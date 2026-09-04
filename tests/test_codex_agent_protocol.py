from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CodexAgentProtocolTests(unittest.TestCase):
    def test_active_protocol_is_complete_and_legacy_runtime_is_absent(self) -> None:
        protocol_path = ROOT / "docs/agent-protocol.md"
        pack_path = ROOT / "docs/agent-protocol/pack.json"
        self.assertTrue(protocol_path.is_file())
        self.assertTrue(pack_path.is_file())

        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        self.assertEqual("codex-agent-protocol", pack["protocol"])
        role_ids = {role["role_id"] for role in pack["roles"]}
        self.assertEqual({"product", "engineering", "qa", "review", "ux"}, role_ids)
        for role_id in role_ids:
            self.assertTrue((ROOT / "docs/agent-protocol/roles" / f"{role_id}.md").is_file())

        self.assertFalse((ROOT / "docs/collaboration.md").exists())
        self.assertFalse((ROOT / "docs/collaboration").exists())

    def test_protocol_declares_historical_boundary(self) -> None:
        protocol = (ROOT / "docs/agent-protocol.md").read_text(encoding="utf-8")
        self.assertIn("historical_material: non_authoritative", protocol)
        self.assertIn("removed_protocol_rule:", protocol)


if __name__ == "__main__":
    unittest.main()
