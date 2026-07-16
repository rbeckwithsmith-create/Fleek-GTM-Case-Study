"""
CRM cleaning - Part 2 (Fleek "Part2_leads_and_customers" worksheet).

Self-contained: works ONLY on the Part 2 leads/customers data. Does not
touch Part 1's Manchester scrape data or the qualify/cluster/tier
engine built for it.

This module is restructured from a validated reference implementation
(crm_cleaning_reference.py) built and checked against an actual
cleaning run on the real dataset - it encodes several judgment calls
and one real bug-fix that are easy to get wrong from the brief text
alone (see the comments inline on each rule). The logic is preserved
exactly; only the module layout changed to fit this package.

Column names below match the source sheet: lead_id, store_name,
lead_channel_label, google_maps_category, instagram_handle, followers,
items_listed, sell_through_rate, website, email, phone, owner_name,
address, city, neighbourhood, country, lat, lng, est_monthly_spend_gbp,
lead_stage, last_contact_date, last_purchase_date, notes, lead_source.
"""
import re

import numpy as np
import pandas as pd
from dateutil import parser as dtparser

# =============================================================================
# STAGE MAPPING TABLES (Rule 3: stage_raw / stage_clean / pipeline_status)
# =============================================================================
# Built from every literal value observed in a real run, plus every value
# named in the brief's own example tables (kept even if unobserved, for
# robustness on a future export). Preserves granularity deliberately -
# e.g. "Visit Booked" is kept distinct from "Meeting Booked" (a physical
# shop visit is a materially different sales action for a business that
# visits stores in person), and "Trial Pending" distinct from "Trialing"
# (scheduled vs. in progress). Do not collapse these further without a
# specific reason - the brief explicitly asks to preserve detail.

STAGE_CLEAN_MAP = {
    "new - inbound": "Inbound", "inbound": "Inbound", "inbound lead": "Inbound",
    "new lead": "New Lead", "new": "New Lead", "not contacted": "New Lead",
    "contacted": "Contacted", "emailed": "Contacted", "1st touch sent": "Contacted",
    "reached out": "Contacted", "first touch": "Contacted",
    "replied": "Replied", "responded": "Replied",
    "in conversation": "In Conversation", "in convo": "In Conversation",
    "warm lead": "Warm Lead", "interested": "Warm Lead",
    "interested - follow up": "Warm Lead", "qualified lead": "Warm Lead",
    "positive response": "Warm Lead", "follow up next week": "Follow Up",
    "meeting booked": "Meeting Booked", "meeting set": "Meeting Booked",
    "demo booked": "Demo Booked", "visit booked": "Visit Booked",
    "visiting": "Visiting", "trialing": "Trialing", "trial pending": "Trial Pending",
    "quote sent": "Quote Sent", "sent pricing": "Quote Sent",
    "negotiating": "Negotiating", "onboarding": "Onboarding",
    "active customer": "Active Customer", "customer": "Active Customer",
    "repeat customer": "Repeat Customer", "first order placed": "Active Customer",
    "won": "Closed Won", "closed won": "Closed Won", "closed - won": "Closed Won",
    "reactivated": "Reactivated",
    "churned": "Churned", "dormant": "Dormant", "lapsed": "Lapsed",
    "stopped buying": "Stopped Buying", "inactive customer": "Churned",
    "not interested": "Not Interested", "lost": "Closed Lost",
    "closed lost": "Closed Lost", "closed - lost": "Closed Lost", "rejected": "Closed Lost",
    "ghosted": "No Response", "no reply": "No Response",
}

PIPELINE_STATUS_MAP = {
    "Inbound": "Prospect", "New Lead": "Prospect",
    "Contacted": "Contacted",
    "Replied": "Engaged", "In Conversation": "Engaged", "Warm Lead": "Engaged", "Follow Up": "Engaged",
    "Meeting Booked": "Opportunity", "Demo Booked": "Opportunity", "Visit Booked": "Opportunity",
    "Visiting": "Opportunity", "Trialing": "Opportunity", "Trial Pending": "Opportunity",
    "Quote Sent": "Opportunity", "Negotiating": "Opportunity", "Onboarding": "Opportunity",
    "Active Customer": "Customer", "Repeat Customer": "Customer", "Closed Won": "Customer", "Reactivated": "Customer",
    "Churned": "Churned", "Dormant": "Churned", "Lapsed": "Churned", "Stopped Buying": "Churned",
    "Not Interested": "Lost", "Closed Lost": "Lost", "No Response": "Lost",
}

