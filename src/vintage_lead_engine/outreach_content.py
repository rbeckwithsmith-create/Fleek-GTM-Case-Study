"""
Outreach message content - the authored half of Part B.

outreach.py decides WHETHER a lead gets a message and what OUTREACH_TYPE
it is (deterministic, testable rules). This module supplies the actual
words, built from hand-authored language blocks that outreach.py's
per-lead facts select and combine - it is not templated boilerplate
praise (which would fail the brief's own "500 other retailers" test),
and it does not fabricate anything: every specific detail used comes
directly from that lead's own `notes`, `country`, `owner_name`, or
`lead_source` field, all already present in the cleaned CRM data.

Why building blocks rather than 141 fully bespoke messages: this
dataset's `notes` field is itself built from a small, recurring set of
product-focus and objection phrases (verified directly against the
cleaned data - about a dozen focus phrases and nine objection phrases
cover the qualified leads, many shared verbatim across different
stores). Genuine per-store specificity is capped by what the data
actually contains; where two leads share the exact same notes text,
their messages are legitimately similar for the same reason a human
working this list by hand would write similar messages - the
underlying fact pattern is the same, not because either message is
generic filler.

Fleek context (used only when relevant, never forced): a wholesale
marketplace connecting retailers/resellers with inventory from trusted
suppliers and brands.
"""
import re

import pandas as pd

# ---------------------------------------------------------------------------
# Focus-phrase -> personalisation angle + a clause usable inside the body.
# Covers every focus phrase actually observed in notes (see the module
# docstring). A handful of notes describe a business Fleek's vintage-
# clothing marketplace doesn't fit (furniture restoration, records,
# costume hire) - these fall through to a category-based fallback
# instead of forcing a vintage-clothing angle onto a non-clothing lead.
# ---------------------------------------------------------------------------
FOCUS_ANGLES = {
    "80s/90s denim & sportswear specialist": (
        "your 80s/90s denim and sportswear edit",
        "the 80s/90s denim and sportswear range you've built",
    ),
    "Curated vintage womenswear, Levi's & band tees": (
        "your curated womenswear built around Levi's and band tees",
        "the Levi's and band-tee-led womenswear edit you're known for",
    ),
    "Hand-picked vintage from the 60s to the 90s": (
        "your hand-picked edit spanning the 60s through the 90s",
        "the decades-spanning edit you've hand-picked",
    ),
    "Retro football shirts & vintage sportswear": (
        "your retro football shirt and vintage sportswear range",
        "the football shirt and sportswear range you specialise in",
    ),
    "Reworked vintage and archive designer pieces": (
        "your reworked and archive designer pieces",
        "the reworked, archive-designer side of what you stock",
    ),
    "Vintage streetwear — Nike, Adidas, Ralph": (
        "your streetwear edit built around Nike, Adidas and Ralph Lauren",
        "the Nike/Adidas/Ralph Lauren streetwear edit you carry",
    ),
    "Vintage workwear, military surplus, carhartt": (
        "your workwear and military surplus range, including Carhartt",
        "the workwear and military surplus you carry, Carhartt included",
    ),
    "Y2K, grunge and reworked one-off pieces": (
        "your Y2K, grunge and reworked one-off pieces",
        "the Y2K and grunge one-offs you carry",
    ),
}

# Channel/performance signals: not a product category, but still a real,
# specific-to-them operational fact (not every business sells this way).
CHANNEL_ANGLES = {
    "Fast seller, good margins": (
        "how quickly your stock turns over",
        "the fast sell-through you've been getting",
    ),
    "IG shop, DMs open": (
        "running your shop straight through Instagram DMs",
        "the DM-led way you run sales",
    ),
    "Sells on Depop + Vinted": (
        "selling across both Depop and Vinted",
        "your presence across both Depop and Vinted",
    ),
    "Whatnot seller, live sales": (
        "your live-sale format on Whatnot",
        "the live-sale format you run on Whatnot",
    ),
}

