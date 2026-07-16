"""
Command-line entrypoint.

    vintage-lead-engine run --input data/part1_manchester_scrape.csv --output output/manchester_results.xlsx
    vintage-lead-engine run --input <any_future_scrape>.csv --output <results>.xlsx
    vintage-lead-engine clean-crm --input data/part2_leads_and_customers.csv --output output/crm_cleaned.xlsx
    vintage-lead-engine generate-outreach --input data/part2_leads_and_customers.csv --output output/crm_with_outreach.xlsx

The Part 1 pipeline (qualify -> cluster -> tier -> workbook) is
identical for any scrape - no hardcoded row lookups, no city-specific
logic, no assumed fields beyond the standard Maps-scrape columns. The
optional --real-shortlist flag layers in the separate real-shop
enrichment demo (see enrichment.py) as its own workbook sheet; it is
never blended into the main scrape's results.

clean-crm and generate-outreach are Part 2 (self-contained - they only
touch the Part2_leads_and_customers data, never Part 1's). clean-crm
runs the CRM cleaning rules alone (crm_cleaning.py); generate-outreach
runs cleaning AND adds the five outreach columns (outreach.py +
outreach_content.py) to the same Cleaned Dataset sheet. See the
README's Part 2 section for what outreach_content.py's authored
message content is and is not - it is the specific, hand-authored
content for the batch of leads in data/part2_leads_and_customers.csv,
wired up as testable code rather than a general-purpose message
generator; it will decline (blank message, clear reasoning) rather
than guess at content for notes/phrases it doesn't recognise.
"""
import argparse
import os

import pandas as pd

from .cluster import cluster_by_walking_distance
from .crm_cleaning import run_cleaning, sort_by_spend_tier
from .enrichment import load_real_shortlist
from .excel_output import DEFAULT_MAX_STYLED_ROWS, build_crm_workbook, build_workbook
from .outreach import build_eligibility_frame
from .outreach_content import build_message_for_lead
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


def _run_crm_cleaning(args):
    df = pd.read_csv(args.input)
    anchor = pd.Timestamp(args.anchor_date) if args.anchor_date else pd.Timestamp.now().normalize()
    return run_cleaning(df, date_anchor=anchor, remove_non_uk=args.remove_non_uk)


def _csv_path_for(output_path):
    return os.path.splitext(output_path)[0] + ".csv"


def _clean_crm(args):
    result = _run_crm_cleaning(args)
    qualified = sort_by_spend_tier(result["qualified"])
    info = build_crm_workbook(
        qualified, result["disqualified"], result["log"], result["qa"], result["flagged_pairs"],
        args.output, city_spend_tier_breakdown=result["city_spend_tier_breakdown"],
    )
    csv_path = _csv_path_for(args.output)
    qualified.to_csv(csv_path, index=False)

    log = result["log"]
    print(f"Cleaned {log['starting_rows']} rows -> {log['unique_business_groups']} unique businesses "
          f"-> {log['qualified_leads']} qualified ({log['disqualified_by_rule_9_5']} disqualified by "
          f"category/charity-name qualification).")
    print(f"QA checks: {log['qa_checks_passed']}/{log['qa_checks_total']} passed.")
    print(f"Spend tier counts: {log['spend_tier_counts']}.")
    print(f"Workbook written to {info['workbook']}.")
    print(f"Cleaned Dataset also written to {csv_path}.")


def _generate_outreach(args):
    result = _run_crm_cleaning(args)
    anchor = pd.Timestamp(args.anchor_date) if args.anchor_date else pd.Timestamp.now().normalize()

    elig = build_eligibility_frame(result["qualified"], today=anchor)
    messages = elig.apply(build_message_for_lead, axis=1, result_type="expand")
    elig = pd.concat([elig, messages], axis=1)
    elig = elig.drop(columns=["_ELIGIBILITY_REASON", "_DAYS_SINCE_CONTACT"])
    elig = sort_by_spend_tier(elig)

    info = build_crm_workbook(
        elig, result["disqualified"], result["log"], result["qa"], result["flagged_pairs"],
        args.output, city_spend_tier_breakdown=result["city_spend_tier_breakdown"],
    )
    csv_path = _csv_path_for(args.output)
    elig.to_csv(csv_path, index=False)

    n_eligible = int(elig["ELIGIBLE"].sum())
    n_drafted = int((elig["SUGGESTED_MESSAGE"] != "").sum())
    print(f"Cleaned {result['log']['qualified_leads']} qualified leads -> {n_eligible} eligible for outreach "
          f"-> {n_drafted} messages drafted ({n_eligible - n_drafted} eligible but declined for lack of "
          f"personalisation).")
    print(f"Spend tier counts: {result['log']['spend_tier_counts']}.")
    print(f"Workbook written to {info['workbook']}.")
    print(f"Cleaned Dataset + outreach columns also written to {csv_path}.")


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

    clean_p = sub.add_parser("clean-crm", help="Run the Part 2 CRM cleaning rules on the leads/customers CSV")
    clean_p.add_argument("--input", required=True, help="Path to the raw Part2_leads_and_customers CSV")
    clean_p.add_argument("--output", required=True, help="Path to write the Excel workbook to")
    clean_p.add_argument("--anchor-date", default=None,
                          help="Reference 'today' for date parsing/inference, YYYY-MM-DD (default: now) - "
                               "pass this for reproducible output rather than relying on the run date")
    clean_p.add_argument("--remove-non-uk", action="store_true",
                          help="Remove non-UK leads instead of flagging them (Rule 5's literal-brief toggle; "
                               "default is flag-only)")
    clean_p.set_defaults(func=_clean_crm)

    outreach_p = sub.add_parser("generate-outreach",
                                 help="Run Part 2 CRM cleaning AND add the five outreach columns")
    outreach_p.add_argument("--input", required=True, help="Path to the raw Part2_leads_and_customers CSV")
    outreach_p.add_argument("--output", required=True, help="Path to write the Excel workbook to")
    outreach_p.add_argument("--anchor-date", default=None,
                             help="Reference 'today' for date parsing/Last-Contacted timing, YYYY-MM-DD "
                                  "(default: now) - pass this for reproducible output")
    outreach_p.add_argument("--remove-non-uk", action="store_true",
                             help="Remove non-UK leads instead of flagging them (see clean-crm)")
    outreach_p.set_defaults(func=_generate_outreach)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
