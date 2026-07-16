import pandas as pd

from vintage_lead_engine.qualify import qualify_dataframe


def _qualify_one(place_name, maps_category, top_review):
    df = pd.DataFrame([{
        "place_name": place_name,
        "maps_category": maps_category,
        "top_review": top_review,
    }])
    return qualify_dataframe(df).iloc[0]


def test_vintage_wines_disqualified_by_category_despite_name():
    row = _qualify_one(
        "Vintage Wines & Spirits", "Wine shop",
        "Great little wine shop, nice selection of natural wines",
    )
    assert not row["qualifies"]
    assert "disqualify" in row["qualification_reason"].lower()


def test_vintage_tea_rooms_disqualified_by_category_despite_name():
    row = _qualify_one(
        "The Vintage Tea Rooms", "Cafe",
        "Lovely spot for coffee and cake in a vintage setting",
    )
    assert not row["qualifies"]


def test_genuine_boutique_with_levis_review_qualifies():
    row = _qualify_one(
        "Corner Boutique", "Boutique",
        "Amazing rack of Levi's denim and some great 90s finds",
    )
    assert row["qualifies"]


def test_boutique_with_generic_review_disqualifies():
    row = _qualify_one(
        "Corner Boutique", "Boutique",
        "Friendly staff, nice little shop",
    )
    assert not row["qualifies"]
    assert "insufficient evidence" in row["qualification_reason"].lower()


def test_charity_name_no_strong_evidence_disqualified():
    row = _qualify_one(
        "Oxfam Bridgford", "Vintage Store",
        "Bit of everything here, all proceeds to charity",
    )
    assert not row["qualifies"]
    assert "charity" in row["qualification_reason"].lower()


def test_charity_name_with_strong_evidence_qualifies():
    row = _qualify_one(
        "Sue Ryder Vintage", "Vintage Store",
        "Surprisingly good curated vintage - found a rack of reworked Levi's and Carhartt",
    )
    assert row["qualifies"]


def test_charity_name_generic_designer_language_not_strong_enough():
    # Generic "designer" language (no NAMED brands) must NOT count as
    # strong evidence for a charity-linked name - this mirrors the real
    # Oxfam Originals case in data/real_manchester_shortlist.csv.
    row = _qualify_one(
        "Oxfam Originals", "Vintage & Designer Clothing Store",
        "Hand-selected vintage and designer clothing, each piece carefully researched",
    )
    assert not row["qualifies"]


def test_hard_disqualify_category_ignores_stray_positive_word_in_review():
    # A stray "vintage"/"retro" word in the review must never override
    # an unconditional hard-disqualify category - the exact name-trap
    # the brief warns about, tested from the other direction.
    row = _qualify_one(
        "Book Nook", "Book store",
        "Charming vintage-style bookshop, great retro atmosphere",
    )
    assert not row["qualifies"]


def test_qualified_businesses_never_deleted_stay_visible_with_reason():
    df = pd.DataFrame([
        {"place_name": "Vintage Wines & Spirits", "maps_category": "Wine shop",
         "top_review": "Great little wine shop"},
        {"place_name": "Corner Boutique", "maps_category": "Boutique",
         "top_review": "Amazing Levi's denim rack"},
    ])
    out = qualify_dataframe(df)
    assert len(out) == 2
    assert set(out["place_name"]) == {"Vintage Wines & Spirits", "Corner Boutique"}
    assert out["qualification_reason"].notna().all()
    assert (out["qualification_reason"] != "").all()