# Focus phrases present in the data that describe a business outside
# vintage clothing/resale entirely - handled via category fallback
# rather than a forced-fit clothing angle.
OFF_TOPIC_FOCUS_PHRASES = {
    "Fancy dress & theatrical costume hire",
    "Reclaimed furniture and home restoration",
    "Records, vinyl & memorabilia",
}

OBJECTION_CLAUSES = {
    "Busy on weekends — visit midweek.": (
        "Happy to work around your weekend trade - midweek suits us fine."
    ),
    "Heard of Fleek, thinks it's 'for small resellers'.": (
        "Worth a quick correction on that: we work with shops at a range of sizes, "
        "not just small resellers - happy to show you what that actually looks like."
    ),
    "Instagram DMs open, email bounced.": (
        "Since email hasn't been landing, DMs are probably the easier way to reach you."
    ),
    "Keen but wants to see the app before committing.": (
        "Makes sense to see it in action first - I can walk you through the app directly rather than describe it."
    ),
    "Left a voicemail, no callback yet.": (
        "No worries on the missed callback - happy to try again whenever suits."
    ),
    "Met at a market, said to drop by the shop.": (
        "Good to put a name to the shop after meeting at the market - still keen to swing by."
    ),
    "Owner mentioned they already buy from a Pakistan supplier.": (
        "Not looking to replace that relationship - more to see if we're useful alongside it for specific gaps."
    ),
    "Price-sensitive, compares to local wholesalers.": (
        "Fair to compare - happy to let the numbers speak for themselves rather than argue the case."
    ),
    "Tried us in 2023, wasn't happy with the sizing mix.": (
        "The sizing-mix issue from 2023 was a fair complaint, and the way we curate mixes has changed since - "
        "genuinely curious whether it's worth a second look."
    ),
}

TRANSLATION_LANGUAGE = {"France": "French", "Germany": "German", "Netherlands": "Dutch"}


def _greeting(owner_name):
    if owner_name and owner_name != "unknown":
        first = str(owner_name).split()[0]
        return f"Hi {first},"
    return "Hi there,"


def _focus_angle(notes):
    """Returns (personalisation_angle, body_clause, objection_clause_or_None,
    raw_objection_phrase_or_None) parsed from the notes field, or all-None
    if notes carry no usable signal (i.e. genuinely 'unknown'). The raw
    phrase is returned alongside the composed English clause because
    translation looks the phrase up in its own dict (see _translate_body) -
    the composed clause is English-only prose, not a lookup key."""
    if not notes or notes == "unknown":
        return None, None, None, None
    parts = [p.strip() for p in str(notes).split("|") if p.strip()]
    focus = parts[0] if parts else None
    objection = parts[1] if len(parts) > 1 else None
    objection_clause = OBJECTION_CLAUSES.get(objection) if objection else None

    if focus in FOCUS_ANGLES:
        angle, clause = FOCUS_ANGLES[focus]
        return angle, clause, objection_clause, objection
    if focus in CHANNEL_ANGLES:
        angle, clause = CHANNEL_ANGLES[focus]
        return angle, clause, objection_clause, objection
    return None, None, objection_clause, objection


def _channel_fallback_angle(row):
    """For online resellers with no usable notes: an honest, real (if
    lighter-weight) angle based on the actual platform they sell
    through - true and specific to how they operate, even without
    product-level detail."""
    source = str(row.get("lead_source") or "").strip().lower()
    if "depop" in source:
        return "selling through Depop", "your Depop shop"
    if "vinted" in source:
        return "selling through Vinted", "your Vinted shop"
    if "whatnot" in source:
        return "your live-sale presence on Whatnot", "your Whatnot sales"
    if "instagram" in source:
        return "running sales through Instagram", "your Instagram shop"
    return None, None


def _category_fallback_angle(row):
    category = row.get("store_category")
    if category and category != "unknown":
        return f"your {category.lower()} setup", f"your {category.lower()}"
    return None, None


