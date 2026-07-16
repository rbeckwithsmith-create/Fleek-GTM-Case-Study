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

# Columns every row of the dummy Maps scrape carries - the minimum
# schema qualify_dataframe()/cluster_by_walking_distance() need.
SCRAPE_COLUMNS = [
    "place_name", "maps_category", "full_address", "lat", "lng",
    "rating", "review_count", "top_review", "website", "phone", "price_level",
]

# Enrichment-only columns layered on top for the real shortlist. Only
# tier_dataframe() reads locations/ig_followers/brand_fit/
# ecommerce_present/inventory_scale for scoring; ig_handle,
# independent_ownership and research_notes are carried through to the
# output workbook for BDR context but never affect the Tier Key itself.
ENRICHMENT_COLUMNS = [
    "locations", "ig_handle", "ig_followers", "ecommerce_present",
    "price_band", "brand_fit", "inventory_scale", "independent_ownership",
    "research_notes",
]


def load_real_shortlist(path) -> pd.DataFrame:
    """Loads the real-shop shortlist CSV and coerces enrichment columns
    into the types tier_dataframe() expects. "Not confirmed" values are
    treated as missing evidence (NaN / False), never as a 0 or a pass -
    a shop with an unconfirmed Instagram count is scored as if that
    field simply isn't there, exactly like a scrape-only row missing
    enrichment entirely."""
    df = pd.read_csv(path)

    missing = [c for c in SCRAPE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Real shortlist is missing required scrape columns: {missing}")

    for col in ("locations", "ig_followers", "review_count", "rating"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ecommerce_present" in df.columns:
        df["ecommerce_present"] = (
            df["ecommerce_present"].astype(str).str.strip().str.lower().eq("true")
        )
    for col in ("brand_fit", "inventory_scale"):
        if col in df.columns:
            df[col] = df[col].fillna("").replace(NOT_CONFIRMED, "")

    return df
