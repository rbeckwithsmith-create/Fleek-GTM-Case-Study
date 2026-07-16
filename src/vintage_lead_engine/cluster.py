"""
Geographic clustering for walkable BDR visit routes (spatially
partitioned, exact complete-linkage).

Groups qualified shops within roughly a 15-minute walk (~0.6km, the
default max_km) of each other, using COMPLETE linkage: every member of
a cluster is genuinely within max_km of every OTHER member, not just
connected via a chain of neighbours (single-linkage chaining). An
earlier version of this code unioned any two points within threshold
directly - that strings far-apart points into one giant cluster via
intermediate neighbours, which is wrong for a walking-distance cluster
(a BDR visiting "cluster 3" should never find the last shop on the list
is 2km from the first). Complete linkage bounds the cluster's diameter
by the threshold instead.

Scaling: a full n x n distance matrix (the naive approach) is fine at
~100 rows and infeasible at tens of thousands (a 30,000 x 30,000 matrix
is 7GB+ as float64, and scipy's own docs describe linkage() as
impractical above roughly 10-20k points). This module bins points into
a grid (cell size = max_km) and finds CONNECTED COMPONENTS of occupied
cells (two cells are "connected" if they're in each other's 3x3
neighbourhood). Every point in a connected component is gathered into
ONE combined candidate set, and exact complete-linkage runs ONCE on
that whole set.

This produces IDENTICAL output to the full O(n^2) method: complete
linkage cut at threshold t can only ever group points directly within t
of each other, so no cluster can span two points more than one
cell-halo apart, and the 3x3 neighbourhood is sufficient to catch every
valid cluster. A naive alternative - clustering each cell's 3x3
neighbourhood independently and keeping only the "home" cell's points -
is wrong: a genuine cluster whose members sit in three different home
cells gets computed three separate times, each with its own unrelated
local label numbering, and clusters silently fragment at grid
boundaries. Connected-components fixes this by ensuring there's only
ever one label space per genuinely contiguous region.

Cost now scales with the size of each geographically contiguous region
(a city, a town), not the national total - a nationwide scrape is many
independent small clustering problems, not one giant one.
"""
import numpy as np
import pandas as pd


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlambda / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _exact_complete_linkage(lat, lng, max_km):
    """The correctness-preserving core: exact complete-linkage on a small
    point set. Only ever called on a single connected component of the
    grid, so n here is bounded by local density, not the whole dataset."""
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform

    n = len(lat)
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([1])

    lat_a = lat.reshape(-1, 1)
    lng_a = lng.reshape(-1, 1)
    dist_matrix = haversine_km(lat_a, lng_a, lat_a.T, lng_a.T)
    np.fill_diagonal(dist_matrix, 0.0)
    condensed = squareform(dist_matrix, checks=False)
    Z = linkage(condensed, method="complete")
    return fcluster(Z, t=max_km, criterion="distance")


def cluster_by_walking_distance(df: pd.DataFrame, max_km: float = 0.6, max_component_points: int = 6000) -> pd.DataFrame:
    """Adds `cluster_id` (e.g. "C1") and `cluster_size` columns.

    max_component_points is a safety-valve marker for future tuning;
    correctness always wins here, so a single connected component is
    clustered in full regardless of size (even a "huge" single region
    is bounded by that region's own shop count, not the national
    total)."""
    df = df.reset_index(drop=True).copy()
    n = len(df)
    if n == 0:
        df["cluster_id"] = pd.Series([], dtype=object)
        df["cluster_size"] = pd.Series([], dtype=int)
        return df
    if n == 1:
        df["cluster_id"] = ["C1"]
        df["cluster_size"] = [1]
        return df

    # Local planar projection (km) centred on the dataset - fine for
    # grid binning at city/country scale; exact haversine is still used
    # for the actual distance comparisons inside each component.
    lat0 = np.radians(df["lat"].mean())
    R = 6371.0
    x = np.radians(df["lng"]) * R * np.cos(lat0)
    y = np.radians(df["lat"]) * R

    cell_size = max_km
    cx = np.floor(x / cell_size).astype(int).values
    cy = np.floor(y / cell_size).astype(int).values

    # Union-find over CELL coordinates (not points): connect any two
    # occupied cells that are within each other's 3x3 neighbourhood.
    occupied_cells = sorted(set(zip(cx.tolist(), cy.tolist())))
    parent = {c: c for c in occupied_cells}

    def find(c):
        root = c
        while parent[root] != root:
            root = parent[root]
        while parent[c] != root:
            parent[c], c = root, parent[c]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    occupied_set = set(occupied_cells)
    for (ccx, ccy) in occupied_cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                neighbor = (ccx + dx, ccy + dy)
                if neighbor in occupied_set:
                    union((ccx, ccy), neighbor)

    cell_component = {c: find(c) for c in occupied_cells}
    point_component = [cell_component[(a, b)] for a, b in zip(cx.tolist(), cy.tolist())]
    df["_component"] = point_component

    final_cluster_id = np.empty(n, dtype=object)
    global_counter = 0

    for comp_id, positions in df.groupby("_component").indices.items():
        positions = np.asarray(positions)
        comp_lat = df["lat"].values[positions]
        comp_lng = df["lng"].values[positions]

        local_labels = _exact_complete_linkage(comp_lat, comp_lng, max_km).astype(str)

        label_to_global = {}
        for pos, lbl in zip(positions, local_labels):
            if lbl not in label_to_global:
                global_counter += 1
                label_to_global[lbl] = global_counter
            final_cluster_id[pos] = f"C{label_to_global[lbl]}"

    df["cluster_id"] = final_cluster_id
    df["cluster_size"] = df.groupby("cluster_id")["cluster_id"].transform("count")
    df = df.drop(columns=["_component"])

    # Renumber sequentially (C1, C2, ...) sorted by size descending, for
    # a readable/stable output rather than arbitrary processing order.
    order = (df[["cluster_id", "cluster_size"]]
             .drop_duplicates()
             .sort_values("cluster_size", ascending=False)["cluster_id"].tolist())
    relabel = {old: f"C{i+1}" for i, old in enumerate(order)}
    df["cluster_id"] = df["cluster_id"].map(relabel)
    return df
