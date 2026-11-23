import sync_functions


def test_functions_folder_is_in_sync():
    assert sync_functions.stale_files() == [], (
        "functions/ copies are stale - run `python sync_functions.py`"
    )
