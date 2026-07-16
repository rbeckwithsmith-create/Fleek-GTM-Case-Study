"""
Vintage-clothing-shop qualification (vectorised).

Designed to run on ANY Google-Maps-style scrape with at least these
columns: place_name, maps_category, top_review. Fully vectorised pandas
string ops - the regex engine runs once per pattern over the whole
column, not once per row - so this scales to a nationwide scrape
without an iterrows() loop.

Why category alone is never trusted: Google Maps categories are noisy
("Boutique", "Second Hand Shop", "Clothing Store" all cover both
genuine vintage clothing retailers and completely unrelated shops), and
business names contain "vintage"/"retro" name-traps (e.g. "Vintage
Wines", "Vintage Tea Rooms") that have nothing to do with clothing. So
qualification combines category + review text + business name, with a
priority order: charity-linked names are checked first (since a
charity-branded shop needs overwhelming evidence to override, even if
its category looks like a normal vintage store), then hard-disqualify
categories (unconditional - a stray positive word in the review must
never resurrect one of these), then clothing-adjacent categories
(ambiguous - need review-text confirmation), then a fallback for any
other category.
"""
import re
import pandas as pd

HARD_DISQUALIFY_CATEGORY_KEYWORDS = [
    "charity", "book", "record", "antique", "pawn", "wine",
    "furniture", "home goods", "homeware", "home decor", "cafe", "coffee",
    "costume", "fancy dress", "tattoo", "barber", "video game", "electricals",
]

CLOTHING_ADJACENT_CATEGORY_KEYWORDS = [
    "vintage clothing", "vintage store", "used clothing", "clothing store",
    "retro clothing", "second hand", "secondhand", "thrift", "boutique",
    "consignment", "resale",
]

POSITIVE_REVIEW_PATTERN = (
    r"\b(?:vintage|retro|y2k|denim|levi'?s|carhartt|dickies|ralph lauren|"
    r"nike|adidas|streetwear|band tees?|reworked|archive designer|"
    r"curated vintage|grunge|football shirts?|sportswear|90s|80s|70s|"
    r"secondhand clothing|second-hand clothing|designer vintage)\b"
)

NEGATIVE_OVERRIDE_PATTERN = (
    r"\b(?:bric-a-brac|antiques?|curios|homeware|home decor|furniture|"
    r"restoration|no clothes|books?|bookshop|vinyl|records?|fancy dress|"
    r"costume hire|tattoo|barber|old-school cuts|coffee|cake|wine|"
    r"phone|consoles?|china|collectables?)\b"
)

CHARITY_NAME_PATTERN = (
    r"\b(?:charity|oxfam|british heart foundation|sue ryder|salvation army)\b"
)

STRONG_POSITIVE_PATTERN = (
    r"\b(?:levi'?s|carhartt|dickies|ralph lauren|nike|adidas|denim|"
    r"streetwear|band tees?|reworked|archive designer|curated vintage|"
    r"football shirts?|designer vintage|secondhand clothing|second-hand clothing)\b"
)

_HARD_DQ_RE = "|".join(re.escape(k) for k in HARD_DISQUALIFY_CATEGORY_KEYWORDS)
_ADJACENT_RE = "|".join(re.escape(k) for k in CLOTHING_ADJACENT_CATEGORY_KEYWORDS)


def qualify_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `qualifies` (bool) and `qualification_reason` (str) columns.

    Priority-ordered rules, vectorised with pandas .str.contains
    (compiled once per pattern) instead of a per-row Python loop - on
    30k rows this is the difference between ~1s and ~30s+."""
    df = df.copy()
    name = df["place_name"].fillna("").astype(str)
    category = df["maps_category"].fillna("").astype(str)
    review = df["top_review"].fillna("").astype(str)
    cat_lower = category.str.lower()

    has_positive = review.str.contains(POSITIVE_REVIEW_PATTERN, case=False, regex=True, na=False)
    has_negative = review.str.contains(NEGATIVE_OVERRIDE_PATTERN, case=False, regex=True, na=False)
    has_strong_positive = review.str.contains(STRONG_POSITIVE_PATTERN, case=False, regex=True, na=False)
    is_charity_name = name.str.contains(CHARITY_NAME_PATTERN, case=False, regex=True, na=False)
    is_hard_dq_cat = cat_lower.str.contains(_HARD_DQ_RE, regex=True, na=False)
    is_adjacent_cat = cat_lower.str.contains(_ADJACENT_RE, regex=True, na=False)

    qualifies = pd.Series(False, index=df.index)
    reason = pd.Series("", index=df.index)

    # Priority 1: charity name
    m = is_charity_name
    qualifies = qualifies.mask(m & has_strong_positive, True)
    reason = reason.mask(m & has_strong_positive,
        "Charity-linked name, but review gives strong, specific commercial vintage-clothing signal - manually verify before disqualifying.")
    reason = reason.mask(m & ~has_strong_positive,
        "Name signals a charity operation; no overwhelming evidence of commercial vintage retail in the review.")

    # Priority 2: hard-disqualify category (unconditional, no charity name)
    m2 = ~m & is_hard_dq_cat
    reason = reason.mask(m2, "Category '" + category + "' is on the automatic-disqualify list - not a clothing retail category.")

    # Priority 3: clothing-adjacent category
    m3 = ~m & ~is_hard_dq_cat & is_adjacent_cat
    m3_neg = m3 & has_negative & ~has_positive
    m3_pos = m3 & has_positive & ~m3_neg
    m3_none = m3 & ~m3_neg & ~m3_pos
    qualifies = qualifies.mask(m3_pos, True)
    reason = reason.mask(m3_neg, "Category '" + category + "' is generic, but review text ('" + review + "') signals non-clothing stock.")
    reason = reason.mask(m3_pos, "Category '" + category + "' plus review text ('" + review + "') confirms genuine vintage clothing stock.")
    reason = reason.mask(m3_none, "Category '" + category + "' is generic and the review ('" + review + "') gives no clothing-specific signal - insufficient evidence, not a keyword-safe pass.")

    # Priority 4: fallback for any category not in either list
    m4 = ~m & ~is_hard_dq_cat & ~is_adjacent_cat
    m4_pos = m4 & has_positive & ~has_negative
    m4_neg = m4 & ~m4_pos
    qualifies = qualifies.mask(m4_pos, True)
    reason = reason.mask(m4_pos, "Category '" + category + "' not in a known list, but review text confirms vintage clothing.")
    reason = reason.mask(m4_neg, "Category '" + category + "' not recognised as clothing retail and no positive review signal.")

    df["qualifies"] = qualifies
    df["qualification_reason"] = reason
    return df
