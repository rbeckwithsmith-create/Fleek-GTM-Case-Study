"""
Command-line entrypoint.

    vintage-lead-engine run --input data/part1_manchester_scrape.csv --output output/manchester_results.xlsx
    vintage-lead-engine run --input <any_future_scrape>.csv --output <results>.xlsx

The pipeline (qualify -> cluster -> tier -> workbook) is identical for
any scrape - no hardcoded row lookups, no city-specific logic, no
assumed fields beyond the standard Maps-scrape columns. The optional
--real-shortlist flag layers in the separate real-shop enrichment demo
(see enrichment.py) as its own workbook sheet; it is never blended into
the main scrape's results.
"""
import argparse

import pandas as pd

from .cluster import cluster_by_walking_distance
from .enrichment import load_real_shortlist
from .excel_output import DEFAULT_MAX_STYLED_ROWS, build_workbook
from .qualify import qualify_dataframe
from .tier import tier_dataframe

ENRICHMENT_SIGNAL_COLUMNS = (
    "locations", "ig_followers", "brand_fit", "ecommerce_present", "inventory_scale",
)


def run_pipeline(df: pd.DataFrame, cluster_km: float = 0.6, has_enrichment: bool = False) -> pd.DataFrame:
    """Qualify -> cluster (qualified rows only) -> tier, then merge the
    disqualified rows back in with tier="Disqualified" so nothing is
    ever dropped from the output - they just carry their qualification
    reason forward as their tier reasoning."""
    qualified_df = qualify_dataframe(df)
    qualified_only = qualified_df[qualified_df["qualifies"]].copy()
    disqualified = qualified_df[~qualified_df["qualifies"]].copy()

    clustered = cluster_by_walking_distance(qualified_only, max_km=cluster_km)
    tiered = tier_dataframe(clustered, has_enrichment=has_enrichment)

    disqualified["cluster_id"] = None
    disqualified["cluster_size"] = None
    disqualified["tier"] = "Disqualified"
    disqualified["tier_reasoning"] = disqualified["qualification_reason"]

    full = pd.concat([tiered, disqualified], ignore_index=True, sort=False)
    return full


def _run(args):
    df = pd.read_csv(args.input)
    has_enrichment = any(c in df.columns for c in ENRICHMENT_SIGNAL_COLUMNS)
    full = run_pipeline(df, cluster_km=args.cluster_km, has_enrichment=has_enrichment)

    real_shop_df = None
    if args.real_shortlist:
        real_df = load_real_shortlist(args.real_shortlist)
        real_shop_df = run_pipeline(real_df, cluster_km=args.cluster_km, has_enrichment=True)

    info = build_workbook(
        full, args.output,
        real_shop_df=real_shop_df,
        max_styled_rows=args.max_styled_rows,
    )

    n_qualified = int((full["tier"] != "Disqualified").sum())
    print(f"Processed {len(full)} rows -> {n_qualified} qualified, {len(full) - n_qualified} disqualified.")
    capped_note = "  [capped - see full CSV]" if info.get("excel_capped") else ""
    print(f"Workbook written to {info['workbook']} ({info['excel_rows']} styled rows{capped_note}).")
    if info.get("full_csv"):
        print(f"Full result ({info['full_csv_rows']} rows) also written to {info['full_csv']}.")
    if real_shop_df is not None:
        print(f"Real-shop enrichment demo included ({info.get('real_shop_rows', len(real_shop_df))} rows).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vintage-lead-engine")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the qualify/cluster/tier pipeline on a Maps-style scrape CSV")
    run_p.add_argument("--input", required=True, help="Path to a raw Maps-scrape CSV")
    run_p.add_argument("--output", required=True, help="Path to write the Excel workbook to")
    run_p.add_argument("--cluster-km", type=float, default=0.6,
                        help="Walking-distance clustering threshold in km (default 0.6, ~15 min walk)")
    run_p.add_argument("--max-styled-rows", type=int, default=DEFAULT_MAX_STYLED_ROWS,
                        help="Cap on styled Excel rows before falling back to a full CSV + bounded top slice")
    run_p.add_argument("--real-shortlist", default=None,
                        help="Optional path to a real-shop enrichment shortlist CSV "
                             "(see data/real_manchester_shortlist.csv) to include as a separate demo sheet")
    run_p.set_defaults(func=_run)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
