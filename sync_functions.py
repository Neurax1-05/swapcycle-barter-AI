"""Copy the matching engine into functions/ before deploying.

`firebase deploy` only uploads the functions/ folder, so the engine files
must live there too. The ROOT copies are the single source of truth.

    python sync_functions.py          # copy root -> functions/
    python sync_functions.py --check  # exit 1 if functions/ is stale (CI/tests)

tests/test_functions_in_sync.py runs the --check logic, so a forgotten sync
fails the test suite instead of silently deploying old code.
"""
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "functions"
FILES = [
    "firestore_bridge.py",
    "bgcc_prototype.py",
    "ai_cycle_evaluator.py",
    "ai_preference.py",
    "cycle_arbitration.py",
    "matching_config.py",
]


def stale_files():
    return [
        n for n in FILES
        if not (DEST / n).exists() or not filecmp.cmp(ROOT / n, DEST / n, shallow=False)
    ]


def main(argv):
    if "--check" in argv:
        stale = stale_files()
        if stale:
            print("functions/ is out of date: " + ", ".join(stale))
            print("Run: python sync_functions.py")
            return 1
        print("functions/ is in sync.")
        return 0
    for name in FILES:
        shutil.copy2(ROOT / name, DEST / name)
        print(f"copied {name} -> functions/")
    print("Done. Now: firebase deploy --only functions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