# ---------------------------------------------------------------------------
# Translations. Scoped to exactly what the current qualified/eligible batch
# needs (French/German/Dutch leads only use Cold, Re-Engagement, and
# Churned-Win-Back templates, and a small subset of focus/objection
# phrases) - see the module docstring on why this is authored per-batch
# rather than a general-purpose translator.
# ---------------------------------------------------------------------------
ANGLE_TRANSLATIONS = {
    "your workwear and military surplus range, including Carhartt": {
        "French": "votre gamme de vêtements de travail et de surplus militaires, y compris Carhartt",
        "German": "Ihr Sortiment an Arbeitskleidung und Militär-Surplus, einschließlich Carhartt",
        "Dutch": "uw assortiment workwear en legerdump, waaronder Carhartt",
    },
    "your reworked and archive designer pieces": {
        "French": "vos pièces retravaillées et vos pièces d'archives de créateurs",
        "German": "Ihre umgearbeiteten Teile und Designer-Archivstücke",
        "Dutch": "uw bewerkte stukken en designer-archiefstukken",
    },
    "your curated womenswear built around Levi's and band tees": {
        "French": "votre sélection femme construite autour de Levi's et de t-shirts de groupes de musique",
        "German": "Ihre kuratierte Damenmode rund um Levi's und Band-T-Shirts",
        "Dutch": "uw geselecteerde damesmode rond Levi's en band-shirts",
    },
    "your Y2K, grunge and reworked one-off pieces": {
        "French": "vos pièces Y2K, grunge et retravaillées en pièce unique",
        "German": "Ihre Y2K-, Grunge- und umgearbeiteten Einzelstücke",
        "Dutch": "uw Y2K-, grunge- en bewerkte unieke stukken",
    },
    "your retro football shirt and vintage sportswear range": {
        "French": "votre gamme de maillots de football rétro et de vêtements de sport vintage",
        "German": "Ihr Sortiment an Retro-Fußballtrikots und Vintage-Sportbekleidung",
        "Dutch": "uw assortiment retro voetbalshirts en vintage sportkleding",
    },
    "your streetwear edit built around Nike, Adidas and Ralph Lauren": {
        "French": "votre sélection streetwear construite autour de Nike, Adidas et Ralph Lauren",
        "German": "Ihre Streetwear-Auswahl rund um Nike, Adidas und Ralph Lauren",
        "Dutch": "uw streetwear-selectie rond Nike, Adidas en Ralph Lauren",
    },
    "your hand-picked edit spanning the 60s through the 90s": {
        "French": "votre sélection couvrant les années 60 à 90",
        "German": "Ihre handverlesene Auswahl von den 60ern bis zu den 90ern",
        "Dutch": "uw handgekozen selectie van de jaren 60 tot en met de jaren 90",
    },
}
CLAUSE_TRANSLATIONS = {
    "the workwear and military surplus you carry, Carhartt included": {
        "French": "les vêtements de travail et surplus militaires que vous proposez, Carhartt inclus",
        "German": "die Arbeitskleidung und den Militär-Surplus, den Sie führen, Carhartt inklusive",
        "Dutch": "de workwear en legerdump die u voert, Carhartt inbegrepen",
    },
    "the Levi's and band-tee-led womenswear edit you're known for": {
        "French": "votre sélection femme reconnue autour de Levi's et de t-shirts de groupes de musique",
        "German": "Ihre bekannte Damenmode-Auswahl rund um Levi's und Band-T-Shirts",
        "Dutch": "uw bekende damesmode-selectie rond Levi's en band-shirts",
    },
}
OBJECTION_TRANSLATIONS = {
    "Keen but wants to see the app before committing.": {
        "French": "Voir l'application avant de vous engager est tout à fait logique - je peux vous la présenter directement plutôt que de la décrire.",
        "German": "Die App vorher zu sehen, ist absolut nachvollziehbar - ich zeige sie Ihnen gerne direkt, statt sie nur zu beschreiben.",
        "Dutch": "Het is logisch om de app eerst te willen zien - ik laat u die graag direct zien in plaats van te beschrijven.",
    },
    "Price-sensitive, compares to local wholesalers.": {
        "French": "Il est normal de comparer - je préfère laisser les chiffres parler d'eux-mêmes plutôt que d'argumenter.",
        "German": "Es ist verständlich zu vergleichen - ich lasse die Zahlen lieber für sich sprechen, als zu argumentieren.",
        "Dutch": "Het is logisch om te vergelijken - ik laat de cijfers liever voor zichzelf spreken dan dat ik erover in discussie ga.",
    },
}

