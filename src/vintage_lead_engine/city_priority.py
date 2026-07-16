"""
City prioritisation - "which city should we go after next, and why?"

Not one of the original 13 CRM-cleaning rules - a separate, explicit
deliverable of its own. Combines four signals into a single,
transparent score, and (critically) a plain-English reasoning string
built from each city's own real numbers - never a black-box score with
no way to see what drove it.

Deliberately restricted to Physical Store leads with a known city:
online resellers are reached by Instagram DM, not a city visit, so
"which city" has no meaning for them, and a lead with no city on
record can't inform a city-level decision either.
"""
import pandas as pd

WARM_STATUSES = ("Engaged", "Opportunity")
LOST_STATUSES = ("Lost", "Churned")

# Density: how many genuine shop leads are already there. Spend
# potential: total addressable monthly spend. Warmth: how much of the
# pipeline is already engaged rather than cold. Win rate: how
# receptive the market has actually proven to be. Spend potential is
# weighted highest since it's the closest proxy for revenue; win rate
# lowest since it's often built on the smallest sample per city.
PRIORITY_WEIGHTS = {
    "density": 0.25,
    "spend_potential": 0.35,
    "warmth": 0.25,
    "win_rate": 0.15,
}

# Below this many decided (won+lost) leads, a city's win rate is shown
# but flagged as directional only - a 100% win rate from 1 deal isn't
# the same claim as a 100% win rate from 10.
MIN_SAMPLE_FOR_WIN_RATE = 3

CITY_PRIORITY_COLUMNS = [
    "city", "qualified_leads", "total_monthly_spend_potential_gbp",
    "avg_monthly_spend_gbp", "warm_leads", "warm_ratio",
    "won_customers", "lost_or_churned", "win_rate",
    "priority_score", "priority_rank", "priority_reasoning",
]


def _normalise(series):
    rng = series.max() - series.min()
    if rng == 0:
        return pd.Series(0.5, index=series.index)
    return (series - series.min()) / rng


def _reason(row, all_cities):
    """Builds the explanation from the row's own numbers plus its rank
    on each signal relative to the other cities - always the real
    figures for that specific city, never generic boilerplate."""
    n_cities = len(all_cities)
    density_rank = int(all_cities["qualified_leads"].rank(ascending=False, method="min")[row.name])
    spend_rank = int(all_cities["total_monthly_spend_potential_gbp"].rank(ascending=False, method="min")[row.name])
    warmth_rank = int(all_cities["warm_ratio"].rank(ascending=False, method="min")[row.name])

    bits = [
        f"{row['qualified_leads']} qualified physical-store leads (#{density_rank} of {n_cities} by density)",
        f"an estimated £{row['total_monthly_spend_potential_gbp']:,.0f}/month combined spend potential "
        f"(#{spend_rank} of {n_cities})",
        f"{row['warm_ratio'] * 100:.0f}% of the pipeline already warm (Engaged/Opportunity) "
        f"(#{warmth_rank} of {n_cities})",
    ]
    decided = row["won_customers"] + row["lost_or_churned"]
    if pd.isna(row["win_rate"]):
        bits.append("no won/lost history yet to judge receptiveness")
    elif decided < MIN_SAMPLE_FOR_WIN_RATE:
        bits.append(
            f"a {row['win_rate'] * 100:.0f}% win rate ({row['won_customers']} won vs "
            f"{row['lost_or_churned']} lost/churned) - small sample, treat as directional only"
        )
    else:
        bits.append(
            f"a {row['win_rate'] * 100:.0f}% win rate ({row['won_customers']} won vs "
            f"{row['lost_or_churned']} lost/churned)"
        )
    return "; ".join(bits) + "."


def city_prioritisation(df: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per city with genuine Physical Store leads:
    the four raw signals, the combined priority_score (0-1),
    priority_rank (1 = go here next), and priority_reasoning spelling
    out the actual numbers behind the score. Sorted by priority_score
    descending."""
    physical = df[(df["store_type"] == "Physical Store") & (df["city"] != "unknown")]

    if physical.empty:
        return pd.DataFrame(columns=CITY_PRIORITY_COLUMNS)

    rows = []
    for city, g in physical.groupby("city"):
        n = len(g)
        total_spend = float(g["est_monthly_spend_gbp"].sum())
        avg_spend = float(g["est_monthly_spend_gbp"].mean())
        warm = int(g["pipeline_status"].isin(WARM_STATUSES).sum())
        warm_ratio = warm / n if n else 0.0
        won = int(g["pipeline_status"].eq("Customer").sum())
        lost = int(g["pipeline_status"].isin(LOST_STATUSES).sum())
        decided = won + lost
        win_rate = (won / decided) if decided > 0 else None
        rows.append({
            "city": city,
            "qualified_leads": n,
            "total_monthly_spend_potential_gbp": round(total_spend, 0),
            "avg_monthly_spend_gbp": round(avg_spend, 0),
            "warm_leads": warm,
            "warm_ratio": round(warm_ratio, 2),
            "won_customers": won,
            "lost_or_churned": lost,
            "win_rate": None if win_rate is None else round(win_rate, 2),
        })

    out = pd.DataFrame(rows)
    out["win_rate"] = out["win_rate"].astype("float64")

    # Missing win_rate means "no decided leads yet", not "market
    # rejected us" - score those cities at the dataset's mean rather
    # than penalising them to zero for lack of data.
    fallback = out["win_rate"].mean() if out["win_rate"].notna().any() else 0.5
    win_rate_for_scoring = out["win_rate"].fillna(fallback)

    density_score = _normalise(out["qualified_leads"])
    spend_score = _normalise(out["total_monthly_spend_potential_gbp"])
    warmth_score = _normalise(out["warm_ratio"])
    win_rate_score = _normalise(win_rate_for_scoring)

    out["priority_score"] = (
        density_score * PRIORITY_WEIGHTS["density"]
        + spend_score * PRIORITY_WEIGHTS["spend_potential"]
        + warmth_score * PRIORITY_WEIGHTS["warmth"]
        + win_rate_score * PRIORITY_WEIGHTS["win_rate"]
    ).round(3)

    out = out.sort_values("priority_score", ascending=False).reset_index(drop=True)
    out["priority_rank"] = out.index + 1
    out["priority_reasoning"] = out.apply(lambda row: _reason(row, out), axis=1)
    return out[CITY_PRIORITY_COLUMNS]
