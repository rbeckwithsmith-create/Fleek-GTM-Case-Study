"""
Builds the BDR-facing Excel workbook.

Sheet 1 - Enriched Data: every original scrape field + all enrichment
    columns + Tier classification, for every row (qualified AND
    disqualified - nothing is deleted).
Sheet 2 - Ranked Lead List: sorted Tier 1 -> Tier 2 -> Tier 3 ->
    Disqualified, with an auto-filter enabled so disqualified rows
    stay visible and filterable rather than hidden.
Sheet 3 - Cluster Analysis: one row per cluster with its size, Tier
    1/2/3 counts, and which named shops it contains.
Real Shop Demo - the separate, real-shop enrichment worked example
    (see enrichment.py), clearly labelled as a worked example and never
    blended into the dummy-scrape sheets above.

Scale: a fully-styled Excel sheet with tens of thousands of rows is
impractical to build and to browse. If `full_df` is larger than
`max_styled_rows`, the complete result is written to CSV alongside the
workbook and the styled Sheet 1 / Sheet 2 are capped to a bounded top
slice (Tier 1 + Tier 2 rows first, then Tier 3, up to the cap) - see
the README for the exact threshold and rationale.
"""
import os

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")
TOP_ALIGNMENT = Alignment(vertical="top")

# Columns whose content is long free text and should wrap rather than
# be squeezed onto one line.
WRAP_COLUMNS = {
    "qualification_reason", "tier_reasoning", "top_review",
    "research_notes", "price_band",
}

DEFAULT_MAX_STYLED_ROWS = 2000


def _write_sheet(wb: Workbook, sheet_name: str, df: pd.DataFrame, freeze_first_col: bool = False):
    ws: Worksheet = wb.create_sheet(sheet_name)
    if df.empty:
        ws.append(["(no rows)"])
        return ws

    columns = list(df.columns)
    ws.append(columns)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = TOP_ALIGNMENT

    for row in df.itertuples(index=False):
        ws.append(list(row))

    for col_idx, col_name in enumerate(columns, start=1):
        letter = get_column_letter(col_idx)
        wrap = col_name in WRAP_COLUMNS
        width = 40 if wrap else min(max(len(str(col_name)) + 2, 12), 30)
        ws.column_dimensions[letter].width = width
        if wrap:
            for cell in ws[letter][1:]:
                cell.alignment = WRAP_ALIGNMENT
        else:
            for cell in ws[letter][1:]:
                cell.alignment = TOP_ALIGNMENT

    ws.freeze_panes = "B2" if freeze_first_col else "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _cluster_analysis(full_df: pd.DataFrame) -> pd.DataFrame:
    clustered = full_df[full_df["cluster_id"].notna()].copy() if "cluster_id" in full_df.columns else pd.DataFrame()
    if clustered.empty:
        return pd.DataFrame(columns=[
            "cluster_id", "cluster_size", "tier_1_count", "tier_2_count",
            "tier_3_count", "shops_in_cluster",
        ])

    rows = []
    for cluster_id, group in clustered.groupby("cluster_id"):
        tier_counts = group["tier"].value_counts()
        rows.append({
            "cluster_id": cluster_id,
            "cluster_size": len(group),
            "tier_1_count": int(tier_counts.get("Tier 1", 0)),
            "tier_2_count": int(tier_counts.get("Tier 2", 0)),
            "tier_3_count": int(tier_counts.get("Tier 3", 0)),
            "shops_in_cluster": "; ".join(group["place_name"].astype(str)),
        })
    out = pd.DataFrame(rows).sort_values("cluster_size", ascending=False).reset_index(drop=True)
    return out


def _ranked(full_df: pd.DataFrame) -> pd.DataFrame:
    tier_order = {"Tier 1": 0, "Tier 2": 1, "Tier 3": 2, "Disqualified": 3}
    df = full_df.copy()
    df["_sort"] = df["tier"].map(tier_order).fillna(3)
    return df.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)


def _cap_for_styling(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    ranked = _ranked(df)
    return ranked.head(max_rows)


def build_workbook(full_df: pd.DataFrame, output_path: str,
                    real_shop_df: pd.DataFrame = None,
                    max_styled_rows: int = DEFAULT_MAX_STYLED_ROWS) -> dict:
    """full_df must already carry qualifies/qualification_reason, tier/
    tier_reasoning, and (for qualified rows) cluster_id/cluster_size -
    i.e. it's the merged qualified+disqualified, tiered, clustered
    result the CLI assembles before calling this.

    real_shop_df, if given, must already be qualified+tiered the same
    way (see enrichment.py + cli.py) and is written to its own sheet,
    clearly separate from the dummy-scrape sheets.

    Returns a dict describing what was written (paths + row counts) so
    the CLI can report it to the user."""
    result = {"workbook": output_path}

    oversized = len(full_df) > max_styled_rows
    if oversized:
        csv_path = os.path.splitext(output_path)[0] + "_full.csv"
        full_df.to_csv(csv_path, index=False)
        result["full_csv"] = csv_path
        result["full_csv_rows"] = len(full_df)
        styled_df = _cap_for_styling(full_df, max_styled_rows)
        result["excel_capped"] = True
        result["excel_rows"] = len(styled_df)
    else:
        styled_df = full_df
        result["excel_capped"] = False
        result["excel_rows"] = len(styled_df)

    wb = Workbook()
    wb.remove(wb.active)

    _write_sheet(wb, "Enriched Data", styled_df, freeze_first_col=True)
    _write_sheet(wb, "Ranked Lead List", _ranked(styled_df), freeze_first_col=True)
    _write_sheet(wb, "Cluster Analysis", _cluster_analysis(styled_df))

    if real_shop_df is not None and not real_shop_df.empty:
        _write_sheet(wb, "Real Shop Demo (Manchester)", _ranked(real_shop_df), freeze_first_col=True)
        _write_sheet(wb, "Real Shop Demo - Clusters", _cluster_analysis(real_shop_df))
        result["real_shop_rows"] = len(real_shop_df)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    wb.save(output_path)
    return result
