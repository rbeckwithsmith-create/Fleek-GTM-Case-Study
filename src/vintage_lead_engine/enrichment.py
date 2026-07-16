"""
Real-shop enrichment data model - Part 2 of the case study.

The dummy Manchester scrape (data/part1_manchester_scrape.csv) has
placeholder business names, so real enrichment (Instagram, locations,
ecommerce) can't be looked up against it - there's nothing real to
find. This module instead defines the schema for a SEPARATE, genuinely
researched shortlist of real, currently-trading Manchester vintage
clothing shops (data/real_manchester_shortlist.csv), so the exact same
qualify_dataframe() / tier_dataframe() functions can be run against it
as a worked example of what the framework produces once real
enrichment data exists.

Every enrichment field below was researched, not guessed. Where a fact
couldn't be confirmed (an exact Instagram follower count, a review
count, a price point), the source CSV carries the literal string
"Not confirmed" rather than a plausible-looking fabricated number -
see the README's enrichment methodology section for the reasoning and
per-shop sourcing notes.
"""
import numpy as np
import pandas as pd

NOT_CONFIRMED = "Not confirmed"

# Columns every row of the real shortlist must carry - the minimum
# schema qualify_dataframe()/cluster_by_walking_distance() need, plus
# google_review_count (see below). Note this is deliberately NOT the
# same list as the dummy scrape's columns: `rating` was never part of
# the requested enrichment fields or the Tier Key, so it has no place
# here, and `review_count` is named `google_review_count` instead of
# the generic scrape-schema name to make explicit that it was looked
# up from each shop's real Google Maps listing, not scraped in bulk.
REQUIRED_COLUMNS = [
    "place_name", "maps_category", "full_address", "lat", "lng",
    "google_review_count", "top_review", "website", "phone", "price_level",
]

# Enrichment-only columns layered on top for the real shortlist. Only
# tier_dataframe() reads locations/ig_followers/brand_fit/
# ecommerce_present for scoring; ig_handle, independent_ownership and
# research_notes are carried through to the output workbook for BDR
# context but never affect the Tier Key itself. There is no
# inventory_scale column here - it was in the master case-study
# brief's general enrichment field list but was never actually
# requested for this specific shortlist.
ENRICHMENT_COLUMNS = [
    "locations", "ig_handle", "ig_followers", "ecommerce_present",
    "price_band", "brand_fit", "independent_ownership", "research_notes",
]


def load_real_shortlist(path) -> pd.DataFrame:
    """Loads the real-shop shortlist CSV and coerces enrichment columns
    into the types tier_dataframe() expects. "Not confirmed" values are
    treated as missing evidence (NaN / False), never as a 0 or a pass -
    a shop with an unconfirmed Instagram count is scored as if that
    field simply isn't there, exactly like a scrape-only row missing
    enrichment entirely.

    tier_dataframe() scores a column literally named "review_count", so
    this loader aliases google_review_count into a "review_count"
    column purely for that in-memory scoring pass - it is never written
    back out to the CSV, which keeps google_review_count as the single
    source of truth on disk instead of two columns holding the same
    number under different names."""
    df = pd.read_csv(path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Real shortlist is missing required columns: {missing}")

    for col in ("locations", "ig_followers", "google_review_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ecommerce_present" in df.columns:
        df["ecommerce_present"] = (
            df["ecommerce_present"].astype(str).str.strip().str.lower().eq("true")
        )
    if "brand_fit" in df.columns:
        df["brand_fit"] = df["brand_fit"].fillna("").replace(NOT_CONFIRMED, "")

    df["review_count"] = df["google_review_count"]

    return df
