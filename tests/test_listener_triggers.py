import types

import local_listener as L


def change(kind, data=None):
    doc = types.SimpleNamespace(to_dict=lambda: data or {})
    return types.SimpleNamespace(type=types.SimpleNamespace(name=kind),
                                 document=doc)


def test_new_preference_and_new_listing_trigger_a_run():
    assert L.is_trigger("preferences", change("ADDED"))
    assert L.is_trigger("listings", change("ADDED"))


def test_edits_to_preferences_or_listings_do_not_trigger():
    # The pipeline itself edits preferences (pending -> processed).
    assert not L.is_trigger("preferences", change("MODIFIED"))
    assert not L.is_trigger("listings", change("MODIFIED"))


def test_declined_match_triggers_but_other_match_changes_do_not():
    assert L.is_trigger("matches", change("MODIFIED", {"status": "declined"}))
    assert not L.is_trigger("matches", change("MODIFIED", {"status": "confirmed"}))
    assert not L.is_trigger("matches", change("ADDED", {"status": "declined"}))
    assert not L.is_trigger("matches", change("MODIFIED", {"status": "pending"}))
