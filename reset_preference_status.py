"""
reset_preference_status.py

The original seed script set status: 'matched' on the 4 test preference
docs (p_shanan, p_herta, p_phainon, p_danish) to look pre-matched for a
demo. That status is never produced by the real app or by
firestore_bridge.py, which only picks up 'pending' / 'processed'.

This resets those 4 docs back to 'pending' so firestore_bridge.py will
actually see and process them.
"""

import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

PREF_IDS = ["p_shanan", "p_herta", "p_phainon", "p_danish"]

for pref_id in PREF_IDS:
    ref = db.collection("preferences").document(pref_id)
    doc = ref.get()
    if not doc.exists:
        print(f"⚠ preferences/{pref_id} does not exist — skipped")
        continue
    ref.update({"status": "pending"})
    print(f"✔ preferences/{pref_id} — status reset to 'pending'")

print("\nDone. Run firestore_bridge.py again to pick these up.")