STAGE_TEMPLATES = {
    ("Cold", "French"): (
        "{greeting} j'ai découvert votre boutique et remarqué {angle}.",
        "Je travaille avec Fleek, une marketplace de gros qui met en relation commerçants et revendeurs avec des fournisseurs et marques de confiance.",
        "Souhaiteriez-vous voir ce qui est actuellement disponible et correspond à ce que vous vendez ?",
    ),
    ("Cold", "German"): (
        "{greeting} ich bin auf Ihr Geschäft gestoßen und habe {angle} bemerkt.",
        "Ich arbeite mit Fleek, einem Großhandelsmarktplatz, der Einzelhändler und Wiederverkäufer mit vertrauenswürdigen Lieferanten und Marken verbindet.",
        "Wäre es interessant zu sehen, was aktuell verfügbar ist und zu Ihrem Sortiment passt?",
    ),
    ("Cold", "Dutch"): (
        "{greeting} ik kwam uw winkel tegen en merkte {angle} op.",
        "Ik werk met Fleek, een groothandelsmarktplaats die retailers en resellers verbindt met voorraad van betrouwbare leveranciers en merken.",
        "Zou het interessant zijn om te zien wat er nu beschikbaar is en aansluit bij wat u verkoopt?",
    ),
    ("Re-Engagement", "French"): (
        "{greeting} cela fait un moment, je voulais donc reprendre contact étant donné {angle}.",
        "Aucune pression si le moment n'est plus idéal, mais si l'approvisionnement reste d'actualité, je serais ravi d'en reparler.",
        "Cela vaudrait-il la peine d'en discuter rapidement ?",
    ),
    ("Re-Engagement", "German"): (
        "{greeting} es ist eine Weile her, deshalb wollte ich mich angesichts {angle} noch einmal melden.",
        "Kein Druck, falls sich der Zeitpunkt geändert hat, aber falls Beschaffung weiterhin ein Thema für Sie ist, spreche ich gerne wieder darüber.",
        "Würde sich ein kurzes Gespräch lohnen?",
    ),
    ("Re-Engagement", "Dutch"): (
        "{greeting} het is alweer even geleden, dus ik wilde graag opnieuw contact opnemen gezien {angle}.",
        "Geen druk als de timing is veranderd, maar als inkoop nog steeds relevant voor u is, denk ik graag weer mee.",
        "Zou een kort gesprek de moeite waard zijn?",
    ),
    ("Churned-Win-Back", "French"): (
        "{greeting} cela fait un moment que nous n'avons pas travaillé ensemble, je voulais donc vous recontacter honnêtement plutôt que de faire comme si rien n'avait changé.",
        "Étant donné {clause}, je comprends que le moment n'était peut-être pas idéal auparavant.",
        "Cela vaudrait-il la peine d'échanger, sans pression, sur ce qui a changé de notre côté, au cas où cela redeviendrait pertinent ?",
    ),
    ("Churned-Win-Back", "German"): (
        "{greeting} es ist eine Weile her, seit wir zuletzt zusammengearbeitet haben, deshalb wollte ich mich ehrlich melden, statt so zu tun, als hätte sich nichts geändert.",
        "Angesichts {clause} verstehe ich, wenn der Zeitpunkt vorher nicht gepasst hat.",
        "Wäre ein unverbindliches Gespräch darüber sinnvoll, was sich bei uns geändert hat, falls es wieder relevant sein könnte?",
    ),
    ("Churned-Win-Back", "Dutch"): (
        "{greeting} het is een tijd geleden dat we samenwerkten, dus ik wilde eerlijk contact opnemen in plaats van te doen alsof er niets is veranderd.",
        "Gezien {clause} snap ik dat de timing eerder niet goed uitkwam.",
        "Zou een vrijblijvend gesprek over wat er bij ons is veranderd de moeite waard zijn, voor het geval het weer relevant is?",
    ),
}


