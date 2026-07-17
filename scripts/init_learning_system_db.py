#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from learning_system import db  # noqa: E402


def main() -> int:
    db_path = ROOT / "data/local_learning_system.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(db_path)
    try:
        db.init_schema(conn)
        db.seed_from_assets(conn, ROOT)
        pilot = {
            "loaded": [],
            "counts": {},
            "staged": None,
            "activated": None,
            "skipped": None,
        }
        conn.execute("savepoint local_v12_pilot_seed")
        try:
            pilot = db.seed_local_v12_pilot_question_banks(conn, ROOT, activate=True, commit=False)
            conn.execute("release savepoint local_v12_pilot_seed")
            conn.commit()
        except Exception as exc:
            conn.execute("rollback to savepoint local_v12_pilot_seed")
            conn.execute("release savepoint local_v12_pilot_seed")
            pilot["skipped"] = {
                "reason": "local_v12_pilot_not_activated",
                "error": f"{type(exc).__name__}: {exc}",
            }
            conn.commit()
        print(f"initialized {db_path}")
        print("v12 pilot banks:")
        print(db.json_dump(pilot))
        print(db.json_dump(db.readiness(conn)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
