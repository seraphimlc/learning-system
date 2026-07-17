import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
    spec = importlib.util.spec_from_file_location("build_math_question_bank_v12_normalization", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _directive(slot: int) -> dict:
    return {
        "slot": slot,
        "repair_scope": "global_duplicate",
        "preserved_role": f"role-{slot}",
        "preserve_or_replace_math_core": "replace_math_core",
        "required_voice_family": "solve_and_interpret",
        "avoided_voice_families": [],
        "exact_target_delta": {
            "dimension": "mathematical_core",
            "from_value": "duplicate",
            "to_value": "distinct",
        },
        "evidence_refs": [f"slot:{slot}"],
    }


class QuestionBankV12GlobalNormalizationTest(unittest.TestCase):
    def test_runtime_filters_only_extra_model_repair_slots_when_canonical_set_is_covered(self):
        module = _load_builder()
        judgment = {"repair_plan": [_directive(2), _directive(16)]}
        reduced = {
            "errors": [
                "global.repair_plan:not_canonical_minimal_set",
                "repair_directive:voice_delta_no_op_or_mismatch",
            ],
            "rejected_slots": [16],
        }

        normalized, audit = module._normalize_global_model_judgment_repair_plan(
            judgment,
            reduced,
        )

        self.assertEqual([16], [item["slot"] for item in normalized["repair_plan"]])
        self.assertEqual([2], audit["removed_slots"])
        self.assertEqual([16], audit["canonical_slots"])

    def test_runtime_does_not_normalize_without_canonical_minimum_mismatch(self):
        module = _load_builder()
        judgment = {"repair_plan": [_directive(2), _directive(16)]}
        reduced = {
            "errors": ["global.voice_family_minimum:missing_exact_repair_plan"],
            "rejected_slots": [16],
        }

        normalized, audit = module._normalize_global_model_judgment_repair_plan(
            judgment,
            reduced,
        )

        self.assertEqual(judgment, normalized)
        self.assertIsNone(audit)

    def test_runtime_synthesizes_missing_duplicate_directives_for_canonical_slots(self):
        module = _load_builder()
        node_entry = {
            "items": [
                {
                    "slot": slot,
                    "slot_role": "standard_model",
                    "review_artifact": {
                        "semantic_evidence": {
                            "instruction_voice_family": "solve_and_interpret",
                        }
                    },
                }
                for slot in (2, 3, 20)
            ]
        }
        judgment = {
            "duplicate_groups": [
                {
                    "group_id": "same-core",
                    "slots": [2, 3, 20],
                    "reason": "The same mathematical core is repeated.",
                    "evidence_refs": ["slot:2", "slot:3", "slot:20"],
                }
            ],
            "repair_plan": [_directive(20)],
        }
        reduced = {
            "errors": ["global.repair_plan:not_canonical_minimal_set"],
            "rejected_slots": [2, 3, 20],
        }

        normalized, audit = module._normalize_global_model_judgment_repair_plan(
            judgment,
            reduced,
            node_entry=node_entry,
        )

        self.assertEqual([2, 3, 20], [item["slot"] for item in normalized["repair_plan"]])
        synthesized = [item for item in normalized["repair_plan"] if item["slot"] in {2, 3}]
        self.assertTrue(all(item["repair_scope"] == "global_duplicate" for item in synthesized))
        self.assertTrue(all(item["exact_target_delta"]["dimension"] == "mathematical_core" for item in synthesized))
        self.assertEqual([2, 3], audit["synthesized_slots"])


if __name__ == "__main__":
    unittest.main()
