from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_system.admin.staged_cleanup import StagedCleanupError, remove_staged_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove explicitly reviewed items from a staged question bank.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        receipt = remove_staged_items(
            root=Path(args.root),
            bank_path=Path(args.bank),
            decision_path=Path(args.decision),
            apply=args.apply,
        )
    except StagedCleanupError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
