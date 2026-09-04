from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path

from learning_system import question_visuals


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MISSING_TICK_SLOT_IDS = (
    "M-G7-NUMBER-LINE:number_line_local_scale_construction:challenging_practice:01",
    "M-G7-NUMBER-LINE:number_line_local_scale_construction:guided_formative:02",
)


def _diagnostic_visual() -> dict:
    return {
        "scene_type": "number_line_reference_frame_diagnostic",
        "alt_text": "一条用于检查数轴参照要素的刻度线。",
        "long_description": "图中显示三个连续刻度，用于判断原点、正方向和单位长度是否完整。",
        "scene": {
            "direction_marker_visible": True,
            "origin_tick_id": "tick-zero",
            "origin_label_visible": True,
            "visible_fault_ids": [],
            "ticks": [
                {
                    "id": "tick-negative-one",
                    "scale_index": -1,
                    "position": 15,
                    "value_label": "-1",
                    "point_label": "A",
                },
                {
                    "id": "tick-zero",
                    "scale_index": 0,
                    "position": 45,
                    "value_label": "0",
                    "point_label": "",
                },
                {
                    "id": "tick-positive-one",
                    "scale_index": 1,
                    "position": 75,
                    "value_label": "1",
                    "point_label": "B",
                },
            ],
        },
    }


def _ordinary_number_line() -> dict:
    return {
        "scene_type": "number_line",
        "alt_text": "一条从负一到一的普通数轴。",
        "long_description": "数轴向右为正方向，原点和每个单位刻度都完整显示。",
        "scene": {
            "axis": {
                "min": -1,
                "max": 1,
                "step": 1,
                "origin": 0,
                "direction": "right",
            },
            "ticks": [
                {"value": -1, "label": "-1"},
                {"value": 0, "label": "0"},
                {"value": 1, "label": "1"},
            ],
            "points": [],
        },
    }


def _missing_tick_construction_visual() -> dict:
    return {
        "scene_type": "number_line",
        "alt_text": "一条保留三个已知刻度、等待补出两个缺失刻度的数轴。",
        "long_description": (
            "数轴从负二到二，当前只显示负二、零和二三个已知刻度；"
            "负一和一必须由孩子补出。"
        ),
        "interaction_contract": {
            "operation": "complete_missing_ticks",
            "response_capture": "paper_photo",
            "required_interaction_capabilities": ["construction_interaction"],
            "visible_entity_ids_for_visual": ["tick:-2", "tick:0", "tick:2"],
            "required_child_produced_entity_ids": ["tick:-1", "tick:1"],
            "answer_hidden": True,
        },
        "scene": {
            "axis": {
                "min": -2,
                "max": 2,
                "step": 1,
                "origin": 0,
                "direction": "right",
            },
            "ticks": [
                {"value": -2, "label": "-2"},
                {"value": 0, "label": "0"},
                {"value": 2, "label": "2"},
            ],
            "points": [],
        },
    }


