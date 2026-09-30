"""Copy the matching engine into functions/ before deploying.

`firebase deploy` only uploads the functions/ folder, so the engine files
must live there too. Run this after ANY change to the engine files:

    python sync_functions.py
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "functions"
FILES = [
    "firestore_bridge.py",
    "bgcc_prototype.py",
    "ai_cycle_evaluator.py",
    "ai_preference.py",
    "cycle_arbitration.py",
]

for name in FILES:
    shutil.copy2(ROOT / name, DEST / name)
    print(f"copied {name} -> functions/")
print("Done. Now: firebase deploy --only functions")
