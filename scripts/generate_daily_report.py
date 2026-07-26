#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import db, reports  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the local learning system daily report.")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data/local_learning_system.sqlite"))
    parser.add_argument("--date", default=None)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "docs/system/daily_reports"))
    args = parser.parse_args()

    with db.connect(args.db) as conn:
        db.init_schema(conn)
        result = reports.write_daily_report(conn, Path(args.output_dir), report_date=args.date)
    print(result["paths"]["latest"])


if __name__ == "__main__":
    main()
