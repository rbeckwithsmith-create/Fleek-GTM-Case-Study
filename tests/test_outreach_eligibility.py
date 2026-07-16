import pandas as pd

from vintage_lead_engine.outreach import (
    EXCLUDED_STAGES,
    assess_eligibility,
    build_eligibility_frame,
    passes_specificity_test,
)
from vintage_lead_engine.outreach_content import build_message_for_lead

TODAY = pd.Timestamp("2026-07-16")


def _row(**kwargs):
    base = {
        "stage_clean": "New Lead", "pipeline_status": "Prospect",
        "last_contact_date": "never", "notes": "unknown", "owner_name": "unknown",
        "country": "UK", "store_category": "unknown", "lead_source": "unknown",
        "store_name": "Test Store",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Eligibility: the four "do not message" stages
# ---------------------------------------------------------------------------

def test_all_four_excluded_stages_are_ineligible():
    assert EXCLUDED_STAGES == {"In Conversation", "Not Interested", "Closed Lost", "Do Not Contact"}
    for stage in EXCLUDED_STAGES:
        result = assess_eligibility(_row(stage_clean=stage), TODAY)
        assert result["eligible"] is False
        assert result["outreach_type"] == "No Action"


def test_excluded_stage_produces_blank_message_and_populated_logic():
    df = pd.DataFrame([_row(stage_clean=s) for s in EXCLUDED_STAGES])
    elig = build_eligibility_frame(df, today=TODAY)
    messages = elig.apply(build_message_for_lead, axis=1, result_type="expand")
    for _, m in messages.iterrows():
        assert m["SUGGESTED_MESSAGE"] == ""
        assert len(m["MESSAGE_LOGIC"].strip()) > 0


def test_in_conversation_does_not_fabricate_prior_conversation_content():
    df = pd.DataFrame([_row(stage_clean="In Conversation")])
    elig = build_eligibility_frame(df, today=TODAY)
    m = build_message_for_lead(elig.iloc[0])
    assert m["SUGGESTED_MESSAGE"] == ""
    assert "do-not-message" in m["MESSAGE_LOGIC"] or "In Conversation" in m["MESSAGE_LOGIC"]


# ---------------------------------------------------------------------------
# Last-Contacted timing: contacted 3 days ago -> Deferred + exact +10 day follow-up
# ---------------------------------------------------------------------------

def test_contacted_three_days_ago_is_deferred_with_follow_up_ten_days_later():
    last_contact = (TODAY - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    result = assess_eligibility(_row(last_contact_date=last_contact), TODAY)
    assert result["eligible"] is False
    assert result["outreach_type"] == "Deferred"
    expected_follow_up = (TODAY - pd.Timedelta(days=3) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    assert result["follow_up_date"] == expected_follow_up


def test_contacted_exactly_seven_days_ago_is_no_longer_premature():
    last_contact = (TODAY - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    result = assess_eligibility(_row(last_contact_date=last_contact), TODAY)
    assert result["eligible"] is True


def test_never_contacted_is_eligible_and_cold():
    result = assess_eligibility(_row(last_contact_date="never"), TODAY)
    assert result["eligible"] is True
    assert result["outreach_type"] == "Cold"


def test_long_gap_prospect_upgrades_from_cold_to_reengagement():
    last_contact = (TODAY - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    result = assess_eligibility(_row(last_contact_date=last_contact), TODAY)
    assert result["outreach_type"] == "Re-Engagement"


def test_engaged_stage_is_never_labelled_cold_even_with_recent_contact():
    last_contact = (TODAY - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    result = assess_eligibility(
        _row(stage_clean="Negotiating", pipeline_status="Opportunity", last_contact_date=last_contact), TODAY,
    )
    assert result["outreach_type"] == "Re-Engagement"


def test_inbound_stage_always_inbound_type():
    result = assess_eligibility(_row(stage_clean="Inbound", pipeline_status="Prospect"), TODAY)
    assert result["outreach_type"] == "Inbound"


def test_customer_and_churned_pipeline_status_framing():
    customer = assess_eligibility(_row(pipeline_status="Customer"), TODAY)
    churned = assess_eligibility(_row(pipeline_status="Churned"), TODAY)
    assert customer["outreach_type"] == "Customer Check-In"
    assert churned["outreach_type"] == "Churned-Win-Back"


# ---------------------------------------------------------------------------
# The "500 other retailers" specificity test
# ---------------------------------------------------------------------------

def test_generic_compliment_fails_specificity_test():
    assert passes_specificity_test("I love your website") is False
    assert passes_specificity_test("Your business looks amazing") is False


def test_specific_observation_passes_specificity_test():
    assert passes_specificity_test("I noticed you're focused on curated vintage womenswear") is True


def test_banned_cliches_fail_specificity_test():
    assert passes_specificity_test("Hope you're well") is False
    assert passes_specificity_test("Just checking in") is False
