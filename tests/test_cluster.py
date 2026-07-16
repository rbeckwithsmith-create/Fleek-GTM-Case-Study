import numpy as np
import pandas as pd

from vintage_lead_engine.cluster import cluster_by_walking_distance, haversine_km

MAX_KM = 0.6
BASE_LAT = 53.4800
BASE_LNG = -2.2400


def _lng_offset_km(km, lat=BASE_LAT):
    """Longitude delta (degrees) that corresponds to `km` at `lat`."""
    return km / (111.32 * np.cos(np.radians(lat)))


def test_complete_linkage_does_not_chain_through_an_intermediate_point():
    """A, B are 0.35km apart; B, C are 0.35km apart; A, C are 0.70km
    apart (over the 0.6km threshold). Single-linkage chaining would
    wrongly put all three in one cluster via B. Complete linkage must
    not: cluster diameter is bounded by the threshold, so A and C can
    never end up in the same cluster."""
    df = pd.DataFrame([
        {"place_name": "A", "lat": BASE_LAT, "lng": BASE_LNG},
        {"place_name": "B", "lat": BASE_LAT, "lng": BASE_LNG + _lng_offset_km(0.35)},
        {"place_name": "C", "lat": BASE_LAT, "lng": BASE_LNG + _lng_offset_km(0.70)},
    ])
    out = cluster_by_walking_distance(df, max_km=MAX_KM)
    clusters = out.groupby("cluster_id")["place_name"].apply(frozenset).tolist()

    assert frozenset({"A", "B", "C"}) not in clusters
    a_cluster = out.set_index("place_name").loc["A", "cluster_id"]
    c_cluster = out.set_index("place_name").loc["C", "cluster_id"]
    assert a_cluster != c_cluster


def test_every_cluster_member_within_threshold_of_every_other_member():
    """Direct check of the complete-linkage guarantee itself: for every
    cluster with 2+ members, every pairwise distance inside it must be
    <= max_km - not just connected via a chain of neighbours."""
    rng = np.random.default_rng(7)
    n = 60
    # Three loose blobs, spread widely enough that some points will
    # land far apart within the same rough neighbourhood.
    centres = [(53.48, -2.24), (53.50, -2.20), (53.46, -2.28)]
    rows = []
    for i in range(n):
        clat, clng = centres[i % len(centres)]
        jitter_km = rng.exponential(0.5)
        angle = rng.uniform(0, 2 * np.pi)
        dlat = (jitter_km / 111.0) * np.sin(angle)
        dlng = _lng_offset_km(jitter_km, clat) * np.cos(angle)
        rows.append({"place_name": f"P{i}", "lat": clat + dlat, "lng": clng + dlng})
    df = pd.DataFrame(rows)

    out = cluster_by_walking_distance(df, max_km=MAX_KM)
    for cluster_id, group in out.groupby("cluster_id"):
        if len(group) < 2:
            continue
        lat = group["lat"].values
        lng = group["lng"].values
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                d = haversine_km(lat[i], lng[i], lat[j], lng[j])
                assert d <= MAX_KM + 1e-9, (
                    f"cluster {cluster_id} has members {d:.3f}km apart, "
                    f"over the {MAX_KM}km threshold"
                )


def test_scaled_clustering_matches_brute_force_ground_truth():
    """The spatially-partitioned version must produce IDENTICAL output
    to a brute-force O(n^2) complete-linkage run - not just the same
    size shape. This is the regression that catches the "per-cell
    independent clustering fragments true clusters" bug."""
    from itertools import combinations

    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    rng = np.random.default_rng(42)
    n = 50
    centres = [(53.48, -2.24), (53.4805, -2.2395), (53.55, -2.10), (53.30, -2.50)]
    rows = []
    for i in range(n):
        clat, clng = centres[i % len(centres)]
        jitter_km = rng.exponential(0.4)
        angle = rng.uniform(0, 2 * np.pi)
        dlat = (jitter_km / 111.0) * np.sin(angle)
        dlng = _lng_offset_km(jitter_km, clat) * np.cos(angle)
        rows.append({"place_name": f"P{i}", "lat": clat + dlat, "lng": clng + dlng})
    df = pd.DataFrame(rows)

    scaled = cluster_by_walking_distance(df, max_km=MAX_KM)
    scaled_groups = set(scaled.groupby("cluster_id")["place_name"].apply(frozenset))

    bf = df.reset_index(drop=True)
    dm = [[0.0] * n for _ in range(n)]
    for i, j in combinations(range(n), 2):
        d = haversine_km(bf.loc[i, "lat"], bf.loc[i, "lng"], bf.loc[j, "lat"], bf.loc[j, "lng"])
        dm[i][j] = dm[j][i] = d
    labels = fcluster(linkage(squareform(dm), method="complete"), t=MAX_KM, criterion="distance")
    bf["brute_cluster"] = labels
    brute_groups = set(bf.groupby("brute_cluster")["place_name"].apply(frozenset))

    assert scaled_groups == brute_groups


def test_cluster_columns_and_size_consistency():
    df = pd.DataFrame([
        {"place_name": "A", "lat": BASE_LAT, "lng": BASE_LNG},
        {"place_name": "B", "lat": BASE_LAT, "lng": BASE_LNG + _lng_offset_km(0.1)},
        {"place_name": "Far", "lat": 55.0, "lng": -4.0},
    ])
    out = cluster_by_walking_distance(df, max_km=MAX_KM)
    assert "cluster_id" in out.columns
    assert "cluster_size" in out.columns
    for cluster_id, group in out.groupby("cluster_id"):
        assert (group["cluster_size"] == len(group)).all()


def test_empty_and_single_row_inputs():
    empty = pd.DataFrame(columns=["place_name", "lat", "lng"])
    out = cluster_by_walking_distance(empty, max_km=MAX_KM)
    assert len(out) == 0

    single = pd.DataFrame([{"place_name": "Only", "lat": BASE_LAT, "lng": BASE_LNG}])
    out = cluster_by_walking_distance(single, max_km=MAX_KM)
    assert len(out) == 1
    assert out.iloc[0]["cluster_size"] == 1
