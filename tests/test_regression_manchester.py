"""
Golden-file regression test against the original hand-verified
Manchester case study. If EXPECTED_QUALIFIED_COUNT changes, that means
the qualification logic changed - a deliberate decision that needs a
conscious update to this test, not a silent regression.
"""
import os

import pandas as pd
import pytest

from vintage_lead_engine.cluster import cluster_by_walking_distance, haversine_km
from vintage_lead_engine.qualify import qualify_dataframe
from vintage_lead_engine.tier import tier_dataframe_from_scrape

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "part1_manchester_scrape.csv")

EXPECTED_TOTAL_ROWS = 121
EXPECTED_QUALIFIED_COUNT = 34


@pytest.fixture(scope="module")
def scrape_df():
    return pd.read_csv(DATA_PATH)


def test_scrape_fixture_has_expected_row_count(scrape_df):
    assert len(scrape_df) == EXPECTED_TOTAL_ROWS


def test_qualified_count_matches_known_golden_number(scrape_df):
    qualified_df = qualify_dataframe(scrape_df)
    n_qualified = int(qualified_df["qualifies"].sum())
    assert n_qualified == EXPECTED_QUALIFIED_COUNT, (
        f"Expected {EXPECTED_QUALIFIED_COUNT} of {EXPECTED_TOTAL_ROWS} rows to qualify, "
        f"got {n_qualified}. If this is a deliberate change to the qualification "
        f"rules, update EXPECTED_QUALIFIED_COUNT; otherwise this is a regression."
    )


def test_scaled_clustering_matches_brute_force_on_the_real_dataset(scrape_df):
    """Same brute-force cross-check as the module's own dev-time
    regression, kept here as a real pytest so CI catches it."""
    from itertools import combinations

    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    qualified_df = qualify_dataframe(scrape_df)
    qualified_only = qualified_df[qualified_df["qualifies"]].copy()

    clustered = cluster_by_walking_distance(qualified_only, max_km=0.6)

    bf_df = qualified_only.reset_index(drop=True).copy()
    n = len(bf_df)
    dm = [[0.0] * n for _ in range(n)]
    for i, j in combinations(range(n), 2):
        d = haversine_km(bf_df.loc[i, "lat"], bf_df.loc[i, "lng"], bf_df.loc[j, "lat"], bf_df.loc[j, "lng"])
        dm[i][j] = dm[j][i] = d
    labels = fcluster(linkage(squareform(dm), method="complete"), t=0.6, criterion="distance")
    bf_df["brute_cluster"] = labels

    brute_groups = set(bf_df.groupby("brute_cluster")["place_name"].apply(frozenset))
    scaled_groups = set(clustered.groupby("cluster_id")["place_name"].apply(frozenset))
    assert brute_groups == scaled_groups


def test_full_pipeline_runs_end_to_end_without_error(scrape_df):
    qualified_df = qualify_dataframe(scrape_df)
    qualified_only = qualified_df[qualified_df["qualifies"]].copy()
    clustered = cluster_by_walking_distance(qualified_only, max_km=0.6)
    tiered = tier_dataframe_from_scrape(clustered)

    assert len(tiered) == EXPECTED_QUALIFIED_COUNT
    assert set(tiered["tier"].unique()) <= {"Tier 1", "Tier 2", "Tier 3"}
    assert tiered["tier_reasoning"].str.contains("scrape-only", case=False).all()
