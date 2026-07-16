# Fleek Vintage Lead Engine

Turns a raw Google Maps scrape of clothing shops in any city into a
ranked, geographically-clustered BDR visit list: which listings are
genuine vintage clothing retailers, which tier they belong in, and
which ones sit close enough together to visit on foot in one trip.

## What it does, and why the qualification logic looks like this

A Google Maps scrape of "vintage" or "clothing" shops is mostly noise.
In the Manchester case-study scrape (`data/part1_manchester_scrape.csv`,
121 rows), roughly 70% is not a vintage clothing retailer at all:
antique shops, charity shops, record shops, furniture shops, cafes -
plus deliberate **name-traps** like "Vintage Wines & Spirits" (a wine
shop) and "The Vintage Tea Rooms" (a cafe), where the word "vintage" in
the name has nothing to do with clothing.

A naive keyword filter on "vintage" fails immediately on these. So
`qualify.py` never trusts one signal alone - it combines **category +
review text + business name**, in a fixed priority order:

1. **Charity-linked names** (Oxfam, British Heart Foundation, Sue
   Ryder, Salvation Army, or "charity" in the name) are checked first,
   before category. They're disqualified unless the review shows
   overwhelming, *named-brand* commercial evidence - a bare "vintage"
   mention doesn't clear this bar. See the enrichment methodology
   below for a real example of this firing on a genuine, currently-
   trading shop.
2. **Hard-disqualify categories** (Charity Shop, Book Store, Record
   Store, Antique Store, Pawn Shop, Wine Store, Furniture Store, Home
   Goods Store, Cafe/Coffee Shop, Costume/Fancy Dress, Tattoo Studio,
   Video Game Store, etc.) are unconditional. A stray positive word in
   the review can never resurrect one of these - that's exactly the
   name-trap the case study is built to catch.
3. **Clothing-adjacent categories** (Boutique, Second Hand Shop,
   Thrift Store, Vintage Clothing Store, Used Clothing Store, Clothing
   Store, Retro Clothing Shop) are ambiguous on their own - some
   genuine vintage shops sit under a generic "Clothing Store" or
   "Boutique", and some junk shops do too. These need review-text
   confirmation: a positive signal (vintage, retro, Y2K, denim, named
   brands like Levi's/Carhartt/Nike/Adidas, streetwear, band tees,
   football shirts, sportswear, etc.) qualifies it; a generic review
   with no clothing-specific signal is **insufficient evidence and
   disqualifies** - it is not a free pass just because the category
   looked plausible.
4. Any other category falls back to the same positive/negative review
   check.

Disqualified listings are never deleted - every row keeps its
`qualification_reason` and stays visible on the "Ranked Lead List"
sheet (filterable, not hidden), for auditability.

## Installation

```bash
pip install -e .
```

Requires Python 3.9+. Dependencies: pandas, numpy, scipy, openpyxl
(pyarrow is optional, only used if you want Parquet output elsewhere).

## Running it on a new scrape

```bash
vintage-lead-engine run \
  --input data/part1_manchester_scrape.csv \
  --output output/manchester_results.xlsx \
  --real-shortlist data/real_manchester_shortlist.csv
```

For any other city or a nationwide scrape, nothing changes - point
`--input`/`--output` at the new file and drop `--real-shortlist` (that
flag only makes sense for the Manchester worked example, see below):

```bash
vintage-lead-engine run --input leeds_scrape.csv --output output/leeds_results.xlsx
```

The pipeline makes no assumptions beyond the standard Maps-scrape
schema: `place_name, maps_category, full_address, lat, lng, rating,
review_count, top_review, website, phone, price_level`. There is no
hardcoded row lookup and no city-specific logic anywhere in
`src/vintage_lead_engine/`.

Other flags:

- `--cluster-km` - walking-distance clustering threshold in km
  (default `0.6`, roughly a 15-minute walk).
