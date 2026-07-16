import pandas as pd

from vintage_lead_engine.tier import assign_tier, tier_dataframe


# ---------------------------------------------------------------------------
# Boundary conditions, one per Tier 1 / Tier 2 criterion, checked just
# above and just below each threshold.
# ---------------------------------------------------------------------------

def test_locations_boundary():
    tier, _ = assign_tier(locations=1)
    assert tier == "Tier 3"
    tier, _ = assign_tier(locations=2)
    assert tier == "Tier 1"


def test_review_count_tier1_boundary():
    tier, _ = assign_tier(review_count=249)
    assert tier == "Tier 2"
    tier, _ = assign_tier(review_count=250)
    assert tier == "Tier 1"


def test_review_count_tier2_lower_boundary():
    tier, _ = assign_tier(review_count=49)
    assert tier == "Tier 3"
    tier, _ = assign_tier(review_count=50)
    assert tier == "Tier 2"


def test_ig_followers_tier1_boundary():
    tier, _ = assign_tier(ig_followers=4999)
    assert tier == "Tier 2"
    tier, _ = assign_tier(ig_followers=5000)
    assert tier == "Tier 1"


def test_ig_followers_tier2_lower_boundary():
    tier, _ = assign_tier(ig_followers=499)
    assert tier == "Tier 3"
    tier, _ = assign_tier(ig_followers=500)
    assert tier == "Tier 2"


def test_strong_brand_fit_requires_ecommerce_for_tier1():
    tier, _ = assign_tier(brand_fit="Strong", ecommerce_present=False)
    assert tier == "Tier 3"  # Strong alone is not a Tier 2 criterion either
    tier, _ = assign_tier(brand_fit="Strong", ecommerce_present=True)
    assert tier == "Tier 1"


def test_medium_brand_fit_is_tier2():
    tier, _ = assign_tier(brand_fit="Medium")
    assert tier == "Tier 2"


def test_ecommerce_alone_is_tier2():
    tier, _ = assign_tier(ecommerce_present=True)
    assert tier == "Tier 2"


def test_medium_inventory_scale_is_tier2():
    tier, _ = assign_tier(inventory_scale="Medium")
    assert tier == "Tier 2"


def test_no_evidence_is_tier3():
    tier, reason = assign_tier()
    assert tier == "Tier 3"
    assert "no tier 1 or tier 2" in reason.lower()


# ---------------------------------------------------------------------------
# tier_dataframe (vectorised bulk path) must agree with assign_tier
# (single-row path) on the same boundary cases.
# ---------------------------------------------------------------------------

def test_tier_dataframe_matches_assign_tier_on_boundaries():
    rows = [
        {"place_name": "A", "review_count": 249},
        {"place_name": "B", "review_count": 250},
        {"place_name": "C", "ig_followers": 4999},
        {"place_name": "D", "ig_followers": 5000},
        {"place_name": "E", "locations": 1},
        {"place_name": "F", "locations": 2},
    ]
    df = pd.DataFrame(rows)
    out = tier_dataframe(df, has_enrichment=True).set_index("place_name")

    assert out.loc["A", "tier"] == "Tier 2"
    assert out.loc["B", "tier"] == "Tier 1"
    assert out.loc["C", "tier"] == "Tier 2"
    assert out.loc["D", "tier"] == "Tier 1"
    assert out.loc["E", "tier"] == "Tier 3"
    assert out.loc["F", "tier"] == "Tier 1"


def test_scrape_only_tiering_states_limitation_in_reasoning():
    df = pd.DataFrame([{"place_name": "A", "review_count": 300}])
    out = tier_dataframe(df, has_enrichment=False)
    assert out.iloc[0]["tier"] == "Tier 1"
    assert "scrape-only" in out.iloc[0]["tier_reasoning"].lower()


def test_enriched_tiering_does_not_add_scrape_only_caveat():
    df = pd.DataFrame([{"place_name": "A", "review_count": 300}])
    out = tier_dataframe(df, has_enrichment=True)
    assert "scrape-only" not in out.iloc[0]["tier_reasoning"].lower()
