"""
Tier assignment (vectorised).

Tier Key
--------
Tier 1 - meets ANY ONE of: 2+ locations / 250+ Google reviews /
         5,000+ Instagram followers / Strong Brand Fit AND active
         ecommerce presence.
Tier 2 - doesn't clear Tier 1, but meets ANY ONE of: 50-249 Google
         reviews / 500-4,999 Instagram followers / active ecommerce or
         marketplace presence / Medium Brand Fit / Medium Inventory
         Scale.
Tier 3 - a genuine vintage clothing retailer that clears neither
         Tier 1 nor Tier 2.
Disqualified - not a genuine vintage clothing retailer (see qualify.py).

Only whichever fields are actually available get scored - a raw Maps
scrape only ever supplies review_count; Locations, Instagram, Brand
Fit and Ecommerce all need real enrichment. Every tier computed from
scrape-only data says so explicitly in its reasoning, rather than
silently implying it's a complete signal.

Brand Fit is scored on NAMED brands only (5+ mentioned = Strong, 2-4 =
Medium, 0-1 = Weak). Generic language like "designer pieces" without
naming brands doesn't count as Strong - see qualify.py's
STRONG_POSITIVE_PATTERN / the enrichment methodology in the README for
why this matters for the real-shop demo.
"""
import numpy as np
import pandas as pd


def assign_tier(review_count=None, locations=None, ig_followers=None,
                 brand_fit=None, ecommerce_present=None, inventory_scale=None):
    """Single-row version for interactive/manual use (e.g. the real
    shortlist worked example) where each shop's reasoning is hand-written."""
    t1 = []
    if locations is not None and locations >= 2:
        t1.append(f"{locations} locations (Tier 1 needs 2+)")
    if review_count is not None and review_count >= 250:
        t1.append(f"{review_count} Google reviews (Tier 1 needs 250+)")
    if ig_followers is not None and ig_followers >= 5000:
        t1.append(f"{ig_followers:,} Instagram followers (Tier 1 needs 5,000+)")
    if brand_fit == "Strong" and ecommerce_present:
        t1.append("Strong Brand Fit + active ecommerce presence")
    if t1:
        return "Tier 1", "; ".join(t1)

    t2 = []
    if review_count is not None and 50 <= review_count < 250:
        t2.append(f"{review_count} Google reviews (Tier 2 range: 50-249)")
    if ig_followers is not None and 500 <= ig_followers < 5000:
        t2.append(f"{ig_followers:,} Instagram followers (Tier 2 range: 500-4,999)")
    if ecommerce_present:
        t2.append("Active ecommerce / marketplace presence")
    if brand_fit == "Medium":
        t2.append("Medium Brand Fit")
    if inventory_scale == "Medium":
        t2.append("Medium Inventory Scale")
    if t2:
        return "Tier 2", "; ".join(t2)

    return "Tier 3", "No Tier 1 or Tier 2 criterion met on the evidence available"


def tier_dataframe(df: pd.DataFrame, has_enrichment: bool = False) -> pd.DataFrame:
    """Vectorised bulk tiering with numpy.select instead of iterrows().
    Uses whichever of review_count / locations / ig_followers /
    brand_fit / ecommerce_present / inventory_scale columns are
    present; missing columns are simply not scored (same "best
    available evidence" principle as the single-row version)."""
    df = df.copy()
    n = len(df)

    def col(name, default=np.nan):
        return df[name] if name in df.columns else pd.Series([default] * n, index=df.index)

    review_count = col("review_count")
    locations = col("locations")
    ig_followers = col("ig_followers")
    brand_fit = col("brand_fit", default="")
    ecommerce_present = col("ecommerce_present", default=False).fillna(False)
    inventory_scale = col("inventory_scale", default="")

    t1_cond = (
        (locations.fillna(-1) >= 2) |
        (review_count.fillna(-1) >= 250) |
        (ig_followers.fillna(-1) >= 5000) |
        ((brand_fit.fillna("") == "Strong") & ecommerce_present)
    )
    t2_cond = (
        review_count.fillna(-1).between(50, 249) |
        ig_followers.fillna(-1).between(500, 4999) |
        ecommerce_present |
        (brand_fit.fillna("") == "Medium") |
        (inventory_scale.fillna("") == "Medium")
    )

    df["tier"] = np.select([t1_cond, t2_cond], ["Tier 1", "Tier 2"], default="Tier 3")

    scrape_only = not has_enrichment
    suffix = " [scrape-only: Locations/Instagram/Brand Fit/Ecommerce not available without enrichment]" if scrape_only else ""
    reasons = []
    for rc, loc, ig, bf, ec, inv, tier in zip(
        review_count, locations, ig_followers, brand_fit, ecommerce_present, inventory_scale, df["tier"]
    ):
        _, reason = assign_tier(
            review_count=None if pd.isna(rc) else rc,
            locations=None if pd.isna(loc) else loc,
            ig_followers=None if pd.isna(ig) else ig,
            brand_fit=bf if bf else None,
            ecommerce_present=bool(ec),
            inventory_scale=inv if inv else None,
        )
        reasons.append(reason + suffix)
    df["tier_reasoning"] = reasons

    tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2}
    df["_sort"] = df["tier"].map(tier_order)
    sort_cols = ["_sort"] + (["review_count"] if "review_count" in df.columns else [])
    sort_asc = [True] + ([False] * (len(sort_cols) - 1))
    out = df.sort_values(sort_cols, ascending=sort_asc).drop(columns="_sort").reset_index(drop=True)
    return out


# Backwards-compatible name used by earlier build scripts.
def tier_dataframe_from_scrape(df: pd.DataFrame) -> pd.DataFrame:
    return tier_dataframe(df, has_enrichment=False)
