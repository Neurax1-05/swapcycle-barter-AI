"""Synthetic marketplace data shared by the experiments (reproducible)."""
import random

CATS = ["books", "guitar", "bike", "camera", "phone", "headphones", "laptop",
        "shoes", "jacket", "console", "keyboard", "monitor", "backpack",
        "calculator", "textbook", "speaker", "tablet", "watch", "skateboard",
        "ukulele", "electronics", "other"]
BRANDS = ["", "yamaha", "giant", "sony", "apple", "casio", "logitech"]
CONDS = ["poor", "fair", "good", "like new", "new"]


def marketplace(n, seed):
    """n users, each with one listing and one 'I want' preference."""
    r = random.Random(seed)
    listings, prefs = [], []
    for i in range(n):
        c = r.choice(CATS)
        listings.append({
            "id": f"l{i}", "ownerId": f"u{i}",
            "item": f"{r.choice(['red', 'used', 'acoustic', 'small', ''])} {c}".strip(),
            "category": c if r.random() < 0.85 else r.choice(CATS),
            "brand": r.choice(BRANDS), "condition": r.choice(CONDS),
        })
        w = r.choice(CATS)
        prefs.append({"userId": f"u{i}", "normalized": {
            "desired_item": r.choice([w, w, f"acoustic {w}", ""]),
            "item_category": w if r.random() < 0.85 else r.choice(CATS),
            "keywords": r.sample(CATS, r.randint(0, 2)),
            "acceptable_brands": r.sample(BRANDS, r.randint(0, 2)),
            "minimum_condition": r.choice(["any", "fair", "good", "like new"]),
            "flexibility": round(r.random(), 2),
        }})
    return listings, prefs