- `--max-styled-rows` - cap on styled Excel rows before falling back to
  a full CSV + bounded top slice (default `2000`, see "Output at
  scale" below).

## The Tier Key

- **Tier 1** - meets ANY ONE of: 2+ locations, 250+ Google reviews,
  5,000+ Instagram followers, or Strong Brand Fit **AND** active
  ecommerce presence.
- **Tier 2** - doesn't clear Tier 1, but meets ANY ONE of: 50-249
  Google reviews, 500-4,999 Instagram followers, active
  ecommerce/marketplace presence, Medium Brand Fit, or Medium
  Inventory Scale.
- **Tier 3** - a genuine vintage clothing retailer that clears neither
  Tier 1 nor Tier 2.
- **Disqualified** - not a genuine vintage clothing retailer (see
  qualification above).

Only whichever fields are actually available get scored. A raw Maps
scrape only ever supplies `review_count` - Locations, Instagram, Brand
Fit, and Ecommerce all need real enrichment. Every tier computed
without that enrichment says so explicitly in its `tier_reasoning`
(`"[scrape-only: ...]"`), rather than silently implying it's a complete
picture.

**Brand Fit is scored on named brands only**: 5+ named brands
mentioned = Strong, 2-4 = Medium, 0-1 = Weak. Generic language like
"designer pieces" or "quiet luxury" without naming actual brands does
**not** count as Strong - see the real-shop demo below for why this
matters in practice, not just in theory.

## Geographic clustering

`cluster.py` groups qualified shops within `--cluster-km` (default
0.6km, ~15 minutes on foot) of each other using **complete linkage**:
every member of a cluster must be genuinely within that distance of
*every other* member, not just connected through a chain of
neighbours (single-linkage chaining). A cluster's diameter is bounded
by the threshold - a BDR working through "Cluster 3" should never find
the last shop on the list is a kilometre from the first.

It scales to a nationwide scrape (tens of thousands of rows) without
building an O(n²) distance matrix: points are binned into a spatial
grid (cell size = the threshold), connected components of occupied
grid cells are found, and exact complete-linkage clustering runs once
per connected component - so cost scales with local density (a city,
a town), not the size of the whole scrape. This produces **identical**
output to a brute-force all-pairs computation (verified in
`tests/test_cluster.py`), not just similarly-shaped clusters - an
earlier version that clustered each grid cell independently silently
fragmented genuine clusters at cell boundaries, which is exactly what
that test guards against.

Output columns: `cluster_id`, `cluster_size`, and (in the "Cluster
Analysis" sheet) Tier 1/2/3 counts per cluster plus the list of shops
in it.

## Output workbook

Running `vintage-lead-engine run` produces a workbook with:

1. **Enriched Data** - every original scrape field + all enrichment
   columns + Tier classification, for every row, qualified and
   disqualified alike.
2. **Ranked Lead List** - sorted Tier 1 → Tier 2 → Tier 3 →
   Disqualified, with auto-filter enabled so disqualified rows stay
   visible and filterable rather than hidden or deleted.
3. **Cluster Analysis** - one row per cluster: size, Tier 1/2/3 counts,
   and which named shops are in it.
4. **Real Shop Demo (Manchester)** and **Real Shop Demo - Clusters** -
   only present when `--real-shortlist` is passed; the same
   Enriched-Data-style and Cluster-Analysis-style views, computed for
   the real shortlist instead - see below.

Headers are bold with frozen panes, auto-filter is enabled on every
sheet, and long free-text columns (`qualification_reason`,
`tier_reasoning`, `top_review`, `research_notes`) wrap instead of being
squeezed onto one line.

### Output at scale

A fully-styled Excel sheet with tens of thousands of rows is
impractical: slow to build and unusable to browse. If a scrape produces
more rows than `--max-styled-rows` (default 2000), the **complete**
result is written to a `_full.csv` file next to the workbook, and the
styled Excel sheets are capped to a bounded top slice (Tier 1 + Tier 2
rows first, then Tier 3, up to the cap) rather than trying to force
everything into one file.

## The real-shop enrichment demo - and why it's kept separate

`data/part1_manchester_scrape.csv` is **dummy data with placeholder
business names** (`Retrograde Wardrobe`, `Heirloom Closet`, etc.) -
deliberately messy, trap-laden, and fictional, so the qualification
logic can be proven against it without any risk of real-world
inaccuracy. You cannot look up a real Instagram follower count or
ecommerce presence for a business that doesn't exist, so the dummy
scrape is run through the pipeline **exactly as provided**, unmodified,
to prove the logic holds up (that's Sheets 1-3 of the output).

Separately, `data/real_manchester_shortlist.csv` is a shortlist of
**11 real, currently-trading Manchester vintage clothing shops**,
researched live (not fabricated, not swapped into the dummy dataset):
Pop Boutique, Blue Rinse, Bags of Flavour, Stare Society, Oxfam
Originals, Cow Vintage, Beg Steal & Borrow, American Graffiti, Retro
Rehab, Bionic Seven, and SYLK. For each shop, address, `lat`/`lng`
(geocoded from the shop's real postcode via postcodes.io, never
estimated from the city centre), location count, Google review count
(`google_review_count` - looked up from each shop's actual Google Maps
listing, not the same field as the dummy scrape's generic
`review_count`), phone number, Instagram handle + follower count,
website/ecommerce presence, named brand fit, and independent-ownership
status were researched from public sources. **Where a fact couldn't be
confirmed, the field says "Not confirmed" rather than a guessed,
plausible-looking number** - see `research_notes` in the CSV for the
reasoning behind every field on every row. Note this shortlist
deliberately does **not** have `rating` or `inventory_scale` columns -
neither was ever part of the requested enrichment fields or the Tier
Key for this file.

Running the exact same `qualify.py`/`cluster.py`/`tier.py` logic
against this real shortlist (via `--real-shortlist`) computes its
`qualifies`, `tier`, and `cluster_id` columns directly in the CSV, and
shows what the framework produces once genuine enrichment data exists -
a worked example, kept in its own clearly-labelled sheets (including a
"Real Shop Demo - Clusters" breakdown mirroring the main Cluster
Analysis sheet), never blended into the dummy-scrape results. A few
results are worth calling out because they demonstrate the logic
actually working on real-world data, not just the synthetic test
cases:

- **Oxfam Originals** is a real Oxfam-run vintage/designer concept
  store on Oldham Street. Its name triggers the same charity-name
  override check as a dummy "Oxfam"/"charity" row. The sourced
  description of its stock ("hand-selected vintage and designer
  clothing") uses only generic "designer" language, not a named brand
  or a literal "curated vintage"/"designer vintage" phrase, so it does
  **not** clear the strong-evidence override - and is disqualified,
  exactly like the dummy-data charity shops.
- **American Graffiti** was originally recorded as a single Afflecks
  stall. Re-verification found it actually trades from **two** current
  locations (the original 1982 Afflecks stall and a Hilton Street
  flagship open since 2005), which clears Tier 1 on locations alone -
  a real example of enrichment data changing a result once it's
  properly checked, not assumed from the first source found.
- **Bionic Seven** has a genuinely **Strong** Brand Fit (five named
  brands confirmed in sourced coverage: Barbour, Berghaus, Rab,
  Adidas, Levi's) - it also separately clears Tier 1 outright on a
  confirmed 9,488 Instagram followers, showing the Tier Key's "ANY ONE
  of" criteria are genuinely independent: a shop can qualify for Tier 1
  on Instagram reach alone even before Brand Fit and ecommerce are
  fully resolved.
- **SYLK**'s real address (39 Devonshire Street North, Ardwick) is
  about 1.8km from the Northern Quarter, and its own Instagram
  following (24,000) is what pushes it into Tier 1 - not proximity to
  the other shops. It correctly lands in its own single-shop cluster
  rather than being pulled into the Northern Quarter cluster, and
  Stare Society (Chinatown) does the same for a subtler reason: it's
  within 0.6km of *some* Northern Quarter shops but not all of them, so
  true complete linkage keeps it separate rather than chaining it in
  through its nearest neighbours.

Phone numbers in this file were cross-checked against at least one
independent source before being recorded, after an initial pass turned
up two concrete traps worth knowing about: one aggregator returned a
Leeds (0113) area-code number for Blue Rinse's Manchester store (Blue
Rinse operates in both cities, and the aggregator had evidently
cross-referenced the wrong location); and the only phone number
findable for two independent traders inside Afflecks Palace (Beg Steal
& Borrow, American Graffiti) was the shopping centre's own shared
building line, not either trader's own number - using it would have
misattributed the building's contact details to a specific stall.
Both traps are recorded in `research_notes` on the relevant rows rather
than silently corrected.

`research_notes` on the Retro Rehab row also documents a real instance
of a naming collision worth knowing about generally: a Retro Rehab
Instagram search surfaces an account with ~5,900 followers that
actually belongs to an unrelated mid-century *furniture* restoration
business, not this clothing shop. That number is deliberately **not**
attributed to Retro Rehab in the CSV - never trust a name/handle match
without checking it's actually the same business.

Independent ownership is tracked alongside every real-shop Tier result
(`independent_ownership` column) but is not part of the Tier Key
itself - it's the single factor that most changes whether a Tier 1
result is actually a viable wholesale prospect, since a charity-run or
centrally-buying chain may not need wholesale stock at all.

## Part 2 - CRM Cleaning & Outreach

Part 2 is self-contained: it works only on `data/part2_leads_and_customers.csv`
(an unmodified export of the `Part2_leads_and_customers` worksheet, 206
rows of leads and customers across every pipeline stage) and never
touches Part 1's Manchester scrape data or engine. It runs in two
stages: **CRM cleaning** (`crm_cleaning.py`) turns the raw export into
an analysis-ready database, then **outreach recommendations**
(`outreach.py` + `outreach_content.py`) generate a suggested message
(or a documented reason not to send one) for every cleaned, qualified
lead.

### Running it

```bash
vintage-lead-engine clean-crm --input data/part2_leads_and_customers.csv --output output/crm_cleaned.xlsx
vintage-lead-engine generate-outreach --input data/part2_leads_and_customers.csv --output output/crm_with_outreach.xlsx
```

`clean-crm` runs the cleaning rules alone. `generate-outreach` runs
cleaning and adds the five outreach columns (`SUGGESTED_MESSAGE`,
`MESSAGE_LOGIC`, `RECOMMENDED_FOLLOW_UP_DATE`, `OUTREACH_TYPE`,
`PERSONALISATION_ANGLE`) onto the same Cleaned Dataset sheet. Both
accept `--anchor-date YYYY-MM-DD` (a reproducible "today" for date
parsing and Last-Contacted timing - omit it and it defaults to the
real current date) and `--remove-non-uk` (see Rule 5 below).

### CRM cleaning: what it does and the two deliberate deviations from the literal brief

`crm_cleaning.py` is restructured from a validated reference
implementation built and checked against a real cleaning run on this
exact dataset - every rule's logic (the dedup guard, the stage maps,
`classify_store_type`, `flag_non_uk`, `parse_date_flex`, the
contactability scoring) is preserved from that reference, not
re-derived. Two places deliberately deviate from the brief's literal
instructions, because that's what the real client wanted:

- **Rule 5 (non-UK leads)**: the brief says remove non-UK leads
  entirely; this pipeline **flags them instead** (`--remove-non-uk`
  switches to the literal behaviour - it's a one-line toggle, not a
  rebuild). Flagging retains visibility into international leads
  rather than silently losing that data. Separately, rows with **no**
  location data at all (no address, phone, or website - typically
  online marketplace sellers) get a distinct `Unverified Location`
  flag rather than being assumed UK or flagged non-UK - country is
  never guessed from a name or product category.
- **Rule 9.5 (category/name qualification)**: not in the original Part
  2 brief at all. Added for consistency with Part 1 - a charity shop,
  record store, or antique store showing up as a "lead" here is the
  same category miss as in the Manchester scrape, just surfacing in
  different data. Reuses Part 1's qualification philosophy (hard-
  disqualify categories, the charity-name override with a
  strong-evidence bar) but is not a call into `qualify.py`: this leads
  list's qualifying categories (`Vintage clothing store`, `Thrift
  store`, etc.) already read as clothing-relevant by name, so - unlike
  Part 1's raw Maps scrape - no review-text confirmation gate is
  needed for them. Disqualified leads are never deleted; they stay
  visible on their own sheet with a reason, same as Part 1.

### The contactability_score contradiction

The brief's own scoring table is internally inconsistent: "2 = Missing
three" and "1 = Only one contact method" both describe having exactly
1 of 4 contact methods (email/phone/website/Instagram), but assign
different scores. Resolved by trusting the more structured "missing N"
reading - a clean monotonic scale (0 methods=0, 1=2, 2=3, 3=4, 4=5) -
since 5 of the 6 rows in the brief's table agree on that reading. This
is documented in the generated Cleaning Log sheet, not silently picked.

### Two real bugs found running this against the real export

Building this against real data (not just the brief's abstract rules)
surfaced two genuine defects, both fixed and covered by regression
tests:

1. **Dates silently landing in the future.** `parse_date_flex()` used
   `dayfirst=True` unconditionally. dateutil applies day-before-month
   disambiguation to the first two ambiguous numeric fields it finds,
   which is wrong once the year already comes first - "2026/04/10" was
   being read as 4 October instead of 10 April, corrupting
   `last_contact_date` and, downstream, every Last-Contacted timing
   decision in Part B. Fixed by only using `dayfirst=True` when the
   string does not already start with a 4-digit year.
2. **A "last purchase" date that was actually in the future.** Rule 6's
   bare-date year-inference has a 60-day grace window (a bare date
   within 60 days of the anchor is assumed to be near-present, not
   rolled back a year) - reasonable for `last_contact_date`, which can
   legitimately reference a near-term scheduled contact. But a
   *purchase* can never be in the future at all, so a bare "18 Aug"
   `last_purchase_date` landing 33 days after the anchor (inside that
   60-day grace window) was left as a nonsensical future purchase date.
   Fixed with a `must_not_be_future` flag on `parse_date_flex()` that
   removes the grace window entirely, applied only to
   `last_purchase_date`.

Neither fix changes the pinned qualified/duplicate-group counts below
- date parsing doesn't affect qualification or which businesses get
merged, only the merged group's date value and duplicate tie-breaking.

### Deduplication: the guard that matters most

`find_duplicate_groups()` matches on store name, website, Instagram
handle, phone, address, and lat/lng - but never merges on a matching
field alone. A real run of this exact dataset found genuinely
unrelated businesses coincidentally sharing an identical Instagram
handle or address template across different countries; every candidate
match (strong key or weak) is checked against a city/country
contradiction first, and contradicting pairs are flagged for manual
review (`Possible Duplicate - Unverified`, shaded yellow in the
Cleaned Dataset sheet) instead of merged or silently dropped. Verified
directly in `tests/test_crm_cleaning.py` and against the real export,
where all 7 flagged pairs are genuine cross-city/cross-country
coincidences, not real duplicates.

### Outreach recommendations - and what "generated directly in this session" means

Part B's five columns were authored directly in the Claude Code
session that built this pipeline, for the specific batch of qualified
leads in `data/part2_leads_and_customers.csv` - **not** via a
standalone script calling the Anthropic API. That authored content
lives in `outreach_content.py` as hand-written personalisation angles
for every distinct product-focus phrase actually observed in the
cleaned `notes` field, hand-written clauses for every distinct
objection phrase, and stage-appropriate templates (Cold / Inbound /
Customer Check-In / Churned-Win-Back / Re-Engagement), combined per
lead using only that lead's own real data - never templated boilerplate
praise, never a fabricated detail. French/German/Dutch translations are
included for the France/Germany/Netherlands leads in this batch.

This means `generate-outreach` **is** re-runnable - it's real, tested
code, not a one-off script - but it is scoped to this batch's
vocabulary. Pointed at a future export with notes phrases it doesn't
recognise, it degrades honestly: a lead with no usable personalisation
signal gets a blank `SUGGESTED_MESSAGE` and a `MESSAGE_LOGIC` explaining
why, never a generic or invented message. If a genuinely general-purpose
version (one that calls an LLM per lead, reading its API key from a
project-local `.env` file) is wanted later, that's a different,
larger piece of work - it has not been built here.

Eligibility is decided before any drafting: `In Conversation`, `Not
Interested`, `Closed Lost`, and `Do Not Contact` stages never get a
message (In Conversation specifically never invents prior-conversation
content, since there's no visibility into what's actually been said).
A lead contacted within 7 days gets `OUTREACH_TYPE=Deferred` and a
follow-up date exactly 10 days after `last_contact_date`, rather than a
second message. The "500 other retailers" test - reject any line that
would read identically sent to any business - is a real function
(`outreach.passes_specificity_test`), not just a description, and acts
as a safety net over the authored content.

### Part 2 tests and regression numbers

- `test_crm_cleaning.py` - the dedup location-conflict guard directly,
  stage-mapping granularity (Visit Booked vs Meeting Booked, Trial
  Pending vs Trialing, Interested/Warm Lead alignment, Inbound staying
  separate), store type/confidence rules, Rule 5's flag-vs-remove and
  Unverified-Location distinction, date parsing (including the exact
  string that previously mis-parsed), category normalisation, the Rule
  9.5 extension, and the contactability_score resolution.
- `test_outreach_eligibility.py` - all four excluded stages, the exact
  3-days-ago -> Deferred + 10-day follow-up case, Engaged/Opportunity
  leads never being labelled Cold, and the specificity test on both a
  generic and a genuinely specific line.
- `test_regression_crm.py` - the golden-file test: **188 unique
  business groups** and **164 qualified leads** on the real export,
  after Rule 9.5. If either number changes, the test fails loudly - a
  deliberate, reviewed change to dedup or qualification logic, not a
  silent regression.

## Part 1 tests and the regression golden numbers

```bash
pytest
```

- `test_qualify.py` - known trap cases (category-based hard
  disqualification even with a vintage-sounding name/review, a
  Boutique confirmed by a genuine review, both sides of the
  charity-name override).
- `test_cluster.py` - complete-linkage semantics directly (a chaining
  case that must NOT merge), plus an exact match against a brute-force
  O(n²) computation on synthetic data.
- `test_tier.py` - all four Tier 1/2 boundary conditions, just above
  and below each threshold.
- `test_regression_manchester.py` - runs the full pipeline against
  `data/part1_manchester_scrape.csv` and asserts the known result:
  **34 of 121 rows qualify**. If this number ever changes, the test
  fails loudly - that means the qualification logic changed, which
  needs to be a deliberate, reviewed decision, not a silent
  regression. Update `EXPECTED_QUALIFIED_COUNT` in that file only when
  you've consciously decided to change the qualification rules.

CI (`.github/workflows/tests.yml`) runs the full suite on every push
and pull request against Python 3.9 and 3.11.

## Repository layout

```
src/vintage_lead_engine/
    qualify.py           # Part 1: qualification (category + review + name)
    cluster.py           # Part 1: spatially-partitioned complete-linkage clustering
    tier.py              # Part 1: Tier 1/2/3 assignment
    enrichment.py        # Part 1: real-shop enrichment data model + loader
    crm_cleaning.py       # Part 2: CRM cleaning rules (dedup, stages, store type, etc.)
    outreach.py          # Part 2: outreach eligibility + timing rules (deterministic)
    outreach_content.py  # Part 2: authored message content (see Part 2 section above)
    excel_output.py       # workbook builders for both Part 1 and Part 2
    cli.py                # `run` / `clean-crm` / `generate-outreach`
data/
    part1_manchester_scrape.csv       # unmodified dummy scrape (121 rows)
    real_manchester_shortlist.csv     # 11 real, researched Manchester shops
    part2_leads_and_customers.csv     # unmodified leads/customers export (206 rows)
tests/                # pytest suite, see above
output/               # generated workbooks land here (gitignored)
```
