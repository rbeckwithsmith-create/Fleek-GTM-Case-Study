"""
Golden-file regression test for Part 2 (CRM cleaning), against the real
Part2_leads_and_customers export. If EXPECTED_UNIQUE_GROUPS or
EXPECTED_QUALIFIED changes, that means the dedup or qualification logic
changed - a deliberate decision that needs a conscious update to this
test, not a silent regression.
"""
import os

import pandas as pd
import pytest

from vintage_lead_engine.crm_cleaning import run_cleaning

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "part2_leads_and_customers.csv")
ANCHOR = pd.Timestamp("2026-07-16")

EXPECTED_STARTING_ROWS = 206
EXPECTED_UNIQUE_GROUPS = 188
EXPECTED_QUALIFIED = 164


@pytest.fixture(scope="module")
def leads_df():
    return pd.read_csv(DATA_PATH)


@pytest.fixture(scope="module")
def cleaning_result(leads_df):
    return run_cleaning(leads_df, date_anchor=ANCHOR)


def test_source_fixture_has_expected_row_count(leads_df):
    assert len(leads_df) == EXPECTED_STARTING_ROWS


def test_unique_business_groups_matches_golden_number(cleaning_result):
    n = cleaning_result["log"]["unique_business_groups"]
    assert n == EXPECTED_UNIQUE_GROUPS, (
        f"Expected {EXPECTED_UNIQUE_GROUPS} unique business groups after dedup, got {n}. "
        f"If this is a deliberate change to the dedup logic, update EXPECTED_UNIQUE_GROUPS; "
        f"otherwise this is a regression."
    )


def test_qualified_count_matches_golden_number(cleaning_result):
    n = cleaning_result["log"]["qualified_leads"]
    assert n == EXPECTED_QUALIFIED, (
        f"Expected {EXPECTED_QUALIFIED} qualified leads after Rule 9.5, got {n}. "
        f"If this is a deliberate change to the qualification rules, update EXPECTED_QUALIFIED; "
        f"otherwise this is a regression."
    )


def test_all_qa_checks_pass(cleaning_result):
    qa = cleaning_result["qa"]
    failed = [(name, detail) for name, passed, detail in qa if not passed]
    assert not failed, f"QA checks failed: {failed}"


def test_no_last_contact_or_purchase_date_is_in_the_future(cleaning_result):
    # Regression guard for the dayfirst/YYYY-MM-DD date-parsing bug found
    # while building Part B - a contact/purchase date can be "never" but
    # never a real date later than the anchor.
    qualified = cleaning_result["qualified"]
    for col in ("last_contact_date", "last_purchase_date"):
        real_dates = qualified[qualified[col] != "never"][col]
        parsed = pd.to_datetime(real_dates)
        assert (parsed <= ANCHOR).all(), f"{col} has a value after the anchor date"


def test_no_qualified_or_disqualified_row_has_a_blank_cell(cleaning_result):
    from vintage_lead_engine.crm_cleaning import TEXT_FIELDS_TO_FILL_UNKNOWN

    qualified = cleaning_result["qualified"]
    for col in TEXT_FIELDS_TO_FILL_UNKNOWN:
        if col in qualified.columns:
            blanks = qualified[col].isna() | (qualified[col].astype(str).str.strip() == "")
            assert not blanks.any(), f"blank cells found in qualified.{col}"