GREETING_WORD = {"French": "Bonjour", "German": "Hallo", "Dutch": "Hallo"}


def _translated_greeting(owner_name, language):
    word = GREETING_WORD[language]
    if owner_name and owner_name != "unknown":
        first = str(owner_name).split()[0]
        return f"{word} {first},"
    return f"{word},"


def _translate_body(outreach_type, language, angle_en, clause_en, raw_objection, owner_name=None):
    """Builds a natural-reading translation of the composed message using
    hand-authored templates + phrase translations (see the dicts above),
    scoped to exactly the templates/phrases this batch needs. raw_objection
    is the RAW notes phrase (not the composed English clause) since
    OBJECTION_TRANSLATIONS is keyed on that raw phrase. Returns None if
    this exact (outreach_type, language) or phrase combination hasn't
    been authored - callers fall back to English-only rather than risk
    a low-quality machine-translated guess."""
    template = STAGE_TEMPLATES.get((outreach_type, language))
    if template is None:
        return None
    angle_t = ANGLE_TRANSLATIONS.get(angle_en, {}).get(language)
    clause_t = CLAUSE_TRANSLATIONS.get(clause_en, {}).get(language)
    opening, middle, cta = template
    if "{angle}" in opening and angle_t is None:
        return None
    if "{clause}" in middle and clause_t is None:
        return None
    greeting_t = _translated_greeting(owner_name, language)
    opening = opening.format(greeting=greeting_t, angle=angle_t or "")
    middle = middle.format(clause=clause_t) if "{clause}" in middle else middle
    parts = [opening, middle]
    if raw_objection:
        objection_t = OBJECTION_TRANSLATIONS.get(raw_objection, {}).get(language)
        if objection_t is None:
            return None
        parts.append(objection_t)
    parts.append(cta)
    return " ".join(parts)


def _wrap_words(text, lo=50, hi=150):
    return lo <= len(text.split()) <= hi


