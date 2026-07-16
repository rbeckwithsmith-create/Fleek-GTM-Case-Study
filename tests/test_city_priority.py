import pandas as pd

from vintage_lead_engine.city_priority import CITY_PRIORITY_COLUMNS, city_prioritisation


def _lead(city, store_type="Physical Store", pipeline_status="Prospect", spend=1000):
    return {
        "city": city, "store_type": store_type, "pipeline_status": pipeline_status,
        "est_monthly_spend_gbp": spend,
    }


def test_excludes_online_retailers_and_unknown_city():
    df = pd.DataFrame([
        _lead("London", store_type="Online Retailer"),
        _lead("unknown"),
        _lead("London"),
    ])
    out = city_prioritisation(df)
    assert list(out["city"]) == ["London"]
    assert out.iloc[0]["qualified_leads"] == 1


def test_empty_input_returns_empty_frame_with_expected_columns():
    df = pd.DataFrame([_lead("London", store_type="Online Retailer")])
    out = city_prioritisation(df)
    assert out.empty
    assert list(out.columns) == CITY_PRIORITY_COLUMNS


def test_higher_density_spend_and_warmth_ranks_first():
    df = pd.DataFrame([
        # Strong city: many leads, high spend, mostly warm
        *[_lead("Strong City", pipeline_status="Engaged", spend=5000) for _ in range(8)],
        # Weak city: one lead, low spend, cold
        _lead("Weak City", pipeline_status="Prospect", spend=200),
    ])
    out = city_prioritisation(df)
    assert out.iloc[0]["city"] == "Strong City"
    assert out.iloc[0]["priority_rank"] == 1
    assert out.iloc[-1]["city"] == "Weak City"


def test_win_rate_missing_when_no_decided_leads():
    df = pd.DataFrame([_lead("London", pipeline_status="Prospect") for _ in range(3)])
    out = city_prioritisation(df)
    assert pd.isna(out.iloc[0]["win_rate"])
    assert "no won/lost history yet" in out.iloc[0]["priority_reasoning"]


def test_win_rate_computed_from_won_and_lost_statuses():
    df = pd.DataFrame([
        _lead("London", pipeline_status="Customer"),
        _lead("London", pipeline_status="Customer"),
        _lead("London", pipeline_status="Lost"),
        _lead("London", pipeline_status="Churned"),
    ])
    out = city_prioritisation(df)
    row = out.iloc[0]
    assert row["won_customers"] == 2
    assert row["lost_or_churned"] == 2
    assert row["win_rate"] == 0.5


def test_small_sample_win_rate_flagged_as_directional():
    df = pd.DataFrame([
        _lead("London", pipeline_status="Customer"),
        _lead("London", pipeline_status="Prospect"),
    ])
    out = city_prioritisation(df)
    assert "small sample" in out.iloc[0]["priority_reasoning"]


def test_reasoning_cites_real_numbers_not_generic_text():
    df = pd.DataFrame([
        _lead("London", pipeline_status="Engaged", spend=6000),
        _lead("Leeds", pipeline_status="Prospect", spend=500),
    ])
    out = city_prioritisation(df)
    london_reason = out[out["city"] == "London"].iloc[0]["priority_reasoning"]
    assert "London" not in london_reason  # doesn't need to repeat the name
    assert "£" in london_reason
    assert "%" in london_reason


def test_priority_rank_is_sequential_starting_at_one():
    df = pd.DataFrame([
        _lead("A", spend=1000), _lead("B", spend=2000), _lead("C", spend=3000),
    ])
    out = city_prioritisation(df)
    assert list(out["priority_rank"]) == [1, 2, 3]
