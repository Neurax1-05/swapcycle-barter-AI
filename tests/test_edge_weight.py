"""Broad categories and substring matches must not score like an exact item."""

import firestore_bridge as bridge

W = bridge.compute_edge_weight
THRESHOLD = bridge.EDGE_WEIGHT_THRESHOLD


def pref(**kw):
    base = {
        "item_category": "", "desired_item": "", "keywords": [],
        "acceptable_brands": [], "minimum_condition": "any",
        "flexibility": 0.0,
    }
    base.update(kw)
    return base


def listing(item, category, brand="", condition="good"):
    return {"item": item, "category": category, "brand": brand,
            "condition": condition}


def test_phone_does_not_match_headphones_in_electronics():
    # The slide's example: this used to score 0.85.
    p = pref(item_category="electronics", desired_item="phone",
             keywords=["phone"])
    assert W(p, listing("Sony headphones", "electronics")) < THRESHOLD


def test_phone_still_matches_a_phone_in_electronics():
    p = pref(item_category="electronics", desired_item="phone",
             keywords=["phone"])
    assert W(p, listing("Samsung phone", "electronics")) >= THRESHOLD


def test_broad_category_alone_is_not_enough():
    p = pref(item_category="other", desired_item="drone")
    assert W(p, listing("Board game", "other")) < THRESHOLD


def test_keyword_hit_rescues_a_broad_category():
    p = pref(item_category="electronics", desired_item="gadget",
             keywords=["tablet"])
    assert W(p, listing("iPad tablet", "electronics")) >= THRESHOLD


def test_specific_category_still_counts_without_item_text():
    p = pref(item_category="guitar", desired_item="beginner guitar")
    assert W(p, listing("Yamaha FG800", "guitar")) >= THRESHOLD


def test_broad_category_name_is_not_an_item_hit():
    p = pref(item_category="electronics", desired_item="electronics")
    assert W(p, listing("Sony headphones", "electronics")) < THRESHOLD


def test_whole_word_matching():
    assert bridge.phrase_in_text("phone", "samsung phone")
    assert bridge.phrase_in_text("guitar", "yamaha guitars")  # plain plural
    assert not bridge.phrase_in_text("phone", "sony headphones")
    assert not bridge.phrase_in_text("car", "carpet")
    assert not bridge.phrase_in_text("", "anything")


def test_worked_examples_from_the_deck_are_unchanged():
    alice = pref(item_category="guitar", desired_item="guitar",
                 acceptable_brands=["yamaha"], minimum_condition="good",
                 flexibility=0.5)
    assert W(alice, listing("Yamaha guitar", "guitar", "Yamaha")) == 0.95

    bob = pref(item_category="camera", desired_item="camera",
               minimum_condition="good", flexibility=0.3)
    assert W(bob, listing("Trek bicycle", "bicycle", "Trek")) == 0.28