class NumberLineReferenceFrameDiagnosticValidationTests(unittest.TestCase):
    def test_derives_each_visible_fault_from_the_scene(self) -> None:
        cases = [
            ("missing_origin", {"origin_label_visible": False}, None),
            (
                "missing_positive_direction",
                {"direction_marker_visible": False},
                None,
            ),
            (
                "inconsistent_unit_length",
                {},
                [15, 45, 82],
            ),
        ]

        for fault_id, scene_updates, positions in cases:
            with self.subTest(fault_id=fault_id):
                visual = _diagnostic_visual()
                visual["scene"].update(scene_updates)
                visual["scene"]["visible_fault_ids"] = [fault_id]
                if positions is not None:
                    for tick, position in zip(visual["scene"]["ticks"], positions):
                        tick["position"] = position

                self.assertEqual(
                    visual,
                    question_visuals.validate_child_visual(visual),
                )

    def test_requires_exact_canonical_visible_fault_ids(self) -> None:
        visual = _diagnostic_visual()
        visual["scene"].update(
            {
                "direction_marker_visible": False,
                "origin_label_visible": False,
                "visible_fault_ids": ["missing_positive_direction"],
            }
        )
        visual["scene"]["ticks"][2]["position"] = 82

        with self.assertRaisesRegex(ValueError, "visible faults do not match"):
            question_visuals.validate_child_visual(visual)

        visual["scene"]["visible_fault_ids"] = [
            "missing_origin",
            "missing_positive_direction",
            "inconsistent_unit_length",
        ]
        self.assertEqual(visual, question_visuals.validate_child_visual(visual))

        reordered = copy.deepcopy(visual)
        reordered["scene"]["visible_fault_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "visible faults do not match"):
            question_visuals.validate_child_visual(reordered)

    def test_tick_contract_is_closed_and_geometry_is_bounded(self) -> None:
        mutations = {
            "too_few_ticks": lambda scene: scene["ticks"].pop(),
            "duplicate_id": lambda scene: scene["ticks"][2].update(
                {"id": "tick-zero"}
            ),
            "nonconsecutive_scale": lambda scene: scene["ticks"][2].update(
                {"scale_index": 2}
            ),
            "noninteger_position": lambda scene: scene["ticks"][2].update(
                {"position": 75.5}
            ),
            "out_of_bounds_position": lambda scene: scene["ticks"][2].update(
                {"position": 101}
            ),
            "invalid_origin_reference": lambda scene: scene.update(
                {"origin_tick_id": "missing-tick"}
            ),
            "arbitrary_shapes": lambda scene: scene.update({"shapes": []}),
            "raw_svg": lambda scene: scene.update({"raw_svg": "<svg></svg>"}),
            "canvas": lambda scene: scene.update({"canvas": "draw"}),
            "url": lambda scene: scene.update({"url": "https://example.test/x"}),
        }

        for name, mutate in mutations.items():
            with self.subTest(name=name):
                visual = _diagnostic_visual()
                mutate(visual["scene"])
                with self.assertRaises(ValueError):
                    question_visuals.validate_child_visual(visual)

    def test_ordinary_number_line_validation_is_unchanged(self) -> None:
        visual = _ordinary_number_line()
        self.assertEqual(visual, question_visuals.validate_child_visual(visual))

        missing_origin_label = copy.deepcopy(visual)
        missing_origin_label["scene"]["ticks"][1]["label"] = ""
        with self.assertRaisesRegex(ValueError, "origin label is missing"):
            question_visuals.validate_child_visual(missing_origin_label)

        missing_tick = copy.deepcopy(visual)
        missing_tick["scene"]["ticks"].pop()
        with self.assertRaisesRegex(ValueError, "tick budget"):
            question_visuals.validate_child_visual(missing_tick)

    def test_production_inventory_has_an_exact_compatible_diagnostic_profile(self) -> None:
        inventory = json.loads(
            (
                PROJECT_ROOT
                / "data/question_visuals/math_question_visual_inventory_v1.json"
            ).read_text(encoding="utf-8")
        )
        question_visuals.QuestionVisualManifest._validate_inventory(inventory)

        diagnostic_inventory = copy.deepcopy(inventory)
        diagnostic_inventory["allowed_scene_types"].append(
            "number_line_reference_frame_diagnostic"
        )
        diagnostic_inventory["groups"][0]["items"][0]["scene_type"] = (
            "number_line_reference_frame_diagnostic"
        )
        question_visuals.QuestionVisualManifest._validate_inventory(
            diagnostic_inventory
        )

        undeclared = copy.deepcopy(diagnostic_inventory)
        undeclared["allowed_scene_types"].remove(
            "number_line_reference_frame_diagnostic"
        )
        with self.assertRaisesRegex(ValueError, "inventory item is invalid"):
            question_visuals.QuestionVisualManifest._validate_inventory(undeclared)

    def test_complete_missing_ticks_accepts_only_a_sparse_initial_scene_contract(
        self,
    ) -> None:
        visual = _missing_tick_construction_visual()
        contract = visual["interaction_contract"]
        visible_tick_ids = [
            f"tick:{tick['value']}" for tick in visual["scene"]["ticks"]
        ]

        self.assertEqual(
            {
                "operation",
                "response_capture",
                "required_interaction_capabilities",
                "visible_entity_ids_for_visual",
                "required_child_produced_entity_ids",
                "answer_hidden",
            },
            set(contract),
        )
        self.assertEqual(
            contract["visible_entity_ids_for_visual"],
            visible_tick_ids,
        )
        self.assertEqual(
            set(),
            set(contract["visible_entity_ids_for_visual"])
            & set(contract["required_child_produced_entity_ids"]),
        )
        self.assertTrue(contract["answer_hidden"])
        try:
            validated = question_visuals.validate_child_visual(visual)
        except ValueError as exc:
            self.fail(
                "QUESTION_VISUAL_MISSING_TICK_CONTRACT_UNSUPPORTED:slots="
                + ",".join(MISSING_TICK_SLOT_IDS)
                + f":underlying={exc}"
            )
        self.assertEqual(visual, validated)

    def test_complete_missing_ticks_rejects_untrusted_or_precompleted_contracts(
        self,
    ) -> None:
        mutations = {
            "wrong_capture": lambda visual: visual["interaction_contract"].update(
                {"response_capture": "existing_control"}
            ),
            "answer_revealed": lambda visual: visual["interaction_contract"].update(
                {"answer_hidden": False}
            ),
            "visible_required_overlap": lambda visual: visual[
                "interaction_contract"
            ]["required_child_produced_entity_ids"].append("tick:0"),
            "missing_required_tick": lambda visual: visual["interaction_contract"][
                "required_child_produced_entity_ids"
            ].pop(),
            "forged_visible_binding": lambda visual: visual[
                "interaction_contract"
            ]["visible_entity_ids_for_visual"].append("tick:1"),
            "prefilled_point": lambda visual: visual["scene"]["points"].append(
                {"key": "answer", "value": 1, "label": "A"}
            ),
            "precompleted_tick": lambda visual: visual["scene"]["ticks"].append(
                {"value": 1, "label": "1"}
            ),
        }

        for name, mutate in mutations.items():
            with self.subTest(name=name):
                visual = _missing_tick_construction_visual()
                mutate(visual)
                with self.assertRaises(ValueError):
                    question_visuals.validate_child_visual(visual)

    def test_renderer_does_not_precomplete_required_child_ticks(self) -> None:
        visual = _missing_tick_construction_visual()
        completed = subprocess.run(
            [
                "node",
                str(
                    PROJECT_ROOT
                    / "tests/fixtures/"
                    "browser_question_visual_missing_tick_construction_v1.mjs"
                ),
                str(
                    PROJECT_ROOT
                    / "app/local_learning_system/question_visual_renderer.js"
                ),
                json.dumps(visual, ensure_ascii=False, separators=(",", ":")),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(
            {
                "operation": "complete_missing_ticks",
                "rendered_tick_entity_ids": ["tick:-2", "tick:0", "tick:2"],
                "required_child_produced_entity_ids": ["tick:-1", "tick:1"],
                "precompleted_entity_ids": [],
                "answer_hidden": True,
                "construction_interaction_required": True,
            },
            json.loads(completed.stdout),
        )


if __name__ == "__main__":
    unittest.main()