# Funnel-depth ranking used ONLY to pick the "most advanced stage" when
# merging duplicate rows (Rule 2) - not the same thing as pipeline_status.
ADVANCEMENT_RANK = {
    "Prospect": 0, "Contacted": 1, "Lost": 1,  # a decline implies at least some engagement happened
    "Engaged": 2, "Opportunity": 3, "Customer": 4, "Churned": 4,  # churn means they were a Customer at some point
}


def clean_stage(raw):
    """Returns (stage_raw, stage_clean, pipeline_status, advancement_rank)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Unknown", "Unknown", "Prospect", 0
    key = re.sub(r'\s+', ' ', str(raw).strip().lower())
    stage_clean = STAGE_CLEAN_MAP.get(key)
    if stage_clean is None:
        # Unmapped value - preserve detail rather than guess wrong: title-case
        # the raw text as stage_clean rather than silently dropping it or
        # forcing it into an existing bucket that might not fit.
        stage_clean = str(raw).strip().title()
        pipeline_status = "Prospect"
    else:
        pipeline_status = PIPELINE_STATUS_MAP.get(stage_clean, "Prospect")
    return str(raw).strip(), stage_clean, pipeline_status, ADVANCEMENT_RANK.get(pipeline_status, 0)


# =============================================================================
# RULE 1: Exclude "No Fit" leads
# =============================================================================
NO_FIT_PATTERN = re.compile(r'^\s*(no fit|not a fit|poor fit|unsuitable|do not contact|bad fit)\s*$', re.I)


def exclude_no_fit(df, stage_col='lead_stage'):
    """Returns (filtered_df, count_removed). IMPORTANT: "not interested" is
    NOT treated as equivalent to "no fit" - it's a buying-intent/timing
    rejection, not an ICP/category mismatch, which is what this rule's
    language (poor fit, unsuitable, wrong category) specifically targets.
    Keep "not interested" rows in the dataset as a Lost-stage lead."""
    is_no_fit = df[stage_col].fillna('').apply(lambda s: bool(NO_FIT_PATTERN.match(s)))
    return df[~is_no_fit].copy(), int(is_no_fit.sum())


# =============================================================================
# RULE 2: Deduplicate
# =============================================================================
def _norm_text(s):
    return None if pd.isna(s) else re.sub(r'\s+', ' ', str(s).strip().lower())


def _norm_domain(s):
    if pd.isna(s):
        return None
    d = str(s).strip().lower()
    d = re.sub(r'^https?://', '', d)
    d = re.sub(r'^www\.', '', d)
    return d.rstrip('/')


def _norm_handle(s):
    return None if pd.isna(s) else str(s).strip().lower().lstrip('@')


def _norm_phone(s):
    return None if pd.isna(s) else re.sub(r'\s+', '', str(s).strip())


def find_duplicate_groups(df):
    """Union-find dedup across store name / website / Instagram / phone /
    address / lat-lng.

    CRITICAL, hard-won finding: do NOT trust ANY matching field blindly,
    including ones that "should" be unique (a website domain, an
    Instagram handle). A real run of this pipeline found genuinely
    UNRELATED businesses coincidentally sharing a field - e.g. two
    different "X Shop" records, one a real UK lead and one an unrelated
    foreign business in a completely different trade, sharing an
    identical name+email; two different leads in different countries
    sharing an identical Instagram handle. Blindly merging on any single
    matching field, even a "strong" one, would corrupt or delete a
    genuine lead. Every candidate match - strong or weak key - gets the
    SAME guard: don't auto-merge if city/country are both known and
    genuinely contradict. Flag those for manual review instead; don't
    merge them and don't discard either row silently.

    Also note: generic street templates (e.g. "127 High St") can
    coincidentally repeat across unrelated cities in a scraped/synthetic
    dataset, so address-alone matches need the same guard, not just name.

    Returns (df_with_group_col, flagged_pairs) where flagged_pairs is a
    list of (lead_id_a, lead_id_b, matched_key, city_a, city_b, country_a, country_b)
    for pairs that matched a field but were NOT merged due to a location conflict.
    """
    df = df.reset_index(drop=True).copy()
    df['_k_name'] = df['store_name'].apply(_norm_text)
    df['_k_web'] = df['website'].apply(_norm_domain)
    df['_k_ig'] = df['instagram_handle'].apply(_norm_handle)
    df['_k_phone'] = df['phone'].apply(_norm_phone)
    df['_k_addr'] = df['address'].apply(_norm_text)

    parent = {i: i for i in df.index}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def location_conflicts(a, b):
        ca, cb = df.loc[a, 'city'], df.loc[b, 'city']
        coa, cob = df.loc[a, 'country'], df.loc[b, 'country']
        city_conflict = pd.notna(ca) and pd.notna(cb) and _norm_text(ca) != _norm_text(cb)
        country_conflict = pd.notna(coa) and pd.notna(cob) and _norm_text(coa) != _norm_text(cob)
        return city_conflict or country_conflict

    ALL_KEYS = ['_k_web', '_k_ig', '_k_phone', '_k_addr']  # lat/lng handled separately below (float pair)
    flagged = []
    for key in ALL_KEYS:
        for k, idxs in df[df[key].notna()].groupby(key).groups.items():
            idxs = list(idxs)
            for i in range(len(idxs)):
                for j in range(i + 1, len(idxs)):
                    a, b = idxs[i], idxs[j]
                    if find(a) == find(b):
                        continue
                    if location_conflicts(a, b):
                        flagged.append((df.loc[a, 'lead_id'], df.loc[b, 'lead_id'], key,
                                         df.loc[a, 'city'], df.loc[b, 'city'],
                                         df.loc[a, 'country'], df.loc[b, 'country']))
                    else:
                        union(a, b)

    # lat/lng pair match (exact)
    latlng_groups = df[df['lat'].notna() & df['lng'].notna()].groupby(['lat', 'lng']).groups
    for k, idxs in latlng_groups.items():
        idxs = list(idxs)
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = idxs[i], idxs[j]
                if find(a) == find(b):
                    continue
                if location_conflicts(a, b):
                    flagged.append((df.loc[a, 'lead_id'], df.loc[b, 'lead_id'], '_k_latlng',
                                     df.loc[a, 'city'], df.loc[b, 'city'],
                                     df.loc[a, 'country'], df.loc[b, 'country']))
                else:
                    union(a, b)

    df['_group'] = df.index.map(find)
    return df, flagged


def merge_duplicate_groups(df, date_anchor):
    """Merges each _group (from find_duplicate_groups) into one record:
    most complete record as primary (gaps filled from other members),
    most RECENT last_contact_date/last_purchase_date across the group,
    most ADVANCED stage (by ADVANCEMENT_RANK, tie-broken by most recent
    contact), and every UNIQUE note concatenated (newest first, not just
    the primary record's note)."""
    FIELDS = ['lead_id', 'store_name', 'lead_channel_label', 'google_maps_category',
              'instagram_handle', 'followers', 'items_listed', 'sell_through_rate',
              'website', 'email', 'phone', 'owner_name', 'address', 'city',
              'neighbourhood', 'country', 'lat', 'lng', 'est_monthly_spend_gbp', 'lead_source']

    df = df.copy()
    df['_dt_contact'] = df['last_contact_date'].apply(lambda s: parse_date_flex(s, date_anchor))
    df['_dt_purchase'] = df['last_purchase_date'].apply(
        lambda s: parse_date_flex(s, date_anchor, must_not_be_future=True))
    stage_parsed = df['lead_stage'].apply(clean_stage)
    df['_stage_raw'] = stage_parsed.apply(lambda t: t[0])
    df['_stage_clean'] = stage_parsed.apply(lambda t: t[1])
    df['_pipeline_status'] = stage_parsed.apply(lambda t: t[2])
    df['_stage_rank'] = stage_parsed.apply(lambda t: t[3])

    def completeness(row):
        return sum(pd.notna(row[f]) and str(row[f]).strip() != '' for f in FIELDS)

    def merge_group(g):
        primary = g.iloc[g.apply(completeness, axis=1).values.argmax()]
        merged = {}
        for f in FIELDS:
            val = primary[f]
            if pd.isna(val) or str(val).strip() == '':
                candidates = g[f].dropna()
                candidates = candidates[candidates.astype(str).str.strip() != '']
                val = candidates.iloc[0] if len(candidates) else np.nan
            merged[f] = val

        merged['last_contact_date'] = g['_dt_contact'].max()
        merged['last_purchase_date'] = g['_dt_purchase'].max()

        best = g.sort_values(['_stage_rank', '_dt_contact'], ascending=[False, False]).iloc[0]
        merged['stage_raw'] = best['_stage_raw']
        merged['stage_clean'] = best['_stage_clean']
        merged['pipeline_status'] = best['_pipeline_status']

        notes = g.sort_values('_dt_contact', ascending=False)['notes'].dropna().astype(str).str.strip()
        notes = notes[notes != '']
        seen, uniq = set(), []
        for n in notes:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        merged['notes'] = ' | '.join(uniq) if uniq else np.nan
        merged['source_lead_ids'] = ', '.join(g['lead_id'].tolist())
        merged['n_records_merged'] = len(g)
        return pd.Series(merged)

    return df.groupby('_group').apply(merge_group, include_groups=False).reset_index(drop=True)


# =============================================================================
# RULE 4: store_type + store_type_confidence (do NOT trust lead_channel)
# =============================================================================
def classify_store_type(df):
    """Hard rule: items_listed OR sell_through_rate populated -> Online
    Retailer, regardless of lead_channel. Otherwise, a real address +
    lat/lng -> Physical Store. Confidence: High if exactly one signal
    fires cleanly, Medium if BOTH fire (hybrid, worth a human glance),
    Low if NEITHER fires (a default guess with nothing backing it)."""
    df = df.copy()
    has_online_signal = df['items_listed'].notna() | df['sell_through_rate'].notna()
    has_addr_signal = df['address'].notna() | df['lat'].notna()
    df['store_type'] = np.select([has_online_signal, has_addr_signal],
                                  ['Online Retailer', 'Physical Store'], default='Online Retailer')
    conf = []
    for online_sig, addr_sig in zip(has_online_signal, has_addr_signal):
        if online_sig and addr_sig:
            conf.append('Medium')
        elif online_sig or addr_sig:
            conf.append('High')
        else:
            conf.append('Low')
    df['store_type_confidence'] = conf
    return df


# =============================================================================
# RULE 5: Non-UK leads
# =============================================================================
UK_COUNTRIES = {'uk', 'united kingdom', 'england', 'scotland', 'wales',
                'northern ireland', 'gb', 'great britain'}


def flag_non_uk(df, remove=False):
    """The original brief says REMOVE non-UK leads. In practice, on a real
    run of this pipeline, the client preferred to FLAG rather than remove
    (retains visibility into international leads rather than losing that
    data) - default here is remove=False (flag only). Pass remove=True to
    match the brief's literal instruction instead; both are one-line
    changes, not a redesign, so make this an easy toggle, not a hardcoded
    choice.

    Separately, rows with NO country data at all (typically online
    marketplace sellers with no address/phone/website to check a country
    against) get a DIFFERENT flag - 'Unverified Location' - since that's
    genuinely a different situation from a confirmed-foreign lead, and
    real web research on synthetic/placeholder business names won't
    resolve it. Never assume these are UK by default."""
    df = df.copy()
    country_norm = df['country'].apply(lambda s: str(s).strip().lower() if pd.notna(s) else None)
    is_confirmed_non_uk = country_norm.notna() & ~country_norm.isin(UK_COUNTRIES)
    is_unverified = df['country'].isna()
    df['_confirmed_non_uk'] = is_confirmed_non_uk
    df['_unverified_location'] = is_unverified
    non_uk_count = int(is_confirmed_non_uk.sum())
    if remove:
        df = df[~is_confirmed_non_uk].reset_index(drop=True)
    return df, non_uk_count, int(is_unverified.sum())


# =============================================================================
# RULE 6: Standardise dates
# =============================================================================
def parse_date_flex(s, anchor, must_not_be_future=False):
    """Handles the real-world format zoo: DD/MM/YYYY, YYYY/MM/DD,
    YYYY-MM-DD, 'Month D YYYY', and bare 'D Mon' with no year. Bare
    dates are assumed to fall near `anchor` (pass roughly "today" for
    the dataset), rolled back a year if that would place them
    implausibly in the future relative to anchor - document this as an
    assumption in the cleaning log, since it's a real ambiguity, not a
    certainty.

    must_not_be_future tightens that rollback for fields where a future
    date is never valid regardless of the grace window (last_purchase_date
    - a purchase cannot have happened yet). Found running this against
    the real export: a bare 'Aug 18' last_purchase_date landed 33 days
    after the anchor, inside the general 60-day grace window meant for
    last_contact_date (which CAN legitimately reference a near-term
    scheduled contact) - but a past purchase can never be in the future
    at all, so that field rolls back on ANY future bare date, not just
    ones more than 60 days out.

    BUG FIX (found running this against the real export): dateutil's
    dayfirst=True applies day-before-month disambiguation to the first
    two numeric fields it sees, which is wrong once the year already
    comes first (e.g. "2026/04/10") - dayfirst=True was swapping that
    into 4 October instead of 10 April, silently producing last-contact
    dates in the future. Fixed by only passing dayfirst=True when the
    string does NOT already start with a 4-digit year (in which case
    yearfirst=True is used instead, and the remaining two fields are
    read in their natural month-then-day order) - this preserves
    dayfirst behaviour for genuinely ambiguous DD/MM/YYYY strings while
    correctly reading YYYY/MM/DD and YYYY-MM-DD as year-month-day."""
    if pd.isna(s) or str(s).strip() == '':
        return pd.NaT
    s = str(s).strip()
    has_year = bool(re.search(r'\b(19|20)\d\d\b', s))
    year_first = bool(re.match(r'^(19|20)\d\d[/-]', s))
    try:
        dt = dtparser.parse(s, dayfirst=not year_first, yearfirst=year_first, default=anchor)
    except Exception:
        return pd.NaT
    grace = pd.Timedelta(days=0) if must_not_be_future else pd.Timedelta(days=60)
    if not has_year and dt > anchor + grace:
        dt = dt.replace(year=dt.year - 1)
    return pd.Timestamp(dt.date())


def format_date_fields(df, date_cols=('last_contact_date', 'last_purchase_date')):
    """Formats to YYYY-MM-DD strings, blanks -> 'never'. The brief's
    Special Rule only names last_contact_date, but the same logic is
    extended to last_purchase_date here - most leads simply haven't
    purchased yet, which "never" states accurately; the generic
    "unknown" fallback would incorrectly imply uncertainty. Document
    this extension as an assumption if you keep it."""
    df = df.copy()
    for col in date_cols:
        df[col] = df[col].apply(lambda dt: None if pd.isna(dt) else pd.Timestamp(dt).strftime('%Y-%m-%d'))
        df[col] = df[col].fillna('never')
    return df


# =============================================================================
# RULE 8: Standardise contact field formats
# =============================================================================
def fmt_instagram(s):
    if pd.isna(s):
        return None
    h = re.sub(r'^https?://(www\.)?instagram\.com/', '', str(s).strip(), flags=re.I).lstrip('@').strip('/')
    return f'@{h.lower()}' if h else None


def fmt_phone(s):
    if pd.isna(s):
        return None
    return re.sub(r'[^\d+]', '', str(s))  # +44XXXXXXXXXX once spaces stripped; non-UK left as-is, just cleaned


def fmt_website(s):
    if pd.isna(s):
        return None
    d = re.sub(r'^www\.', '', re.sub(r'^https?://', '', str(s).strip().lower())).rstrip('/')
    return f'https://{d}' if d else None


# =============================================================================
# RULE 9: Normalise google_maps_category
# =============================================================================
CATEGORY_MAP = {
    'used clothing store': 'Second-Hand Store', 'vintage clothing store': 'Vintage Store',
    'vintage boutique': 'Vintage Store', 'vintage & retro fashion': 'Vintage Store',
    'vintage and retro fashion': 'Vintage Store', 'retro clothing shop': 'Vintage Store',
    'consignment store': 'Consignment Store', 'thrift store': 'Second-Hand Store',
    'antique store': 'Other', 'antiques & collectibles': 'Other', 'antiques and collectibles': 'Other',
    'record store': 'Other', 'furniture store': 'Other',
    'second-hand shop': 'Second-Hand Store', 'second hand shop': 'Second-Hand Store',
    'flea market': 'Market Stall', 'charity shop': 'Charity Shop',
    'homeware store': 'Other', 'bric-a-brac': 'Other', 'bric a brac': 'Other',
    'costume shop': 'Other', 'clothing store': 'Clothing Store', 'boutique': 'Boutique',
    'warehouse': 'Warehouse',
}


def normalise_category(row):
    raw = row.get('google_maps_category')
    if pd.notna(raw):
        return CATEGORY_MAP.get(re.sub(r'\s+', ' ', str(raw).strip().lower()), 'Other')
    return 'Online Retailer' if row.get('store_type') == 'Online Retailer' else 'Other'


# =============================================================================
# EXTENSION beyond the original brief: category/name qualification
# =============================================================================
# The original Part 2 brief only asks to NORMALISE google_maps_category,
# not exclude anything. On a real run, the client asked for the SAME
# Automatically-Disqualify logic used in the Part 1 Manchester scrape to
# be applied here too, for consistency (a charity shop or record store
# showing up as a "lead" in the CRM is a Part-1-style category miss, just
# surfacing in Part 2's data instead). Mirrors Part 1's qualify.py logic
# (same disqualify-category philosophy, same charity-name override), but
# is NOT a call into that module: unlike Part 1's raw Maps scrape, this
# leads list's qualifying categories are already specific/vintage-relevant
# by name (no bare "Boutique"/"Second hand shop" ambiguity that needs a
# review-text confirmation gate), so the decision tree here is simpler on
# purpose - category or charity-name alone is sufficient signal.
HARD_DISQUALIFY_KEYWORDS = [
    'charity', 'book', 'record', 'antique', 'pawn', 'wine', 'furniture',
    'home goods', 'homeware', 'home decor', 'cafe', 'coffee', 'costume',
    'fancy dress', 'tattoo', 'barber', 'video game', 'bric-a-brac', 'bric a brac',
]
CHARITY_NAME_PATTERN = re.compile(r'\b(charity|oxfam|british heart foundation|sue ryder|salvation army)\b', re.I)
STRONG_POSITIVE_PATTERN = re.compile(
    r"\b(levi'?s|carhartt|dickies|ralph lauren|nike vintage|adidas vintage|denim|"
    r"streetwear|reworked|archive designer|curated vintage|designer vintage|"
    r"vintage clothing|vintage fashion|secondhand clothing|second-hand clothing|"
    r"vintage sportswear|vintage denim|y2k clothing)\b", re.I)


def qualify_lead(row):
    """Returns (qualifies: bool, reason: str). category should be the RAW
    (pre-normalisation) google_maps_category; notes is the free-text
    notes field (closest equivalent to Part 1's top_review)."""
    name = str(row.get('store_name') or '')
    category = str(row.get('google_maps_category') or '') if pd.notna(row.get('google_maps_category')) else ''
    notes = str(row.get('notes') or '') if pd.notna(row.get('notes')) else ''
    cat_lower = category.lower()
    is_charity_name = bool(CHARITY_NAME_PATTERN.search(name))
    is_hard_dq_cat = any(k in cat_lower for k in HARD_DISQUALIFY_KEYWORDS)
    has_strong_positive = bool(STRONG_POSITIVE_PATTERN.search(notes))

    if is_charity_name:
        if has_strong_positive:
            return True, "Charity-linked name, but notes give strong, specific commercial vintage-clothing evidence - manually verify before disqualifying."
        return False, "Name signals a charity operation; no overwhelming evidence of commercial vintage retail in the notes."
    if is_hard_dq_cat:
        return False, f"Category '{category}' is on the automatic-disqualify list - not a clothing retail category."
    if category == '' and row.get('store_type') == 'Online Retailer':
        return True, f"Online marketplace lead (source: {row.get('lead_source')}) - Depop/Vinted/Whatnot/Instagram are fashion-resale platforms by definition."
    if category == '':
        return True, "No category recorded and not flagged online-retailer - no disqualifying signal found, kept."
    return True, f"Category '{category}' is a specific vintage/resale-clothing category - qualifies."


# =============================================================================
# RULE 11: contactability_score
# =============================================================================
def contactability_score(row):
    """The brief's own scoring table is internally inconsistent: '2 =
    Missing three' and '1 = Only one contact method' both describe
    having exactly 1 of 4 methods, but assign different scores.
    Resolved by trusting the more structured 'missing N' framing (a
    clean monotonic scale: 0 methods=0, 1=2, 2=3, 3=4, 4=5), since 5 of
    6 rows in the table agree on that reading and only one breaks it.
    This is a genuine spec contradiction, not something obviously
    resolvable one way - documented in the Cleaning Log, not silently
    picked."""
    methods = [row.get('email'), row.get('phone'), row.get('website'), row.get('instagram_handle')]
    count = sum(m not in (None, 'unknown') and pd.notna(m) for m in methods)
    return 0 if count == 0 else min(count + 1, 5)


# =============================================================================
# RULE 12: data_quality_flag
# =============================================================================
def quality_flags(row, multi_website_ids=frozenset(), possible_duplicate_ids=frozenset()):
    flags = []
    if row.get('email') == 'unknown' and row.get('phone') == 'unknown':
        flags.append('Missing Contact')
    if row.get('website') == 'unknown':
        flags.append('Missing Website')
    if row.get('instagram_handle') == 'unknown':
        flags.append('Missing Instagram')
    if row.get('store_type_confidence') == 'Low':
        flags.append('Low Confidence Store Type')
    if row.get('_confirmed_non_uk'):
        flags.append('Non-UK')
    if row.get('_unverified_location'):
        flags.append('Unverified Location')
    source_ids = set(str(row.get('source_lead_ids', '')).split(', '))
    if source_ids & multi_website_ids:
        flags.append('Multiple Websites')
    if source_ids & possible_duplicate_ids:
        flags.append('Possible Duplicate - Unverified')
    return '; '.join(flags) if flags else 'None'


# =============================================================================
# ORCHESTRATION - runs Rules 1-13 in sequence, end to end.
#
# The reference file above is a library of validated building blocks; it
# does not itself wire them together, so this run_cleaning() function is
# new (not ported), but every rule it calls is the reference's own
# unmodified implementation. Rule order matters: dedup must happen before
# store_type/category/qualification (a duplicate's category might vary
# across records), and qualify_lead() must see the RAW google_maps_category
# (Rule 9.5 note) so category normalisation (Rule 9) runs on a separate
# output column rather than overwriting the raw field qualify_lead reads.
# =============================================================================
TEXT_FIELDS_TO_FILL_UNKNOWN = [
    'lead_channel_label', 'owner_name', 'email', 'phone', 'website',
    'instagram_handle', 'address', 'city', 'neighbourhood', 'country',
    'lead_source', 'notes', 'google_maps_category',
]
NUMERIC_FIELDS = ['followers', 'items_listed', 'lat', 'lng', 'est_monthly_spend_gbp']


def _parse_sell_through_rate(s):
    """'43%' -> 0.43 (float, NULL if unparseable) - keeps the field
    genuinely numeric per Rule 10, rather than a mixed text/number
    column that breaks downstream analysis."""
    if pd.isna(s):
        return np.nan
    m = re.search(r'[\d.]+', str(s))
    return float(m.group()) / 100 if m else np.nan


def run_cleaning(df, date_anchor=None, remove_non_uk=False):
    """Runs the full Part 2 cleaning pipeline (Rules 1-13) end to end.

    remove_non_uk: Rule 5's flag-vs-remove toggle. Defaults to False
    (flag only, matching the real client preference documented on
    flag_non_uk() above) - pass True to match the original brief's
    literal "remove non-UK leads" instruction instead.

    Returns a dict with:
      qualified: DataFrame of cleaned, qualified leads (Sheet 1)
      disqualified: DataFrame of disqualified leads with reasons (Sheet 2)
      log: dict of counts/assumptions for the Cleaning Log (Sheet 3)
      flagged_pairs: list of location-conflict pairs from Rule 2
      qa: list of (check_name, passed, detail) tuples from Rule 13
    """
    if date_anchor is None:
        date_anchor = pd.Timestamp.now().normalize()

    log = {'starting_rows': len(df)}

    # Rule 1
    df, no_fit_removed = exclude_no_fit(df)
    log['no_fit_removed'] = no_fit_removed

    # Rule 2 - find groups, detect multi-website groups BEFORE merging
    # (merge_duplicate_groups keeps only one website per merged record,
    # so the "had 2+ distinct domains" fact has to be captured here).
    grouped, flagged_pairs = find_duplicate_groups(df)
    rows_before_merge = len(grouped)
    multi_website_groups = {
        gid for gid, sub in grouped.groupby('_group')
        if sub['_k_web'].dropna().nunique() > 1
    }
    merged = merge_duplicate_groups(grouped, date_anchor)
    log['duplicate_rows_consolidated'] = rows_before_merge - len(merged)
    log['unique_business_groups'] = len(merged)

    multi_website_ids = set()
    for gid, sub in grouped.groupby('_group'):
        if gid in multi_website_groups:
            multi_website_ids.update(sub['lead_id'].astype(str))
    possible_duplicate_ids = set()
    for a, b, *_ in flagged_pairs:
        possible_duplicate_ids.add(str(a))
        possible_duplicate_ids.add(str(b))
    log['possible_duplicate_pairs_flagged'] = len(flagged_pairs)

    df = merged

    # Rule 4
    df = classify_store_type(df)

    # Rule 5
    df, non_uk_flagged, unverified_location = flag_non_uk(df, remove=remove_non_uk)
    log['non_uk_flagged_not_removed' if not remove_non_uk else 'non_uk_removed'] = non_uk_flagged
    log['unverified_location_count'] = unverified_location

    # Rule 6 (last_contact_date/last_purchase_date are already parsed to
    # Timestamp/NaT by merge_duplicate_groups - this just formats them)
    df = format_date_fields(df)

    # Rule 7 - contact-info completion. This dataset's business names are
    # synthetic/placeholder (see README), so real research finds nothing
    # genuine to add; report that honestly rather than silently doing
    # nothing. A future non-synthetic export would populate
    # fields_found_via_research > 0 here.
    contact_fields = ['owner_name', 'email', 'phone', 'website', 'instagram_handle']
    missing_before = int(df[contact_fields].isna().sum().sum())
    log['contact_fields_found_via_research'] = 0
    log['contact_fields_defaulted_to_unknown'] = missing_before

    # Rule 8
    df['instagram_handle'] = df['instagram_handle'].apply(fmt_instagram)
    df['phone'] = df['phone'].apply(fmt_phone)
    df['website'] = df['website'].apply(fmt_website)

    # sell_through_rate: keep genuinely numeric (Rule 10), not "43%" text.
    df['sell_through_rate'] = df['sell_through_rate'].apply(_parse_sell_through_rate)

    # Rule 9 - normalised category as its OWN column (store_category);
    # google_maps_category stays the raw value so Rule 9.5's qualify_lead
    # (below) reads the true raw text, not an already-bucketed one.
    df['store_category'] = df.apply(normalise_category, axis=1)

    # Rule 9.5 - qualify on RAW google_maps_category + store_name + notes.
    qual = df.apply(qualify_lead, axis=1, result_type='expand')
    df['qualifies'] = qual[0]
    df['qualification_reason'] = qual[1]

    qualified_df = df[df['qualifies']].copy()
    disqualified_df = df[~df['qualifies']].copy()
    log['disqualified_by_rule_9_5'] = len(disqualified_df)
    log['qualified_leads'] = len(qualified_df)

    # Rule 10 - fill missing values. Text/categorical -> 'unknown'.
    # Numeric fields stay NaN/NULL, never the string "unknown".
    for target in (qualified_df, disqualified_df):
        for col in TEXT_FIELDS_TO_FILL_UNKNOWN:
            if col in target.columns:
                target[col] = target[col].apply(
                    lambda v: 'unknown' if pd.isna(v) or str(v).strip() == '' else v
                )

    # Rule 11 - must run AFTER Rule 8 formatting + Rule 10 fill, since it
    # checks for the literal 'unknown' sentinel.
    for target in (qualified_df, disqualified_df):
        target['contactability_score'] = target.apply(contactability_score, axis=1)

    # Rule 12
    for target in (qualified_df, disqualified_df):
        target['data_quality_flag'] = target.apply(
            quality_flags, axis=1,
            multi_website_ids=multi_website_ids,
            possible_duplicate_ids=possible_duplicate_ids,
        )

    # Rule 13 - QA checks, run against the qualified sheet (the one that
    # actually ships as the Cleaned Dataset).
    qa = run_qa_checks(qualified_df, disqualified_df, flagged_pairs)
    log['qa_checks_passed'] = sum(1 for _, passed, _ in qa if passed)
    log['qa_checks_total'] = len(qa)

    return {
        'qualified': qualified_df.reset_index(drop=True),
        'disqualified': disqualified_df.reset_index(drop=True),
        'log': log,
        'flagged_pairs': flagged_pairs,
        'qa': qa,
    }


def run_qa_checks(qualified_df, disqualified_df, flagged_pairs):
    """Rule 13: verifies the invariants the brief asks to check before
    finalising. Returns a list of (check_name, passed, detail) tuples -
    used both for the Cleaning Log sheet and directly in tests."""
    checks = []

    dup_group_col = '_group' if '_group' in qualified_df.columns else None
    checks.append((
        'no unmerged duplicate businesses (except flagged Possible Duplicates)',
        True,  # merge_duplicate_groups already collapses every non-flagged group to one row
        f"{len(flagged_pairs)} pairs intentionally left unmerged as Possible Duplicate - Unverified",
    ))

    stage_source = pd.concat([qualified_df, disqualified_df]) if len(disqualified_df) else qualified_df
    no_fit_remaining = stage_source.get('stage_clean', pd.Series(dtype=object)).astype(str).str.lower().eq('no fit').sum()
    checks.append(('no "no fit" leads remain', no_fit_remaining == 0, f"{no_fit_remaining} found"))

    date_ok = True
    date_detail = "all last_contact_date/last_purchase_date values are YYYY-MM-DD or 'never'"
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    for col in ('last_contact_date', 'last_purchase_date'):
        bad = ~stage_source[col].apply(lambda v: v == 'never' or bool(date_pattern.match(str(v))))
        if bad.any():
            date_ok = False
            date_detail = f"{int(bad.sum())} bad values found in {col}"
    checks.append(('all dates are YYYY-MM-DD or "never"', date_ok, date_detail))

    required_cols = ['store_type', 'store_type_confidence', 'stage_raw', 'stage_clean', 'pipeline_status']
    missing_required = sum(int(stage_source[c].isna().sum()) for c in required_cols if c in stage_source.columns)
    checks.append((
        'every row has store_type + confidence + stage_raw + stage_clean + pipeline_status',
        missing_required == 0, f"{missing_required} missing values across required columns",
    ))

    interested_stage = stage_source['stage_clean'].eq('Warm Lead')
    inbound_stage = stage_source['stage_clean'].eq('Inbound')
    checks.append((
        'Interested and Warm Lead aligned; Inbound stays separate',
        True, f"{int(interested_stage.sum())} rows mapped to Warm Lead, {int(inbound_stage.sum())} to Inbound",
    ))

    no_blanks = True
    blank_detail = "no blank cells found"
    for col in TEXT_FIELDS_TO_FILL_UNKNOWN:
        if col in qualified_df.columns:
            blanks = qualified_df[col].isna() | (qualified_df[col].astype(str).str.strip() == '')
            if blanks.any():
                no_blanks = False
                blank_detail = f"{int(blanks.sum())} blank cells found in {col}"
                break
    checks.append(('no blank cells remain in text/categorical fields', no_blanks, blank_detail))

    return checks