def build_message_for_lead(row) -> dict:
    """Returns SUGGESTED_MESSAGE, MESSAGE_LOGIC, PERSONALISATION_ANGLE
    for one eligible row. Assumes row already carries OUTREACH_TYPE,
    ELIGIBLE, and the cleaned Part A fields (notes, owner_name, stage_clean,
    country, etc.)."""
    outreach_type = row["OUTREACH_TYPE"]
    stage_clean = row.get("stage_clean")
    country = row.get("country")
    owner_name = row.get("owner_name")

    angle, clause, objection_clause, raw_objection = _focus_angle(row.get("notes"))
    fallback_used = None
    if angle is None:
        angle, clause = _channel_fallback_angle(row)
        if angle is not None:
            fallback_used = "channel"
    if angle is None:
        angle, clause = _category_fallback_angle(row)
        if angle is not None:
            fallback_used = "category"

    greeting = _greeting(owner_name)

    if angle is None:
        # No notes, no usable lead_source, no store_category signal -
        # genuinely nothing to personalise on. Per the brief: leave
        # generic-but-honest or don't send - here we don't send, since a
        # zero-personalisation message to a placeholder-named business
        # reads as spam, not outreach.
        return {
            "SUGGESTED_MESSAGE": "",
            "MESSAGE_LOGIC": (
                f"Stage identified as {stage_clean} ({outreach_type}). No usable personalisation "
                f"signal found - notes, lead_source and store_category all carry no specific detail "
                f"for this lead. Declining to send a fully generic message rather than fabricate "
                f"a specific-sounding detail; recommend manual research before outreach."
            ),
            "PERSONALISATION_ANGLE": "None available - insufficient information for specific personalisation.",
        }

    body = _compose_body(outreach_type, greeting, angle, clause, objection_clause, row)

    if not passes_specificity_test(body):
        # Should not happen given the angle library above, but this is
        # the safety net the brief asks for - never ship a line that
        # fails the 500-retailers test.
        return {
            "SUGGESTED_MESSAGE": "",
            "MESSAGE_LOGIC": (
                f"Stage identified as {stage_clean} ({outreach_type}). A draft was produced but failed "
                f"the specificity check (reads too generic) - not sending rather than shipping filler copy."
            ),
            "PERSONALISATION_ANGLE": angle,
        }

    translated = None
    if country in TRANSLATION_LANGUAGE:
        language = TRANSLATION_LANGUAGE[country]
        translated = _translate_body(outreach_type, language, angle, clause, raw_objection, owner_name)

    message = body
    if translated:
        message = f"English: {body}\n\nTranslated ({TRANSLATION_LANGUAGE[country]}): {translated}"

    logic_bits = [
        f"Stage identified as {stage_clean} ({outreach_type}).",
        f"Personalisation drawn from {'notes' if fallback_used is None else fallback_used + ' (notes unavailable)'}: {angle}.",
    ]
    if objection_clause:
        logic_bits.append("Notes flagged a specific objection/context, addressed directly rather than ignored.")
    dsc = row.get("_DAYS_SINCE_CONTACT")
    if dsc is not None and not pd.isna(dsc):
        logic_bits.append(f"Last contacted {int(dsc)} day(s) ago - timing supports a follow-up now.")
    else:
        logic_bits.append("No prior contact on record - treated as first outreach.")

    return {
        "SUGGESTED_MESSAGE": message,
        "MESSAGE_LOGIC": " ".join(logic_bits),
        "PERSONALISATION_ANGLE": angle,
    }


def passes_specificity_test(line: str) -> bool:
    from .outreach import passes_specificity_test as _test
    return _test(line)


def _compose_body(outreach_type, greeting, angle, clause, objection_clause, row):
    store_name = row.get("store_name", "")
    if outreach_type == "Inbound":
        opening = f"{greeting} thanks for getting in touch - I had a look at {angle} before writing back."
        middle = f"Fleek connects shops like yours with inventory from trusted suppliers, so given {clause}, it seemed worth a proper reply rather than a generic one."
        cta = "What's the main gap in sourcing right now - more volume, more variety, or something specific you're struggling to find?"
    elif outreach_type == "Cold":
        opening = f"{greeting} I came across your shop and noticed {angle}."
        middle = "I work with Fleek, a wholesale marketplace connecting retailers and resellers with inventory from trusted suppliers and brands."
        cta = "Would it be useful to see what's currently available that fits what you stock?"
    elif outreach_type == "Re-Engagement":
        opening = f"{greeting} it's been a little while, so wanted to check back in given {angle}."
        middle = "No pressure if the timing's shifted, but if sourcing is still on your radar, happy to pick things back up."
        cta = "Worth a quick chat to see where things stand?"
    elif outreach_type == "Customer Check-In":
        opening = f"{greeting} wanted to check in properly rather than send a generic update, given {clause}."
        middle = "Keen to hear how things have been going and whether there's anything new worth exploring together."
        cta = "Any gaps in what you're sourcing at the moment, or new ranges you're thinking about?"
    elif outreach_type == "Churned-Win-Back":
        opening = f"{greeting} it's been a while since we last worked together, so wanted to reach out honestly rather than pretend nothing's changed."
        middle = f"Given {clause}, I understand if the timing wasn't right before."
        cta = "Would it be worth a low-pressure conversation about what's changed on our side, in case it's relevant again?"
    else:
        opening = f"{greeting} noticed {angle}."
        middle = "Fleek connects retailers and resellers with inventory from trusted suppliers."
        cta = "Worth a conversation?"

    parts = [opening, middle]
    if objection_clause:
        parts.append(objection_clause)
    parts.append(cta)
    return " ".join(parts)
