"""
Schema and sanity checks for the real-shop enrichment shortlist
(data/real_manchester_shortlist.csv). These guard against exactly the
kind of regressions raised when this file was corrected: a dropped
column silently coming back, a numeric field going unpopulated without
being marked "Not confirmed", or the tier/cluster columns disappearing.
"""
import os

import pandas as pd
import pytest

from vintage_lead_engine.enrichment import load_real_shortlist

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "real_manchester_shortlist.csv")

EXPECTED_COLUMNS = [
    "place_name", "maps_category", "full_address", "lat", "lng",
    "google_review_count", "top_review", "website", "phone", "price_level",
    "locations", "ig_handle", "ig_followers", "ecommerce_present",
    "price_band", "brand_fit", "independent_ownership",
    "qualifies", "qualification_reason",
    "tier", "tier_reasoning", "cluster_id", "cluster_size",
    "research_notes",
]

EXPECTED_ROW_COUNT = 11


@pytest.fixture(scope="module")
def raw_csv():
    return pd.read_csv(DATA_PATH)


def test_row_count(raw_csv):
    assert len(raw_csv) == EXPECTED_ROW_COUNT


def test_exact_column_set_no_rating_or_inventory_scale(raw_csv):
    assert list(raw_csv.columns) == EXPECTED_COLUMNS
    assert "rating" not in raw_csv.columns
    assert "inventory_scale" not in raw_csv.columns


def test_google_review_count_present_and_never_blank(raw_csv):
    # Every row must be either a real number or the literal string
    # "Not confirmed" - never an empty/NaN cell that could be misread
    # as silently missing data.
    assert raw_csv["google_review_count"].notna().all()
    assert (raw_csv["google_review_count"].astype(str).str.strip() != "").all()


def test_tier_and_cluster_columns_populated_for_every_row(raw_csv):
    assert raw_csv["tier"].notna().all()
    assert raw_csv["tier_reasoning"].notna().all()
    assert set(raw_csv["tier"].unique()) <= {"Tier 1", "Tier 2", "Tier 3", "Disqualified"}

    qualified = raw_csv[raw_csv["tier"] != "Disqualified"]
    assert qualified["cluster_id"].notna().all()
    assert qualified["cluster_size"].notna().all()

    disqualified = raw_csv[raw_csv["tier"] == "Disqualified"]
    assert disqualified["cluster_id"].isna().all()


def test_oxfam_originals_is_disqualified_by_charity_override(raw_csv):
    row = raw_csv[raw_csv["place_name"] == "Oxfam Originals"].iloc[0]
    assert row["tier"] == "Disqualified"
    assert "charity" in row["qualification_reason"].lower()


def test_load_real_shortlist_aliases_google_review_count_to_review_count():
    df = load_real_shortlist(DATA_PATH)
    assert "review_count" in df.columns
    pop = df[df["place_name"] == "Pop Boutique Manchester"].iloc[0]
    assert pop["review_count"] == pop["google_review_count"] == 121


def test_northern_quarter_shops_share_a_cluster(raw_csv):
    # Sanity check from the brief: shops genuinely close together on
    # the ground (several blocks of the Northern Quarter) should land
    # in the same cluster_id, not be scattered as singletons.
    nq_shops = ["Pop Boutique Manchester", "Blue Rinse Vintage", "Cow Vintage"]
    cluster_ids = raw_csv.set_index("place_name").loc[nq_shops, "cluster_id"]
    assert cluster_ids.nunique() == 1


def test_geographically_distant_shop_is_not_forced_into_the_main_cluster(raw_csv):
    # SYLK's real address (Ardwick) is ~1.8km from the Northern Quarter
    # core - it must not be chained into the same cluster as the NQ
    # shops just because the pipeline ran on the same dataset.
    by_name = raw_csv.set_index("place_name")
    assert by_name.loc["SYLK", "cluster_id"] != by_name.loc["Pop Boutique Manchester", "cluster_id"]
