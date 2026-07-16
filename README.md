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
4. **Real Shop Demo (Manchester)** - only present when
   `--real-shortlist` is passed; see below.

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
Rehab, Bionic Seven, and SYLK. For each shop, address, location count,
Instagram handle + follower count, website/ecommerce presence, named
brand fit, and independent-ownership status were researched from
public sources. **Where a fact couldn't be confirmed, the field says
"Not confirmed" rather than a guessed, plausible-looking number** - see
`research_notes` in the CSV for the reasoning behind every field on
every row.

Running the same `qualify.py`/`tier.py` logic against this real
shortlist (via `--real-shortlist`) shows what the framework produces
once genuine enrichment data exists - a worked example, kept in its
own clearly-labelled sheet, never blended into the dummy-scrape
results. Two results are worth calling out because they demonstrate
the logic actually working on real-world data, not just the synthetic
test cases:

- **Oxfam Originals** is a real Oxfam-run vintage/designer concept
  store on Oldham Street. Its name triggers the same charity-name
  override check as a dummy "Oxfam"/"charity" row. The sourced
  description of its stock ("hand-selected vintage and designer
  clothing") uses only generic "designer" language, not a named brand
  or a literal "curated vintage"/"designer vintage" phrase, so it does
  **not** clear the strong-evidence override - and is disqualified,
  exactly like the dummy-data charity shops.
- **Bionic Seven** has a genuinely **Strong** Brand Fit (five named
  brands confirmed in sourced coverage: Barbour, Berghaus, Rab,
  Adidas, Levi's) but lands in **Tier 3** anyway, because Tier 1's
  "Strong Brand Fit" criterion also requires confirmed active
  ecommerce, which research didn't turn up for this shop. It's a real
  example of why Brand Fit alone doesn't guarantee a high tier - and a
  good candidate for a BDR to call directly and confirm ecommerce
  before re-scoring, rather than the tool silently assuming it.

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

## Tests and the regression golden numbers

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
    qualify.py       # qualification (category + review + name)
    cluster.py       # spatially-partitioned complete-linkage clustering
    tier.py          # Tier 1/2/3 assignment
    enrichment.py     # real-shop enrichment data model + loader
    excel_output.py  # 3(+1)-sheet workbook builder
    cli.py           # `vintage-lead-engine run ...`
data/
    part1_manchester_scrape.csv       # unmodified dummy scrape (121 rows)
    real_manchester_shortlist.csv     # 11 real, researched Manchester shops
tests/                # pytest suite, see above
output/               # generated workbooks land here (gitignored)
```
