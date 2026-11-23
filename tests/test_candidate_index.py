"""The inverted-index shortcut in build_graph must give the same graph as a
full O(P x L) scan."""
import random

import firestore_bridge as bridge
from matching_config import EdgeWeights

CATS = ["books", "guitar", "bike", "camera", "phone", "headphones", "laptop",
        "shoes", "jacket", "console", "electronics", "other"]
BRANDS = ["", "yamaha", "giant", "sony", "apple"]
CONDS = ["poor", "fair", "good", "like new", "new", ""]


def make(n, seed):
    r = random.Random(seed)
    listings, prefs = [], []
    for i in range(n):
        c = r.choice(CATS)
        listings.append({
            "id": f"l{i}", "ownerId": f"u{i}",
            "item": f"{r.choice(['red', 'used', 'acoustic', ''])} {c}".strip()
                    + r.choice(["", "s"]),
            "category": r.choice(CATS), "brand": r.choice(BRANDS),
            "condition": r.choice(CONDS),
        })
        w = r.choice(CATS)
        prefs.append({"userId": f"u{i}", "normalized": {
            "desired_item": r.choice([w, f"acoustic {w}", "", "zzz"]),
            "item_category": r.choice(CATS + [""]),
            "keywords": r.sample(CATS, r.randint(0, 2)),
            "acceptable_brands": r.sample(BRANDS, r.randint(0, 2)),
            "minimum_condition": r.choice(["any", "good", "new"]),
            "flexibility": r.choice([0.0, 0.3, 0.9, 1.0, "x"]),
        }})
    return listings, prefs


def edges(g):
    return sorted((u, v, d["weight"], d["listingId"]) for u, v, d in g.edges(data=True))


def test_index_equals_full_scan_default_weights(capsys):
    for seed in range(8):
        L, P = make(60, seed)
        a = bridge.build_graph(L, P, use_index=True)
        b = bridge.build_graph(L, P, use_index=False)
        assert edges(a) == edges(b)


def test_index_equals_full_scan_loose_weights(capsys):
    # A low threshold makes the shortcut unsafe; it must fall back to a scan.
    w = EdgeWeights(threshold=0.1)
    for seed in range(4):
        L, P = make(40, seed)
        a = bridge.build_graph(L, P, w, use_index=True)
        b = bridge.build_graph(L, P, w, use_index=False)
        assert edges(a) == edges(b)


def test_edge_cap_keeps_top_k_per_buyer_with_shared_tiebreak(capsys):
    from cycle_arbitration import edge_tiebreak
    L, P = make(80, 3)
    full = bridge.build_graph(L, P)
    capped = bridge.build_graph(L, P, max_edges_per_buyer=5)
    expected = set()
    for u in full.nodes():
        top = sorted(full.out_edges(u, data=True),
                     key=lambda e: (-e[2]["weight"], edge_tiebreak(u, e[1])))[:5]
        expected |= {(u, v) for _, v, _ in top}
    assert {(u, v) for u, v in capped.edges()} == expected
    assert all(capped.out_degree(u) <= 5 for u in capped.nodes())
