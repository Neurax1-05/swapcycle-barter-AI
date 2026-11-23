import csv

import calibrate_weights as cw
from matching_config import DEFAULT_WEIGHTS


def test_ahp_consistent_matrix_has_low_cr():
    # item = 2*brand, brand = 2*condition, condition = 2*openness (+ implied)
    pairs = {("item", "brand"): 2, ("item", "condition"): 4, ("item", "openness"): 8,
             ("brand", "condition"): 2, ("brand", "openness"): 4, ("condition", "openness"): 2}
    w, cr = cw.ahp_weights(pairs)
    assert abs(sum(w.values()) - 1) < 1e-9
    assert cr < 0.01 and w["item"] > w["brand"] > w["condition"] > w["openness"]


def test_calibration_end_to_end(tmp_path):
    rows = cw.read("survey/example_responses.csv")
    imp, used, dropped = cw.importances(rows)
    assert used == 6 and abs(sum(imp.values()) - 1) < 1e-9
    w = cw.to_weights(imp, 0.3, 0.6)
    # a perfect listing still tops out at ~1.0 and the base is as requested
    top = w.base + w.exact_item + w.brand + w.condition_ok + w.flexibility_scale
    assert abs(top - 1.0) < 0.01
    assert w.threshold == 0.6
    assert w.exact_item > DEFAULT_WEIGHTS.exact_item  # item matters most in the sample


def test_inconsistent_respondent_is_dropped(tmp_path):
    p = tmp_path / "r.csv"
    keys = ["ahp_item_brand", "ahp_item_condition", "ahp_item_openness",
            "ahp_brand_condition", "ahp_brand_openness", "ahp_condition_openness"]
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(keys)
        w.writerow([9, 1/9, 9, 9, 1/9, 9])   # circular preferences
        w.writerow([2, 4, 8, 2, 4, 2])
    imp, used, dropped = cw.importances(cw.read(p))
    assert used == 1 and dropped == 1
