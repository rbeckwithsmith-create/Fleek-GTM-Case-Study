import pandas as pd

from vintage_lead_engine.crm_cleaning import (
    CATEGORY_MAP,
    STAGE_CLEAN_MAP,
    assign_spend_tier,
    city_spend_tier_breakdown,
    classify_store_type,
    clean_stage,
    contactability_score,
    exclude_no_fit,
    find_duplicate_groups,
    flag_non_uk,
    normalise_category,
    parse_date_flex,
    qualify_lead,
)

ANCHOR = pd.Timestamp("2026-07-16")


def _lead(**kwargs):
    base = {
        "lead_id": "L1", "store_name": "Test Store", "lead_channel_label": None,
        "google_maps_category": None, "instagram_handle": None, "followers": None,
        "items_listed": None, "sell_through_rate": None, "website": None, "email": None,
        "phone": None, "owner_name": None, "address": None, "city": None,
        "neighbourhood": None, "country": None, "lat": None, "lng": None,
        "est_monthly_spend_gbp": None, "lead_stage": "new", "last_contact_date": None,
        "last_purchase_date": None, "notes": None, "lead_source": None,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Rule 1: no-fit exclusion, "not interested" kept
# ---------------------------------------------------------------------------

def test_no_fit_excluded():
    df = pd.DataFrame([_lead(lead_stage="No Fit"), _lead(lead_stage="do not contact")])
    out, removed = exclude_no_fit(df)
    assert removed == 2
    assert len(out) == 0


def test_not_interested_is_not_treated_as_no_fit():
    df = pd.DataFrame([_lead(lead_stage="Not Interested")])
    out, removed = exclude_no_fit(df)
    assert removed == 0
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Rule 2: dedup location-conflict guard - the highest-value test in this
# module. A strong key (Instagram handle) matching across two genuinely
# different countries must be flagged, never merged.
# ---------------------------------------------------------------------------

def test_dedup_does_not_merge_matching_instagram_handle_across_countries():
    df = pd.DataFrame([
        _lead(lead_id="L1", store_name="Retro Finds", instagram_handle="@retrofinds",
              city="London", country="UK"),
        _lead(lead_id="L2", store_name="Retro Finds LA", instagram_handle="@retrofinds",
              city="Los Angeles", country="USA"),
    ])
    grouped, flagged = find_duplicate_groups(df)
    assert grouped.loc[0, "_group"] != grouped.loc[1, "_group"]
    assert len(flagged) == 1
    assert flagged[0][0] == "L1" and flagged[0][1] == "L2"


def test_dedup_merges_matching_key_when_location_agrees():
    df = pd.DataFrame([
        _lead(lead_id="L1", store_name="Retro Finds", instagram_handle="@retrofinds",
              city="London", country="UK"),
        _lead(lead_id="L2", store_name="Retro Finds", instagram_handle="@retrofinds",
              city="London", country="UK"),
    ])
    grouped, flagged = find_duplicate_groups(df)
    assert grouped.loc[0, "_group"] == grouped.loc[1, "_group"]
    assert len(flagged) == 0


def test_dedup_merges_when_location_unknown_on_one_side():
    # Only one side has city/country data - no contradiction to detect,
    # so this should merge (matches find_duplicate_groups' notna() guard).
    df = pd.DataFrame([
        _lead(lead_id="L1", store_name="Retro Finds", instagram_handle="@retrofinds",
              city=None, country=None),
        _lead(lead_id="L2", store_name="Retro Finds", instagram_handle="@retrofinds",
              city="London", country="UK"),
    ])
    grouped, flagged = find_duplicate_groups(df)
    assert grouped.loc[0, "_group"] == grouped.loc[1, "_group"]
    assert len(flagged) == 0


# ---------------------------------------------------------------------------
# Rule 3: stage mapping preserves granularity
# ---------------------------------------------------------------------------

def test_visit_booked_stays_distinct_from_meeting_booked():
    assert clean_stage("visit booked")[1] == "Visit Booked"
    assert clean_stage("meeting booked")[1] == "Meeting Booked"
    assert clean_stage("visit booked")[1] != clean_stage("meeting booked")[1]


def test_trial_pending_stays_distinct_from_trialing():
    assert clean_stage("trial pending")[1] == "Trial Pending"
    assert clean_stage("trialing")[1] == "Trialing"


def test_interested_and_warm_lead_align():
    assert clean_stage("interested")[1] == "Warm Lead"
    assert clean_stage("warm lead")[1] == "Warm Lead"


def test_inbound_stays_separate_from_warm_lead():
    assert clean_stage("inbound")[1] == "Inbound"
    assert clean_stage("inbound")[1] != clean_stage("warm lead")[1]


def test_unmapped_stage_preserves_detail_rather_than_dropping():
    stage_raw, stage_clean, pipeline_status, rank = clean_stage("Some Brand New Stage")
    assert stage_raw == "Some Brand New Stage"
    assert stage_clean == "Some Brand New Stage".title()
    assert pipeline_status == "Prospect"


# ---------------------------------------------------------------------------
# Rule 4: store_type + confidence
# ---------------------------------------------------------------------------

def test_online_signal_wins_regardless_of_lead_channel():
    df = pd.DataFrame([_lead(items_listed=42, address="123 Fake St", lat=51.5, lng=-0.1)])
    out = classify_store_type(df)
    assert out.loc[0, "store_type"] == "Online Retailer"
    assert out.loc[0, "store_type_confidence"] == "Medium"  # both signals fire


def test_address_only_is_high_confidence_physical():
    df = pd.DataFrame([_lead(address="123 Fake St", lat=51.5, lng=-0.1)])
    out = classify_store_type(df)
    assert out.loc[0, "store_type"] == "Physical Store"
    assert out.loc[0, "store_type_confidence"] == "High"


def test_no_signal_is_low_confidence():
    df = pd.DataFrame([_lead()])
    out = classify_store_type(df)
    assert out.loc[0, "store_type_confidence"] == "Low"


# ---------------------------------------------------------------------------
# Rule 5: flag-not-remove, unverified location distinct from non-UK
# ---------------------------------------------------------------------------

def test_non_uk_is_flagged_not_removed_by_default():
    df = pd.DataFrame([_lead(country="France")])
    out, non_uk_count, unverified_count = flag_non_uk(df)
    assert len(out) == 1  # not removed
    assert non_uk_count == 1
    assert unverified_count == 0


def test_missing_country_is_unverified_not_non_uk():
    df = pd.DataFrame([_lead(country=None)])
    out, non_uk_count, unverified_count = flag_non_uk(df)
    assert non_uk_count == 0
    assert unverified_count == 1


def test_remove_true_actually_removes():
    df = pd.DataFrame([_lead(country="France"), _lead(country="UK")])
    out, non_uk_count, _ = flag_non_uk(df, remove=True)
    assert len(out) == 1
    assert non_uk_count == 1


# ---------------------------------------------------------------------------
# Rule 6: date parsing, including the YYYY/MM/DD dayfirst bug fix
# ---------------------------------------------------------------------------

def test_yyyy_mm_dd_slash_format_parsed_correctly_not_swapped():
    # This exact string previously parsed as 4 October (dayfirst=True
    # was wrongly applied to an already year-first string).
    result = parse_date_flex("2026/04/10", ANCHOR)
    assert result == pd.Timestamp("2026-04-10")


def test_dd_mm_yyyy_still_parsed_dayfirst():
    result = parse_date_flex("05/03/2026", ANCHOR)
    assert result == pd.Timestamp("2026-03-05")


def test_bare_date_rolls_back_a_year_if_implausibly_future():
    result = parse_date_flex("20 Dec", ANCHOR)  # anchor is July 2026
    assert result.year == 2025


def test_blank_date_is_nat():
    assert pd.isna(parse_date_flex(None, ANCHOR))
    assert pd.isna(parse_date_flex("", ANCHOR))


# ---------------------------------------------------------------------------
# Rule 9: category normalisation
# ---------------------------------------------------------------------------

def test_known_category_maps_correctly():
    row = {"google_maps_category": "Vintage clothing store", "store_type": "Physical Store"}
    assert normalise_category(row) == "Vintage Store"


def test_blank_category_falls_back_to_store_type():
    row = {"google_maps_category": None, "store_type": "Online Retailer"}
    assert normalise_category(row) == "Online Retailer"


def test_every_category_map_value_is_a_known_bucket():
    known_buckets = {
        "Vintage Store", "Second-Hand Store", "Charity Shop", "Boutique",
        "Clothing Store", "Consignment Store", "Market Stall", "Warehouse", "Other",
    }
    assert set(CATEGORY_MAP.values()) <= known_buckets


# ---------------------------------------------------------------------------
# Rule 9.5: category/name qualification extension
# ---------------------------------------------------------------------------

def test_hard_disqualify_category_rejected():
    row = {"store_name": "Vinyl Revival", "google_maps_category": "Record store", "notes": None}
    qualifies, reason = qualify_lead(row)
    assert not qualifies


def test_charity_name_without_strong_evidence_rejected():
    row = {"store_name": "Oxfam Bridgford", "google_maps_category": "Vintage boutique", "notes": "bit of everything"}
    qualifies, reason = qualify_lead(row)
    assert not qualifies
    assert "charity" in reason.lower()


def test_charity_name_with_strong_evidence_qualifies():
    row = {"store_name": "Sue Ryder Vintage", "google_maps_category": "Vintage boutique",
           "notes": "Curated vintage clothing with reworked Levi's pieces"}
    qualifies, reason = qualify_lead(row)
    assert qualifies


def test_specific_vintage_category_qualifies_without_review_confirmation():
    # Unlike Part 1, a specific vintage-relevant category here needs no
    # notes-text confirmation gate.
    row = {"store_name": "Anything", "google_maps_category": "Vintage clothing store", "notes": None}
    qualifies, reason = qualify_lead(row)
    assert qualifies


# ---------------------------------------------------------------------------
# Rule 11: contactability_score contradiction resolution
# ---------------------------------------------------------------------------

def test_contactability_score_monotonic_scale():
    no_methods = {"email": "unknown", "phone": "unknown", "website": "unknown", "instagram_handle": "unknown"}
    one_method = {"email": "a@b.com", "phone": "unknown", "website": "unknown", "instagram_handle": "unknown"}
    all_methods = {"email": "a@b.com", "phone": "+441234567890", "website": "https://x.com", "instagram_handle": "@x"}
    assert contactability_score(no_methods) == 0
    assert contactability_score(one_method) == 2
    assert contactability_score(all_methods) == 5


# ---------------------------------------------------------------------------
# spend_tier extension: GBP5k+ = Tier 1, GBP2k-4,999 = Tier 2, under GBP2k = Tier 3
# ---------------------------------------------------------------------------

def test_spend_tier_boundaries():
    assert assign_spend_tier(4999) == "Tier 2"
    assert assign_spend_tier(5000) == "Tier 1"
    assert assign_spend_tier(1999) == "Tier 3"
    assert assign_spend_tier(2000) == "Tier 2"


def test_spend_tier_missing_value_is_unknown_not_tier_3():
    assert assign_spend_tier(float("nan")) == "Unknown"
    assert assign_spend_tier(None) == "Unknown"


def test_city_spend_tier_breakdown_sorted_by_total_descending():
    df = pd.DataFrame([
        {"city": "London", "spend_tier": "Tier 1"},
        {"city": "London", "spend_tier": "Tier 2"},
        {"city": "London", "spend_tier": "Tier 2"},
        {"city": "Leeds", "spend_tier": "Tier 3"},
    ])
    out = city_spend_tier_breakdown(df)
    assert list(out.columns) == ["city", "Tier 1", "Tier 2", "Tier 3", "Unknown", "Total"]
    assert out.iloc[0]["city"] == "London"
    assert out.iloc[0]["Total"] == 3
    assert out.iloc[0]["Tier 1"] == 1
    assert out.iloc[0]["Tier 2"] == 2
    assert out.iloc[1]["city"] == "Leeds"
    assert out.iloc[1]["Total"] == 1


def test_spend_tier_column_name_does_not_collide_with_part1_tier():
    # Deliberately not named "tier" - Part 1's Manchester pipeline already
    # uses that name for a completely different (locations/reviews/
    # Instagram/brand-fit based) scoring system.
    df = pd.DataFrame([{"est_monthly_spend_gbp": 6000}])
    df["spend_tier"] = df["est_monthly_spend_gbp"].apply(assign_spend_tier)
    assert "tier" not in df.columns
    assert df.loc[0, "spend_tier"] == "Tier 1"
