#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from learning_system import knowledge_card_generation


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit knowledge-card coverage and next generation batch.")
    parser.add_argument("--project-root", default=PROJECT_ROOT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--module-id", default="")
    parser.add_argument("--node-id", default="")
    args = parser.parse_args()
    project_root = Path(args.project_root)
    if args.node_id:
        payload = knowledge_card_generation.build_generation_packet_for_node(
            args.node_id,
            project_root=project_root,
        )
    else:
        payload = knowledge_card_generation.plan_generation_batch(
            project_root=project_root,
            limit=args.limit,
            module_id=args.module_id or None,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
