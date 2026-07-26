from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from learning_system.admin.expert_ideation import FAMILY_DESIGN_KERNELS, build_expert_design_ideas, write_expert_design_ideas
from learning_system.admin.expert_review import (
    _score_points as _expert_score_points,
    build_candidate_expert_review,
    write_expert_quality_review,
    write_model_expert_board_review,
)
from learning_system.admin.production_loop import (
    AdminProductionError,
    _score_point_sum as _production_score_point_sum,
    build_candidate_check_from_paths,
    build_generation_plan,
    build_generation_plan_batch,
    build_question_requirement_plan,
    decide_loop_next_action,
    decide_staging_from_receipts,
    validate_candidate_against_brief,
    write_production_report,
)
from learning_system.admin.question_generation import (
    _normalize_model_item,
    build_generated_candidate_batch_from_plans,
    build_generated_candidate_from_plan,
    write_generated_candidate_artifact,
)
from learning_system.admin.qa_review import (
    REQUIRED_SEMANTIC_QA_PROFILES,
    _score_point_sum as _qa_score_point_sum,
    build_candidate_qa_contract_check,
    write_candidate_qa_contract_check,
    write_candidate_semantic_qa_review,
)
from learning_system.admin.staging import build_stage_candidate_receipt, write_stage_candidate_receipt
from learning_system.admin.production_workflow import (
    run_batch_production_workflow,
    run_slot_production_workflow,
    write_batch_production_workflow_report,
    write_slot_production_workflow_report,
)
from learning_system import internal_agents, model_router
from learning_system.local_env import load_local_env_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _number_line_brief() -> dict:
    return build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", version="v18")


def _write_temp_number_line_brief(tmp_path: Path) -> Path:
    written = write_expert_design_ideas(_number_line_brief(), root=tmp_path, apply=True)
    return tmp_path / written["design_json_path"]


def _good_candidate(brief: dict) -> dict:
    return {
        "id": "CAND-M-G7-NUMBER-LINE-001",
        "item_version": "draft.production-test",
        "node_id": "M-G7-NUMBER-LINE",
        "question_type": "number_line_coordinate_location",
        "difficulty": "L3",
        "prompt": "数轴上点 A 表示 -2.5。点 B 在 A 的右边 3 个单位，点 C 在原点左边 0.5 个单位。请写出 B、C 表示的数，并按从小到大排序；最后用一句话说明你的依据。",
        "answer_format": "第一行写 B、C 的数并完成排序；第二行写一句依据。",
        "interaction_schema": {
            "schema_version": "2026-07-17.question-interaction.v2",
            "type": "formula_input",
            "title": "写下结果",
            "allow_explanation": True,
            "requires_explanation": True,
            "explanation_label": "一句依据",
            "fields": [],
            "choices": [],
            "formula_label": "B、C 的值和排序",
            "placeholder": "例如：B=...，C=...，...<...<...",
        },
        "standard_answer": "B=0.5，C=-0.5，从小到大是 A<C<B。依据：数轴越往右数越大，向右 3 个单位表示加 3。",
        "expected_answer": "B=0.5，C=-0.5，从小到大是 A<C<B。依据等价即可。",
        "accepted_alternatives": ["写成 -2.5 < -0.5 < 0.5 也可。", "用图示表达同样的位置关系也可。"],
        "rubric": ["结果和位置关系正确给主要分。", "依据等价即可。", "轻微书写省略不作为主扣分。"],
        "solution_steps": [
            "A=-2.5，B 在 A 右边 3 个单位，所以 B=-2.5+3=0.5。",
            "C 在原点左边 0.5 个单位，所以 C=-0.5。",
            "数轴上越往右数越大，所以从小到大是 A、C、B。",
        ],
        "required_evidence": [
            "先读懂每格代表的数量再定位",
            "数到点和点到数的对应准确",
            "能用左右位置解释顺序而不是只报答案",
        ],
        "key_score_points": [
            {"key": "final_conclusion", "points": 4, "evidence": "B=0.5，C=-0.5，A<C<B。"},
            {"key": "core_relation", "points": 3, "evidence": "向右为加，原点左侧为负。"},
            {"key": "process_or_check", "points": 3, "evidence": "能用数轴越往右越大解释排序。"},
        ],
        "target_error_tags": ["modeling_or_reading"],
        "rollback_candidates": ["M-G7-POS-NEG"],
        "estimated_minutes": 4,
        "evidence_goal": "能读懂数轴刻度，把数对应到位置并解释左右顺序。",
        "math_core_signature": "TEST-NUMBER-LINE-DIRECTION-DISTANCE-001",
        "child_surface_design": _child_surface_design(
            difficulty="L3",
            backend_evidence_targets=[
                "先读懂每格代表的数量再定位",
                "数到点和点到数的对应准确",
                "能用左右位置解释顺序而不是只报答案",
            ],
        ),
        "source_type": "ai_original",
        "source": {"type": "ai_original", "usage_mode": "draft_original_generation"},
        "production_lineage": {
            "design_brief_id": brief["report_id"],
            "family_id": "number_line_coordinate_location",
            "evidence_goal": "能读懂数轴刻度，把数对应到位置并解释左右顺序。",
            "generation_rationale": "依据专家 brief 的方向移动和位置排序构思生成，避免只读点或只换数字。",
            "generation_attempt": 1,
        },
        "quality": {
            "review_status": "draft_generated",
            "activation_eligible": False,
            "structure_fingerprint": "TEST-NUMBER-LINE-DIRECTION-DISTANCE-001",
        },
    }


def _child_surface_design(*, difficulty: str, backend_evidence_targets: list[str]) -> dict:
    return {
        "task_focus_count": 1,
        "primary_task": "确定数轴上的位置并完成排序。",
        "child_deliverables": ["写出两个点表示的数并排序", "用一句话说明排序依据"],
        "backend_evidence_targets": list(backend_evidence_targets),
        "student_actions": {
            "primary": "model_or_represent",
            "supporting": ["explain_core_relation"],
        },
        "interaction_requirements": {
            "response_kind": "formula_input",
            "actions": [],
        },
        "writing_burden": {
            "burden_level": "light",
            "estimated_response_lines": 2,
            "why_necessary": "保留数值结果和一条关键关系即可判断断点。",
        },
        "visual_support": {
            "mode": "not_needed",
            "prompt_depends_on_visual": False,
            "asset_ref": "",
            "inline_visual": "",
        },
        "language_surface": {
            "natural_child_facing_chinese": True,
            "respectful_age_appropriate": True,
            "semantic_review_boundary": "requires_independent_semantic_qa",
            "named_characters": [],
            "short_explanation_requests": 1,
        },
        "distractor_design": {"distractors": []},
        "difficulty_alignment": {
            "target_difficulty": difficulty,
            "diagnostic_breakpoint": "能否把方向、距离和数的大小关系连起来。",
            "difficulty_source": "representation_transfer",
        },
    }


def _candidate_for_slot(brief: dict, slot: dict) -> dict:
    candidate = _good_candidate(brief)
    candidate["question_type"] = slot["family_id"]
    candidate["difficulty"] = slot["difficulty"]
    candidate["support_only"] = bool(slot["support_only"])
    candidate["not_for_activation"] = bool(slot["not_for_activation"])
    candidate["exclude_from_coverage"] = bool(slot["exclude_from_coverage"])
    candidate["secondary_node_ids"] = list(slot["secondary_nodes"])
    candidate["required_evidence"] = list(
        dict.fromkeys(
            list(candidate["required_evidence"])
            + list(slot.get("must_include") or [])
            + [slot["evidence_goal"]]
        )
    )
    candidate["production_lineage"]["slot_id"] = slot["slot_id"]
    candidate["production_lineage"]["question_requirement_id"] = slot["question_requirement_id"]
    candidate["production_lineage"]["family_id"] = slot["family_id"]
    candidate["production_lineage"]["evidence_goal"] = slot["evidence_goal"]
    candidate["child_surface_design"] = _child_surface_design(
        difficulty=slot["difficulty"],
        backend_evidence_targets=list(slot.get("must_include") or []) + [slot["evidence_goal"]],
    )
    return candidate


def _wrapped_model_candidate_for_slot(brief: dict, slot: dict) -> dict:
    candidate = _candidate_for_slot(brief, slot)
    candidate["reviewer_evidence"] = {
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "review_rationale": "检测数轴方向、距离和排序关系，不是机械读点。",
    }
    candidate["design_rationale"] = "围绕 slot 的方向移动与位置排序证据生成。"
    candidate["source"] = {
        "type": "ai_original",
        "usage_mode": "draft_original_generation",
        "basis": "generated_from_expert_requirement_slot",
    }
    return {
        "schema_version": "2026-07-23.question-candidate.schema.v1",
        "confidence": 0.91,
        "item": candidate,
        "child_surface_design": copy.deepcopy(candidate["child_surface_design"]),
    }


def _model_expert_pass_output(item_id: str = "CAND-test") -> dict:
    profiles = [
        "frontline_math_teacher",
        "bridge_diagnosis_teacher",
        "stretch_competition_teacher",
        "assessment_expert",
        "source_compliance_reviewer",
    ]
    return {
        "schema_version": "2026-07-23.admin-question-expert-review.schema.v1",
        "overall_status": "pass",
        "confidence": 0.94,
        "profile_reviews": [
            {
                "profile": profile,
                "status": "pass",
                "reasons": ["题目符合当前图谱节点、证据目标和孩子端质量要求。"],
                "blocking_item_ids": [],
                "repair_suggestions": [],
            }
            for profile in profiles
        ],
        "findings": [],
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["qa_review"],
    }


def _model_expert_scope_output(item_id: str = "CAND-test") -> dict:
    output = _model_expert_pass_output(item_id)
    output["overall_status"] = "pass_with_scope"
    output["profile_reviews"][2]["status"] = "pass_with_scope"
    output["profile_reviews"][2]["reasons"] = ["当前难度更接近 L3，需要降低孩子书写负担后再评审。"]
    output["profile_reviews"][2]["repair_suggestions"] = ["删去非必要的第三个认知动作。"]
    output["findings"] = [
        {
            "severity": "P2",
            "profile": "stretch_competition_teacher",
            "item_id": item_id,
            "code": "writing_burden_needs_repair",
            "message": "当前难度更接近 L3，需要降低孩子书写负担后再评审。",
        }
    ]
    output["next_actions"] = ["repair_questions"]
    return output


def _semantic_qa_pass_output() -> dict:
    return {
        "schema_version": "2026-07-24.admin-question-qa-review.schema.v1",
        "overall_status": "pass",
        "confidence": 0.94,
        "profile_reviews": [
            {
                "profile": profile,
                "status": "pass",
                "reasons": ["该 profile 的语义检查通过。"],
                "repair_suggestions": [],
            }
            for profile in REQUIRED_SEMANTIC_QA_PROFILES
        ],
        "hard_blockers": {
            blocker: {"detected": False, "evidence": []}
            for blocker in (
                "mathematical_ambiguity",
                "prompt_answer_conflict",
                "node_or_family_mismatch",
                "age_inappropriate",
                "meaningless_formal_requirement",
            )
        },
        "scope": {
            "support_only": False,
            "not_for_activation": False,
            "exclude_from_coverage": False,
            "reasons": [],
        },
        "findings": [],
        "activation_implication": "does_not_authorize_activation",
        "next_actions": ["staging_decision"],
    }


def _is_semantic_collision_board_payload(payload: dict) -> bool:
    return "semantic collision board" in str(payload.get("instructions") or "").lower()


def _semantic_collision_pass_output(payload: dict) -> dict:
    prompt_text = payload["input"][0]["content"][0]["text"]
    context = json.loads(prompt_text)
    candidate_ids = [
        str(item["item_id"])
        for item in context["candidate_items"]
    ]
    return {
        "decisions": [
            {
                "candidate_item_id": item_id,
                "decision": "PASS",
                "confidence": 0.95,
                "collisions": [],
                "summary": "该题与已入库题及同批候选题的数学结构和诊断任务均不同。",
            }
            for item_id in candidate_ids
        ],
        "batch_summary": "本批候选题没有语义重复。",
    }


def _write_collision_receipt(
    *,
    root: Path,
    candidate_path: Path,
    candidate: dict,
    staged_bank_path: Path,
) -> tuple[Path, str]:
    candidate_sha256 = _json_digest(candidate)
    candidate_file_sha256 = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    binding = {
        "item_id": str(candidate.get("id") or ""),
        "candidate_path": str(candidate_path),
        "candidate_sha256": candidate_sha256,
        "candidate_file_sha256": candidate_file_sha256,
    }
    identity = [
        {
            "item_id": binding["item_id"],
            "candidate_sha256": candidate_sha256,
            "candidate_file_sha256": candidate_file_sha256,
        }
    ]
    if staged_bank_path.exists():
        bank = json.loads(staged_bank_path.read_text(encoding="utf-8"))
        base_items = [item for item in bank.get("items") or [] if isinstance(item, dict)]
        base_bank_sha256 = hashlib.sha256(staged_bank_path.read_bytes()).hexdigest()
    else:
        base_items = []
        base_bank_sha256 = hashlib.sha256(b"").hexdigest()
    report = {
        "schema_version": "2026-07-25.codex-admin.semantic-collision-board.v1",
        "status": "PASS",
        "provider_mode": "live_model",
        "write_applied": True,
        "candidate_bindings": [binding],
        "candidate_set_sha256": _json_digest(identity),
        "candidate_decisions": {
            binding["item_id"]: {
                "candidate_item_id": binding["item_id"],
                "decision": "PASS",
                "confidence": 0.95,
                "collisions": [],
                "summary": "No semantic collision.",
                "decision_source": "live_model_board",
                "candidate_sha256": candidate_sha256,
                "candidate_file_sha256": candidate_file_sha256,
            }
        },
        "base_staged_bank_sha256": base_bank_sha256,
        "base_staged_item_bindings": sorted(
            [
                {
                    "item_id": str(item.get("id") or ""),
                    "item_sha256": _json_digest(item),
                }
                for item in base_items
            ],
            key=lambda value: value["item_id"],
        ),
        "model_evidence": {
            "provider_mode": "live_model",
            "raw_response_sha256": "9" * 64,
            "route": {"structured_json_mode": "json_schema"},
            "transport_attempts": [],
        },
    }
    report["base_staged_snapshot_sha256"] = _json_digest(
        report["base_staged_item_bindings"]
    )
    path = root / f"collision-{binding['item_id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _json_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _passing_model_expert_receipt(
    candidate: dict,
    *,
    source_path: str = "candidate.json",
    question_requirement: dict | None = None,
) -> dict:
    resolved_source = Path(source_path)
    source_file_sha256 = hashlib.sha256(resolved_source.read_bytes()).hexdigest() if resolved_source.exists() else ""
    return {
        "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
        "status": "PASS",
        "overall_status": "pass",
        "provider_mode": "live_model",
        "item_id": str(candidate.get("id") or ""),
        "node_id": str(candidate.get("node_id") or ""),
        "family_id": str(candidate.get("question_type") or ""),
        "slot_id": str((question_requirement or {}).get("slot_id") or (candidate.get("production_lineage") or {}).get("slot_id") or ""),
        "question_requirement_id": str((question_requirement or {}).get("question_requirement_id") or (candidate.get("production_lineage") or {}).get("question_requirement_id") or ""),
        "question_requirement_sha256": _json_digest(question_requirement or {}),
        "candidate_sha256": hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "source_file_sha256": source_file_sha256,
        "source_path": source_path,
        "route": {
            "enabled": True,
            "provider": "openai_compatible",
            "model": "test-model",
            "raw_response_sha256": "model-expert-raw",
            "structured_json_mode": "json_schema",
        },
        "prompt_meta": {
            "contract": "admin_question_expert_review.v1",
            "rendered_prompt_sha256": "model-expert-prompt",
            "response_schema_sha256": "model-expert-schema",
        },
        "profile_reviews": [
            {"profile": profile, "status": "pass"}
            for profile in (
                "frontline_math_teacher",
                "bridge_diagnosis_teacher",
                "stretch_competition_teacher",
                "assessment_expert",
                "source_compliance_reviewer",
            )
        ],
        "model_expert_review_json_path": "data/admin/model_expert_reviews/MODEL-EXPERT-test.json",
        "finding_counts": {},
        "findings": [],
        "activation_implication": "does_not_authorize_activation",
    }


def _qa_contract_receipt(candidate: dict, *, source_path: str) -> dict:
    resolved_source = Path(source_path)
    return {
        "schema_version": "2026-07-24.codex-admin.candidate-qa-contract-check.v1",
        "gate_type": "deterministic_contract_check",
        "status": "PASS",
        "item_id": str(candidate.get("id") or ""),
        "node_id": str(candidate.get("node_id") or ""),
        "family_id": str(candidate.get("question_type") or ""),
        "candidate_sha256": _json_digest(candidate),
        "source_file_sha256": hashlib.sha256(resolved_source.read_bytes()).hexdigest(),
        "source_path": source_path,
        "qa_contract_check_json_path": "data/admin/qa_contract_checks/QA-CONTRACT-test.json",
        "finding_counts": {},
        "findings": [],
    }


def _semantic_qa_pass_receipt(candidate: dict, *, source_path: str, contract_report: dict) -> dict:
    resolved_source = Path(source_path)
    contract_digest = str(contract_report.get("qa_contract_check_json_sha256") or _json_digest(contract_report))
    return {
        "schema_version": "2026-07-23.codex-admin.candidate-qa-review.v1",
        "gate_type": "live_model_semantic_qa",
        "status": "PASS",
        "provider_mode": "live_model",
        "item_id": str(candidate.get("id") or ""),
        "node_id": str(candidate.get("node_id") or ""),
        "family_id": str(candidate.get("question_type") or ""),
        "candidate_sha256": _json_digest(candidate),
        "qa_contract_report_sha256": contract_digest,
        "source_file_sha256": hashlib.sha256(resolved_source.read_bytes()).hexdigest(),
        "source_path": source_path,
        "route": {
            "enabled": True,
            "provider": "openai_compatible",
            "model": "test-review-model",
            "raw_response_sha256": "semantic-raw",
            "structured_json_mode": "json_schema",
        },
        "prompt_meta": {
            "rendered_prompt_sha256": "semantic-prompt",
            "response_schema_sha256": "semantic-schema",
        },
        "profile_reviews": [
            {"profile": profile, "status": "pass"}
            for profile in REQUIRED_SEMANTIC_QA_PROFILES
        ],
        "profile_verdicts": {profile: "pass" for profile in REQUIRED_SEMANTIC_QA_PROFILES},
        "hard_blockers": {
            blocker: {"detected": False, "evidence": []}
            for blocker in (
                "mathematical_ambiguity",
                "prompt_answer_conflict",
                "node_or_family_mismatch",
                "age_inappropriate",
                "meaningless_formal_requirement",
            )
        },
        "scope": {
            "support_only": False,
            "not_for_activation": False,
            "exclude_from_coverage": False,
            "reasons": [],
        },
        "status_normalization": {
            "authority": "deterministic_from_profile_verdicts",
            "model_overall_status_is_advisory": True,
        },
        "qa_json_path": "data/admin/qa/QA-SEMANTIC-test.json",
        "finding_counts": {},
        "findings": [],
    }


def _write_trusted_staging_receipts(
    *,
    artifact_root: Path,
    candidate_path: Path,
    candidate: dict,
    brief: dict,
    slot: dict,
) -> tuple[dict, dict, dict, dict, dict]:
    machine = validate_candidate_against_brief(
        root=PROJECT_ROOT,
        candidate={"item": candidate},
        design_brief=brief,
        required_slot=slot,
    )
    machine = write_production_report(machine, root=artifact_root, apply=True)
    expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
    expert = write_expert_quality_review(expert, root=artifact_root, apply=True)
    model_expert = _passing_model_expert_receipt(
        candidate,
        source_path=str(candidate_path),
        question_requirement=slot,
    )
    model_expert = write_model_expert_board_review(model_expert, root=artifact_root, apply=True)
    qa_contract = build_candidate_qa_contract_check(root=PROJECT_ROOT, candidate_path=candidate_path)
    qa_contract = write_candidate_qa_contract_check(qa_contract, root=artifact_root, apply=True)
    semantic_qa = _semantic_qa_pass_receipt(
        candidate,
        source_path=str(candidate_path),
        contract_report=qa_contract,
    )
    semantic_qa = write_candidate_semantic_qa_review(semantic_qa, root=artifact_root, apply=True)
    return machine, expert, model_expert, qa_contract, semantic_qa


def _handwritten_model_expert_stub(candidate: dict) -> dict:
    return {
        "schema_version": "2026-07-23.codex-admin.model-expert-board-review.v1",
        "status": "PASS",
        "overall_status": "pass",
        "provider_mode": "recorded_model",
        "item_id": str(candidate.get("id") or ""),
        "node_id": str(candidate.get("node_id") or ""),
        "family_id": str(candidate.get("question_type") or ""),
        "finding_counts": {},
        "findings": [],
    }


def _slot_generation_plan(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    brief_path = _write_temp_number_line_brief(tmp_path)
    requirements = build_question_requirement_plan(
        root=PROJECT_ROOT,
        node_id="M-G7-NUMBER-LINE",
        design_brief_path=brief_path,
    )
    req_path = tmp_path / "requirements.json"
    req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
    slot = requirements["question_requirements"][0]
    plan = build_generation_plan(
        root=PROJECT_ROOT,
        node_id="M-G7-NUMBER-LINE",
        family_id=slot["family_id"],
        design_brief_path=brief_path,
        requirement_plan_path=req_path,
        slot_id=slot["slot_id"],
    )
    plan_path = tmp_path / "generation_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan, slot, plan_path, brief_path


class AdminConsoleProductionLoopTests(unittest.TestCase):
    def test_requirement_plan_turns_expert_brief_into_ordered_question_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief_path = _write_temp_number_line_brief(Path(tmp))
            report = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )

        self.assertEqual("REQUIREMENT_PLAN_READY", report["status"])
        self.assertEqual(12, report["requirement_count"])
        first = report["question_requirements"][0]
        self.assertEqual(1, first["slot_order"])
        self.assertEqual("M-G7-NUMBER-LINE", first["node_id"])
        self.assertEqual("number_line_reference_frame", first["family_id"])
        self.assertIn("question_designer_agent_generate_candidate", report["workflow"])
        self.assertIn("loop_regenerate_or_continue", report["workflow"])

    def test_requirement_plan_blocks_when_family_design_kernel_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-OPPOSITE", version="v18")
            written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            brief_path = tmp_path / written_brief["design_json_path"]
            patched_kernels = {key: value for key, value in FAMILY_DESIGN_KERNELS.items() if key != "equivalent_expression_judgement"}
            with mock.patch.dict(FAMILY_DESIGN_KERNELS, patched_kernels, clear=True):
                requirements = build_question_requirement_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-OPPOSITE",
                    design_brief_path=brief_path,
                )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            blocked_slot = next(slot for slot in requirements["question_requirements"] if slot["family_id"] == "equivalent_expression_judgement")
            with mock.patch.dict(FAMILY_DESIGN_KERNELS, patched_kernels, clear=True):
                plan = build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-OPPOSITE",
                    family_id=blocked_slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=req_path,
                    slot_id=blocked_slot["slot_id"],
                )

        self.assertEqual("BLOCKED", requirements["status"])
        self.assertIn("family_missing_design_kernel", {finding["code"] for finding in requirements["findings"]})
        self.assertEqual("BLOCKED", plan["status"])
        self.assertIn("requirement_plan_not_ready", {finding["code"] for finding in plan["findings"]})
        self.assertIn("family_missing_design_kernel", {finding["code"] for finding in plan["findings"]})

    def test_expert_brief_covers_all_blueprint_families_even_when_sample_has_items(self) -> None:
        nodes_and_required_families = {
            "M-PRE-GEO-AREA-VOLUME": "area_volume_formula_structure",
            "M-BRIDGE-WORK-RATE": "work_rate_model",
            "M-G7-GEO-VIEWS": "net_and_view_matching",
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for node_id, required_family in nodes_and_required_families.items():
                brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id=node_id, version="v18")
                written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
                requirements = build_question_requirement_plan(
                    root=PROJECT_ROOT,
                    node_id=node_id,
                    design_brief_path=tmp_path / written_brief["design_json_path"],
                )

                suggestion_families = {
                    suggestion["family_id"]
                    for profile in brief["profile_contributions"].values()
                    for suggestion in profile["suggestions"]
                }
                self.assertIn(required_family, suggestion_families)
                self.assertEqual("REQUIREMENT_PLAN_READY", requirements["status"])
                self.assertIn(required_family, {slot["family_id"] for slot in requirements["question_requirements"]})

    def test_opposite_entry_requirement_does_not_make_absolute_value_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-OPPOSITE", version="v18")
            written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-OPPOSITE",
                design_brief_path=tmp_path / written_brief["design_json_path"],
            )

        slot = next(slot for slot in requirements["question_requirements"] if slot["family_id"] == "opposite_absolute_value_model")
        self.assertEqual("entry_probe", slot["coverage_role"])
        self.assertIn("0的相反数", slot["evidence_goal"])
        self.assertIn("不把绝对值比较命题作为主要得分点", slot["question_direction"])
        self.assertIn("未标 secondary node 时不要把绝对值作为主要得分点", slot["must_not_include"])

    def test_linear_equation_flow_requirement_requires_each_transformation_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-PRE-EQUATION-BASIC", version="v18")
            written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-PRE-EQUATION-BASIC",
                design_brief_path=tmp_path / written_brief["design_json_path"],
            )

        slot = next(slot for slot in requirements["question_requirements"] if slot["family_id"] == "linear_equation_solving_flow")
        self.assertIn("分别说明每个等式变形为什么合法", slot["question_direction"])
        self.assertIn("每一次等式变形都要说明两边同做同一运算", slot["must_include"])
        self.assertIn("只解释第一步合法性而不解释系数化一", slot["must_not_include"])

    def test_requirement_slot_must_include_has_at_least_three_evidence_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-BRIDGE-WORD-PROBLEM-READING", version="v18")
            written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-BRIDGE-WORD-PROBLEM-READING",
                design_brief_path=tmp_path / written_brief["design_json_path"],
            )

        slot = next(slot for slot in requirements["question_requirements"] if slot["family_id"] == "known_unknown_relation_marking")
        self.assertGreaterEqual(len(slot["must_include"]), 3)
        self.assertIn("能标出已知未知", slot["must_include"])

    def test_normalized_candidate_inherits_requirement_must_include_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-BRIDGE-WORD-PROBLEM-READING", version="v18")
            written_brief = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-BRIDGE-WORD-PROBLEM-READING",
                design_brief_path=tmp_path / written_brief["design_json_path"],
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            slot = next(slot for slot in requirements["question_requirements"] if slot["family_id"] == "known_unknown_relation_marking")
            plan = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-BRIDGE-WORD-PROBLEM-READING",
                family_id=slot["family_id"],
                design_brief_path=tmp_path / written_brief["design_json_path"],
                requirement_plan_path=req_path,
                slot_id=slot["slot_id"],
            )
            item = _candidate_for_slot(brief, slot)
            item["required_evidence"] = ["能写出应用题审题流程对应的核心关系"]

            normalized = _normalize_model_item(
                {"item": item},
                plan=plan,
                requirement=slot,
                generation_attempt=1,
                previous_rejection_codes=[],
            )

        self.assertGreaterEqual(len(normalized["required_evidence"]), 3)
        self.assertTrue(set(slot["must_include"]).issubset(set(normalized["required_evidence"])))

    def test_slot_generation_packet_is_one_question_and_contains_slot_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            slot = requirements["question_requirements"][1]
            report = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id=slot["family_id"],
                design_brief_path=brief_path,
                requirement_plan_path=req_path,
                slot_id=slot["slot_id"],
                requested_count=5,
            )

        self.assertEqual("GENERATION_PACKET_READY", report["status"])
        self.assertEqual(1, report["requested_count"])
        self.assertEqual(slot["slot_id"], report["slot_id"])
        self.assertEqual(slot["question_requirement_id"], report["question_requirement_id"])
        self.assertEqual(slot["slot_id"], report["bounded_candidate_packet"]["question_requirement"]["slot_id"])

    def test_production_report_id_includes_slot_to_prevent_plan_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            slot1, slot2 = requirements["question_requirements"][:2]
            plan1 = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id=slot1["family_id"],
                design_brief_path=brief_path,
                requirement_plan_path=req_path,
                slot_id=slot1["slot_id"],
            )
            plan2 = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id=slot2["family_id"],
                design_brief_path=brief_path,
                requirement_plan_path=req_path,
                slot_id=slot2["slot_id"],
            )
            written1 = write_production_report(plan1, root=tmp_path, apply=True)
            written2 = write_production_report(plan2, root=tmp_path, apply=True)

        self.assertNotEqual(written1["production_report_id"], written2["production_report_id"])
        self.assertNotEqual(written1["production_json_path"], written2["production_json_path"])

    def test_generation_plan_batch_writes_one_unique_plan_per_requirement_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")

            batch = build_generation_plan_batch(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                requirement_plan_path=req_path,
                family_id="number_line_reference_frame",
                limit=3,
            )
            written_plans = [write_production_report(plan, root=tmp_path, apply=True) for plan in batch["generation_plans"]]
            batch = {
                **batch,
                "generation_plans": written_plans,
                "generation_plan_paths": [plan["production_json_path"] for plan in written_plans],
            }
            written_batch = write_production_report(batch, root=tmp_path, apply=True)
            plan_paths_exist = [(tmp_path / path).exists() for path in batch["generation_plan_paths"]]

        self.assertEqual("PLAN_BATCH_READY", batch["status"])
        self.assertEqual(3, batch["plan_count"])
        self.assertEqual(3, len(set(batch["generation_plan_paths"])))
        self.assertTrue(all(plan_paths_exist))
        self.assertTrue(written_batch["production_json_path"])

    def test_generate_candidate_blocks_when_question_designer_model_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            _plan, _slot, plan_path, _brief_path = _slot_generation_plan(Path(tmp))

            report = build_generated_candidate_from_plan(
                root=PROJECT_ROOT,
                generation_plan_path=plan_path,
            )

        self.assertEqual("BLOCKED_MODEL_NOT_CONFIGURED", report["status"])
        self.assertEqual("not_configured", report["provider_mode"])
        self.assertEqual(["configure_question_designer_model"], report["next_actions"])
        self.assertFalse(report["candidate"])

    def test_question_candidate_schema_leaves_trusted_identity_to_program(self) -> None:
        contract = internal_agents.load_contract("question_candidate", version_suffix="v1")
        item_schema = contract["response_schema"]["properties"]["item"]
        required = set(item_schema["required"])
        properties = set(item_schema["properties"])
        program_owned = {
            "id",
            "item_version",
            "node_id",
            "question_type",
            "difficulty",
            "source_type",
            "source",
            "production_lineage",
            "quality",
        }

        self.assertFalse(program_owned & required)
        self.assertFalse(program_owned & properties)

    def test_question_candidate_schema_requires_decimal_scores_and_child_surface_contract(self) -> None:
        contract = internal_agents.load_contract("question_candidate", version_suffix="v1")
        schema = contract["response_schema"]
        child_surface = schema["properties"]["child_surface_design"]
        points = schema["properties"]["item"]["properties"]["key_score_points"]["items"]["properties"]["points"]

        self.assertIn("child_surface_design", schema["required"])
        self.assertEqual("number", points["type"])
        self.assertEqual(0.5, points["multipleOf"])
        self.assertEqual(2, child_surface["properties"]["child_deliverables"]["maxItems"])
        self.assertIn("backend_evidence_targets", child_surface["required"])
        self.assertIn("writing_burden", child_surface["required"])
        self.assertIn("respectful_age_appropriate", child_surface["properties"]["language_surface"]["required"])

    def test_decimal_score_points_are_not_truncated_by_any_gate(self) -> None:
        item = {
            "key_score_points": [
                {"points": 1.5},
                {"points": 2},
                {"points": 2},
                {"points": 1.5},
                {"points": 1.5},
                {"points": 1.5},
            ]
        }

        self.assertEqual(10, _production_score_point_sum(item))
        self.assertEqual(10, _expert_score_points(item))
        self.assertEqual(10, _qa_score_point_sum(item))

    def test_single_candidate_without_child_surface_design_fails_closed(self) -> None:
        def fake_call(route, payload, *, schema, **kwargs):
            value = _wrapped_model_candidate_for_slot(brief, slot)
            value.pop("child_surface_design")
            value["item"].pop("child_surface_design")
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(Path(tmp))
            report = build_generated_candidate_from_plan(root=PROJECT_ROOT, generation_plan_path=plan_path)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("missing_child_surface_design", {finding["code"] for finding in report["findings"]})

    def test_single_candidate_rejects_more_than_two_child_deliverables(self) -> None:
        def fake_call(route, payload, *, schema, **kwargs):
            value = _wrapped_model_candidate_for_slot(brief, slot)
            value["child_surface_design"]["child_deliverables"].append("再分析一个错误方法")
            value["item"]["child_surface_design"] = copy.deepcopy(value["child_surface_design"])
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(Path(tmp))
            report = build_generated_candidate_from_plan(root=PROJECT_ROOT, generation_plan_path=plan_path)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("child_surface_too_many_deliverables", {finding["code"] for finding in report["findings"]})

    def test_transient_generation_error_does_not_become_content_regeneration(self) -> None:
        loop = decide_loop_next_action(
            machine_report={
                "status": "BLOCKED_MODEL_ERROR",
                "item_id": "",
                "node_id": "M-G7-NUMBER-LINE",
                "family_id": "number_line_reference_frame",
                "findings": [],
            },
            generation_attempt=1,
            max_attempts=3,
        )

        self.assertEqual("BLOCKED_MODEL_ERROR", loop["status"])
        self.assertEqual("retry_or_repair_model_route", loop["next_action"])
        self.assertEqual({}, loop["regeneration_input"])
        self.assertEqual(
            {
                "provider_retry_required": True,
                "content_regeneration_consumed": False,
            },
            loop["attempt_accounting"],
        )

    def test_generate_candidate_from_slot_calls_model_and_runs_machine_check(self) -> None:
        captured = {}

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            captured["route"] = route
            captured["payload"] = payload
            captured["schema"] = schema
            captured["kwargs"] = kwargs
            return model_router.StructuredJSONResult(
                value=_wrapped_model_candidate_for_slot(brief, slot),
                mode="json_schema",
                raw_response={"output_text": json.dumps(_wrapped_model_candidate_for_slot(brief, slot), ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(tmp_path)

            report = build_generated_candidate_from_plan(
                root=PROJECT_ROOT,
                generation_plan_path=plan_path,
                generation_attempt=1,
            )
            written = write_generated_candidate_artifact(report, root=tmp_path, apply=True)
            candidate_written = (tmp_path / written["candidate_json_path"]).exists()

        self.assertEqual("CANDIDATE_READY_FOR_EXPERT_REVIEW", report["status"])
        self.assertEqual("SELF_CHECKED_PASS", report["machine_report"]["status"])
        self.assertEqual("question_designer_agent", captured["route"].agent_key)
        self.assertEqual("gpt-5.5", captured["route"].model)
        self.assertIs(captured["kwargs"]["include_fallback_schema"], False)
        self.assertEqual("2026-07-23.question-candidate.schema.v1", captured["schema"]["properties"]["schema_version"]["const"])
        self.assertIn(slot["slot_id"], json.dumps(captured["payload"], ensure_ascii=False))
        item = report["candidate"]["item"]
        self.assertTrue(item["id"].startswith("CAND-"))
        self.assertEqual(slot["slot_id"], item["production_lineage"]["slot_id"])
        self.assertEqual(slot["question_requirement_id"], item["production_lineage"]["question_requirement_id"])
        self.assertEqual(["expert_review"], report["next_actions"])
        self.assertTrue(candidate_written)

    def test_candidate_artifact_path_includes_payload_hash_to_preserve_rerun_evidence(self) -> None:
        brief = _number_line_brief()
        candidate_one = _good_candidate(brief)
        candidate_two = copy.deepcopy(candidate_one)
        candidate_two["prompt"] = candidate_two["prompt"] + " 请再补一句检验。"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first = write_generated_candidate_artifact(
                {
                    "candidate": {"item": candidate_one},
                    "candidate_sha256": hashlib.sha256(json.dumps(candidate_one, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
                },
                root=tmp_path,
                apply=True,
            )
            second = write_generated_candidate_artifact(
                {
                    "candidate": {"item": candidate_two},
                    "candidate_sha256": hashlib.sha256(json.dumps(candidate_two, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
                },
                root=tmp_path,
                apply=True,
            )

        self.assertEqual(candidate_one["id"], candidate_two["id"])
        self.assertNotEqual(first["candidate_json_path"], second["candidate_json_path"])

    def test_generated_candidate_keeps_required_evidence_scoped_to_question_requirement(self) -> None:
        captured = {}

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            captured["payload"] = payload
            item = {
                "id": "model-id-will-be-replaced",
                "item_version": "model-version-will-be-replaced",
                "node_id": "M-G7-NUMBER-LINE",
                "question_type": slot["family_id"],
                "difficulty": slot["difficulty"],
                "prompt": "数轴上 A=-4，B=4，C=0。判断 A 和 B 是否互为相反数，并说明 0 的特殊性；再判断“取绝对值一定变大”是否正确。",
                "answer_format": "判断 + 改正 + 一句话解释。",
                "standard_answer": "A 和 B 互为相反数；0 的相反数和绝对值都是 0；“取绝对值一定变大”错误，如 |4|=4，|0|=0。",
                "expected_answer": "结论等价即可。",
                "accepted_alternatives": ["用关于 0 对称解释也可。"],
                "rubric": ["核心概念正确给主分，表达等价即可。"],
                "solution_steps": [
                    "A=-4 与 B=4 到 0 的距离相等、方向相反。",
                    "0 在原点，相反数和绝对值都是 0。",
                    "正数和 0 加绝对值符号后不变，所以“一定变大”错误。",
                ],
                "required_evidence": [
                    "能说出两个数在 0 两侧对称。",
                    "能说明绝对值看离原点多远。",
                    "能用 0 或正数反驳绝对化说法。",
                ],
                "key_score_points": [
                    {"key": "opposite", "points": 3, "evidence": "判断 -4 和 4 互为相反数。"},
                    {"key": "zero_boundary", "points": 2, "evidence": "说明 0 的特殊性。"},
                    {"key": "absolute_value_counterexample", "points": 3, "evidence": "反驳绝对值一定变大。"},
                    {"key": "explanation", "points": 2, "evidence": "用距离或对称解释。"},
                ],
                "target_error_tags": ["concept_boundary"],
                "rollback_candidates": ["M-G7-NUMBER-LINE"],
                "estimated_minutes": 4,
                "evidence_goal": slot["evidence_goal"],
                "math_core_signature": "opposite-absolute-zero-counterexample-trace-test",
                "child_surface_design": _child_surface_design(
                    difficulty=slot["difficulty"],
                    backend_evidence_targets=[
                        "能说出两个数在 0 两侧对称。",
                        "能说明绝对值看离原点多远。",
                        "能用 0 或正数反驳绝对化说法。",
                    ],
                ),
                "source_type": "ai_original",
                "source": {"type": "ai_original", "usage_mode": "draft_original_generation"},
                "production_lineage": {
                    "design_brief_id": plan["design_brief_id"],
                    "family_id": slot["family_id"],
                    "evidence_goal": slot["evidence_goal"],
                    "generation_rationale": "检测相反数、绝对值和 0 的边界。",
                    "generation_attempt": 1,
                },
                "quality": {
                    "review_status": "draft_generated",
                    "activation_eligible": False,
                    "structure_fingerprint": "opposite-absolute-zero-counterexample-trace-test",
                },
            }
            item = _wrapped_model_candidate_for_slot(brief, slot)["item"]
            item["required_evidence"] = ["模型原始返回的一条证据"]
            return model_router.StructuredJSONResult(
                value={
                    "schema_version": "2026-07-23.question-candidate.schema.v1",
                    "confidence": 0.91,
                    "item": item,
                    "child_surface_design": copy.deepcopy(item["child_surface_design"]),
                },
                mode="json_schema",
                raw_response={"output_text": json.dumps(item, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = build_expert_design_ideas(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", version="v18")
            brief_written = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=tmp_path / brief_written["design_json_path"],
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            slot = requirements["question_requirements"][0]
            plan = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id=slot["family_id"],
                design_brief_path=tmp_path / brief_written["design_json_path"],
                requirement_plan_path=req_path,
                slot_id=slot["slot_id"],
            )
            plan_path = tmp_path / "generation_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            report = build_generated_candidate_from_plan(root=PROJECT_ROOT, generation_plan_path=plan_path)

        self.assertEqual("CANDIDATE_READY_FOR_EXPERT_REVIEW", report["status"])
        evidence = report["candidate"]["item"]["required_evidence"]
        self.assertIn(slot["evidence_goal"], evidence)
        sibling_family_evidence = set(plan["bounded_candidate_packet"]["family_plan_entry"]["required_evidence"]) - set(slot["must_include"])
        self.assertFalse(sibling_family_evidence & set(evidence))
        self.assertNotIn("required_evidence_not_aligned", {finding["code"] for finding in report["findings"]})

    def test_run_slot_workflow_stages_candidate_after_all_receipts_pass(self) -> None:
        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            if route.agent_key == "admin_question_expert_review_agent":
                value = _model_expert_pass_output()
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            if route.agent_key == "question_reviewer_agent":
                value = (
                    _semantic_collision_pass_output(payload)
                    if _is_semantic_collision_board_payload(payload)
                    else _semantic_qa_pass_output()
                )
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            return model_router.StructuredJSONResult(
                value=_wrapped_model_candidate_for_slot(brief, slot),
                mode="json_schema",
                raw_response={"output_text": json.dumps(_wrapped_model_candidate_for_slot(brief, slot), ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(tmp_path)
            staged_bank = tmp_path / "staged.json"

            report = run_slot_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_path=plan_path,
                staged_bank_path=staged_bank,
                apply=True,
            )
            written = write_slot_production_workflow_report(report, root=tmp_path, apply=True)
            staged = json.loads(staged_bank.read_text(encoding="utf-8"))
            workflow_json_exists = (tmp_path / written["workflow_json_path"]).exists()
            workflow_markdown_exists = (tmp_path / written["workflow_markdown_path"]).exists()

        self.assertEqual("WORKFLOW_STAGED", report["status"])
        self.assertEqual(1, report["attempt_count"])
        self.assertIsInstance(report["elapsed_seconds"], float)
        self.assertGreaterEqual(report["elapsed_seconds"], 0)
        self.assertEqual(
            [
                "generate_candidate",
                "machine_contract_check",
                "expert_review",
                "model_expert_board_review",
                "qa_contract_check",
                "semantic_qa_review",
                "staging_decision",
                "semantic_collision_review",
                "stage_candidate",
            ],
            [step["step"] for step in report["steps"]],
        )
        self.assertEqual(1, staged["item_count"])
        self.assertFalse(report["activation_allowed"])
        self.assertTrue(workflow_json_exists)
        self.assertTrue(workflow_markdown_exists)

    def test_model_expert_scope_regenerates_with_feedback_before_semantic_qa(self) -> None:
        calls = {"designer": 0, "expert": 0, "semantic": 0}
        second_designer_prompt = {"text": ""}

        def fake_call(route, payload, *, schema, **kwargs):
            if route.agent_key == "admin_question_expert_review_agent":
                calls["expert"] += 1
                value = _model_expert_scope_output() if calls["expert"] == 1 else _model_expert_pass_output()
            elif route.agent_key == "question_reviewer_agent":
                if _is_semantic_collision_board_payload(payload):
                    value = _semantic_collision_pass_output(payload)
                else:
                    calls["semantic"] += 1
                    value = _semantic_qa_pass_output()
            else:
                calls["designer"] += 1
                if calls["designer"] == 2:
                    second_designer_prompt["text"] = json.dumps(payload, ensure_ascii=False)
                value = _wrapped_model_candidate_for_slot(brief, slot)
            return model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            _plan, slot, plan_path, _brief_path = _slot_generation_plan(tmp_path)
            report = run_slot_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_path=plan_path,
                staged_bank_path=tmp_path / "staged.json",
                max_attempts=2,
                apply=True,
            )

        self.assertEqual("WORKFLOW_STAGED", report["status"])
        self.assertEqual(2, report["attempt_count"])
        self.assertEqual(2, calls["designer"])
        self.assertEqual(2, calls["expert"])
        self.assertEqual(1, calls["semantic"])
        self.assertIn("writing_burden_needs_repair", second_designer_prompt["text"])
        self.assertEqual(
            1,
            sum(1 for step in report["steps"] if step["step"] == "semantic_qa_review"),
        )

    def test_run_batch_workflow_stages_multiple_slots_and_writes_summary(self) -> None:
        call_count = {"value": 0}
        generated_slots: list[dict] = []

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            if route.agent_key == "admin_question_expert_review_agent":
                value = _model_expert_pass_output()
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            if route.agent_key == "question_reviewer_agent":
                value = (
                    _semantic_collision_pass_output(payload)
                    if _is_semantic_collision_board_payload(payload)
                    else _semantic_qa_pass_output()
                )
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            call_count["value"] += 1
            slot_payload = generated_slots[call_count["value"] - 1]
            candidate = _wrapped_model_candidate_for_slot(brief, slot_payload)
            candidate["item"]["id"] = f"CAND-BATCH-{call_count['value']}"
            candidate["item"]["quality"]["structure_fingerprint"] = f"batch-structure-{call_count['value']}"
            candidate["item"]["math_core_signature"] = f"batch-structure-{call_count['value']}"
            return model_router.StructuredJSONResult(
                value=candidate,
                mode="json_schema",
                raw_response={"output_text": json.dumps(candidate, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            plan_paths = []
            for slot in requirements["question_requirements"][:2]:
                generated_slots.append(slot)
                plan = build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-NUMBER-LINE",
                    family_id=slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=req_path,
                    slot_id=slot["slot_id"],
                )
                written_plan = write_production_report(plan, root=tmp_path, apply=True)
                plan_paths.append(tmp_path / written_plan["production_json_path"])
            staged_bank = tmp_path / "staged.json"

            batch = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=plan_paths,
                staged_bank_path=staged_bank,
                max_slots=2,
                apply=True,
            )
            written = write_batch_production_workflow_report(batch, root=tmp_path, apply=True)
            staged = json.loads(staged_bank.read_text(encoding="utf-8"))
            batch_json_exists = (tmp_path / written["batch_json_path"]).exists()
            batch_markdown_exists = (tmp_path / written["batch_markdown_path"]).exists()

        self.assertEqual("BATCH_COMPLETED", batch["status"])
        self.assertEqual(2, batch["executed_slot_count"])
        self.assertEqual(2, batch["staged_slot_count"])
        self.assertEqual(0, batch["failed_slot_count"])
        self.assertTrue(all(isinstance(slot["elapsed_seconds"], float) for slot in batch["slot_workflows"]))
        self.assertEqual(2, staged["item_count"])
        self.assertTrue(batch_json_exists)
        self.assertTrue(batch_markdown_exists)
        self.assertFalse(batch["activation_allowed"])

    def test_run_batch_workflow_parallel_single_slots_and_serializes_staged_writes(self) -> None:
        entered_model_call_at: list[float] = []
        barrier = threading.Barrier(2)

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            if route.agent_key == "admin_question_expert_review_agent":
                value = _model_expert_pass_output()
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            if route.agent_key == "question_reviewer_agent":
                value = (
                    _semantic_collision_pass_output(payload)
                    if _is_semantic_collision_board_payload(payload)
                    else _semantic_qa_pass_output()
                )
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            text = payload["input"][0]["content"][0]["text"]
            matching_slot = next(slot for slot in generated_slots if slot["slot_id"] in text)
            entered_model_call_at.append(time.monotonic())
            barrier.wait(timeout=2.0)
            time.sleep(0.15)
            candidate = _wrapped_model_candidate_for_slot(brief, matching_slot)
            unique_suffix = hashlib.sha256(matching_slot["slot_id"].encode("utf-8")).hexdigest()[:10]
            candidate["item"]["quality"]["structure_fingerprint"] = f"parallel-structure-{unique_suffix}"
            candidate["item"]["math_core_signature"] = f"parallel-structure-{unique_suffix}"
            return model_router.StructuredJSONResult(
                value=candidate,
                mode="json_schema",
                raw_response={"output_text": json.dumps(candidate, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            generated_slots = requirements["question_requirements"][:2]
            plan_paths = []
            for slot in generated_slots:
                plan = build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-NUMBER-LINE",
                    family_id=slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=req_path,
                    slot_id=slot["slot_id"],
                )
                written_plan = write_production_report(plan, root=tmp_path, apply=True)
                plan_paths.append(tmp_path / written_plan["production_json_path"])
            staged_bank = tmp_path / "staged.json"

            batch = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=plan_paths,
                staged_bank_path=staged_bank,
                max_slots=2,
                parallel_workers=2,
                apply=True,
            )
            staged = json.loads(staged_bank.read_text(encoding="utf-8"))

        self.assertEqual("BATCH_COMPLETED", batch["status"])
        self.assertTrue(batch["parallel_execution_enabled"])
        self.assertEqual(2, batch["parallel_workers"])
        self.assertEqual(2, len(entered_model_call_at))
        self.assertLess(max(entered_model_call_at) - min(entered_model_call_at), 1.5)
        self.assertEqual(2, staged["item_count"])
        self.assertEqual(2, len({item["id"] for item in staged["items"]}))
        self.assertEqual(2, len({item["quality"]["structure_fingerprint"] for item in staged["items"]}))

    def test_run_batch_workflow_can_generate_two_slots_in_one_model_call(self) -> None:
        captured = {"calls": 0}

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            if route.agent_key == "admin_question_expert_review_agent":
                value = _model_expert_pass_output()
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            if route.agent_key == "question_reviewer_agent":
                value = (
                    _semantic_collision_pass_output(payload)
                    if _is_semantic_collision_board_payload(payload)
                    else _semantic_qa_pass_output()
                )
                return model_router.StructuredJSONResult(
                    value=value,
                    mode="json_schema",
                    raw_response={"output_text": json.dumps(value, ensure_ascii=False)},
                    endpoint="responses",
                )
            captured["calls"] += 1
            candidates = []
            for index, slot_payload in enumerate(generated_slots):
                candidate = _wrapped_model_candidate_for_slot(brief, slot_payload)
                candidate["item"]["quality"]["structure_fingerprint"] = f"grouped-structure-{index}"
                candidate["item"]["math_core_signature"] = f"grouped-structure-{index}"
                candidates.append({
                    "plan_index": index,
                    "confidence": 0.91,
                    "item": candidate["item"],
                    "child_surface_design": candidate["child_surface_design"],
                })
            return model_router.StructuredJSONResult(
                value={
                    "schema_version": "2026-07-23.question-candidate-batch.schema.v1",
                    "confidence": 0.91,
                    "candidates": candidates,
                },
                mode="json_schema",
                raw_response={"output_text": json.dumps(candidates, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            generated_slots = requirements["question_requirements"][:2]
            plan_paths = []
            for slot in generated_slots:
                plan = build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-NUMBER-LINE",
                    family_id=slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=req_path,
                    slot_id=slot["slot_id"],
                )
                written_plan = write_production_report(plan, root=tmp_path, apply=True)
                plan_paths.append(tmp_path / written_plan["production_json_path"])
            staged_bank = tmp_path / "staged.json"

            batch = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=plan_paths,
                staged_bank_path=staged_bank,
                generation_batch_size=2,
                max_slots=2,
                apply=True,
            )
            staged = json.loads(staged_bank.read_text(encoding="utf-8"))
            first_workflow = json.loads((tmp_path / batch["slot_workflows"][0]["workflow_json_path"]).read_text(encoding="utf-8"))

        self.assertEqual(1, captured["calls"])
        self.assertEqual("BATCH_COMPLETED", batch["status"])
        self.assertEqual(2, batch["staged_slot_count"])
        self.assertEqual(2, staged["item_count"])
        self.assertEqual("generate_candidate_batch", first_workflow["steps"][0]["step"])
        self.assertIsInstance(first_workflow["elapsed_seconds"], float)

    def test_batch_generation_rejects_duplicate_structure_fingerprints(self) -> None:
        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True, **kwargs):
            candidates = []
            for index, slot_payload in enumerate(generated_slots):
                candidate = _wrapped_model_candidate_for_slot(brief, slot_payload)
                candidate["item"]["quality"]["structure_fingerprint"] = "same-batch-shell"
                candidate["item"]["math_core_signature"] = "same-batch-shell"
                candidates.append({
                    "plan_index": index,
                    "confidence": 0.91,
                    "item": candidate["item"],
                    "child_surface_design": candidate["child_surface_design"],
                })
            return model_router.StructuredJSONResult(
                value={
                    "schema_version": "2026-07-23.question-candidate-batch.schema.v1",
                    "confidence": 0.91,
                    "candidates": candidates,
                },
                mode="json_schema",
                raw_response={"output_text": json.dumps(candidates, ensure_ascii=False)},
                endpoint="responses",
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AI_QUESTION_MODEL": "gpt-5.5",
            "OPENAI_BASE_URL": "https://api.amux.xyb2b.com/v1",
        }, clear=True), mock.patch.object(model_router, "call_structured_json", side_effect=fake_call):
            tmp_path = Path(tmp)
            brief = _number_line_brief()
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            req_path = tmp_path / "requirements.json"
            req_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            generated_slots = requirements["question_requirements"][:2]
            plan_paths = []
            for slot in generated_slots:
                plan = build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-NUMBER-LINE",
                    family_id=slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=req_path,
                    slot_id=slot["slot_id"],
                )
                written_plan = write_production_report(plan, root=tmp_path, apply=True)
                plan_paths.append(tmp_path / written_plan["production_json_path"])

            report = build_generated_candidate_batch_from_plans(
                root=PROJECT_ROOT,
                generation_plan_paths=plan_paths,
            )

        self.assertEqual("BATCH_CANDIDATES_PARTIAL", report["status"])
        self.assertEqual(0, report["ready_candidate_count"])
        self.assertEqual(2, report["failed_candidate_count"])
        for candidate_report in report["candidate_reports"]:
            self.assertEqual("NEEDS_REGENERATION", candidate_report["status"])
            self.assertIn("batch_duplicate_structure_fingerprint", {finding["code"] for finding in candidate_report["findings"]})

    def test_qa_contract_check_does_not_use_scoring_text_as_semantic_oracle(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["key_score_points"][0]["evidence"] = "同上一题，按模板给分。"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")

            report = build_candidate_qa_contract_check(root=PROJECT_ROOT, candidate_path=candidate_path)

        self.assertEqual("PASS", report["status"])
        self.assertEqual("deterministic_contract_check", report["gate_type"])
        self.assertFalse(report["semantic_authority"])

    def test_run_batch_workflow_honors_max_slots(self) -> None:
        def fake_slot(**kwargs):
            return {
                "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
                "workflow_id": "WF-test",
                "status": "WORKFLOW_STAGED",
                "attempt_count": 1,
                "item_id": "CAND-test",
                "generation_plan_path": str(kwargs["generation_plan_path"]),
                "staging_allowed": True,
                "activation_allowed": False,
                "activation_implication": "does_not_authorize_activation",
                "steps": [],
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "learning_system.admin.production_workflow.run_slot_production_workflow",
            side_effect=fake_slot,
        ) as run_slot:
            tmp_path = Path(tmp)
            plans = [tmp_path / f"plan-{idx}.json" for idx in range(3)]
            for path in plans:
                path.write_text("{}", encoding="utf-8")
            batch = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=plans,
                max_slots=1,
                apply=False,
            )

        self.assertEqual(1, run_slot.call_count)
        self.assertEqual(1, batch["executed_slot_count"])
        self.assertEqual(2, batch["skipped_slot_count"])

    def test_run_batch_workflow_summarizes_blocking_codes_from_failed_slots(self) -> None:
        def fake_slot(**kwargs):
            return {
                "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
                "workflow_id": "WF-failed",
                "status": "LOOP_BLOCKED_MAX_ATTEMPTS",
                "attempt_count": 1,
                "item_id": "CAND-failed",
                "generation_plan_path": str(kwargs["generation_plan_path"]),
                "staging_allowed": False,
                "activation_allowed": False,
                "activation_implication": "does_not_authorize_activation",
                "steps": [
                    {
                        "step": "generate_candidate",
                        "status": "NEEDS_REGENERATION",
                        "item_id": "CAND-failed",
                        "node_id": "M-G7-NUMBER-LINE",
                        "family_id": "number_line_reference_frame",
                        "report_path": "data/admin/production/PROD-failed.json",
                        "finding_counts": {"P1": 1},
                        "blocking_codes": ["accepted_alternatives_answer_only_misalignment"],
                        "blocking_findings": [
                            {
                                "severity": "P1",
                                "profile": "assessment_expert",
                                "code": "accepted_alternatives_answer_only_misalignment",
                                "message": "裸结果不能作为完整作答。",
                            }
                        ],
                        "next_actions": ["loop_decision"],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "learning_system.admin.production_workflow.run_slot_production_workflow",
            side_effect=fake_slot,
        ):
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            batch = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=[plan],
                max_slots=1,
                apply=False,
            )

        self.assertEqual("BATCH_COMPLETED_WITH_FAILURES", batch["status"])
        self.assertEqual(["accepted_alternatives_answer_only_misalignment"], batch["slot_workflows"][0]["blocking_codes"])
        self.assertEqual({"accepted_alternatives_answer_only_misalignment": 1}, batch["blocking_code_counts"])

    def test_run_batch_workflow_id_preserves_same_failure_rerun_evidence(self) -> None:
        def fake_slot(**kwargs):
            return {
                "schema_version": "2026-07-23.codex-admin.slot-production-workflow.v1",
                "workflow_id": "WF-repeatable-failure",
                "status": "LOOP_BLOCKED_MAX_ATTEMPTS",
                "attempt_count": 1,
                "item_id": "",
                "generation_plan_path": str(kwargs["generation_plan_path"]),
                "staging_allowed": False,
                "activation_allowed": False,
                "activation_implication": "does_not_authorize_activation",
                "steps": [
                    {
                        "step": "generate_candidate",
                        "status": "BLOCKED_MODEL_ERROR",
                        "blocking_codes": ["blocked_model_error"],
                        "blocking_findings": [
                            {
                                "severity": "P1",
                                "profile": "admin_production_workflow",
                                "code": "blocked_model_error",
                                "message": "timeout",
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "learning_system.admin.production_workflow.run_slot_production_workflow",
            side_effect=fake_slot,
        ):
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            first = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=[plan],
                max_slots=1,
                apply=False,
            )
            second = run_batch_production_workflow(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                generation_plan_paths=[plan],
                max_slots=1,
                apply=False,
            )

        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(first["blocking_code_counts"], second["blocking_code_counts"])

    def test_generation_plan_is_bounded_by_expert_brief_and_family(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            written = write_expert_design_ideas(brief, root=Path(tmp), apply=True)
            report = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id="number_line_reference_frame",
                design_brief_path=Path(tmp) / written["design_json_path"],
                requested_count=3,
            )

        self.assertEqual("GENERATION_PACKET_READY", report["status"])
        self.assertEqual(3, report["requested_count"])
        packet = report["bounded_candidate_packet"]
        self.assertIn("expert_suggestions", packet)
        self.assertIn("review_must_reject", packet)
        self.assertLessEqual(len(packet["existing_structure_fingerprints"]), 30)
        self.assertEqual("question_designer_agent", report["allowed_next_agent"])

    def test_generation_plan_inherits_explicit_bank_identity_and_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            selected_bank = tmp_path / "selected-staged-bank.json"
            selected_bank.write_text(
                json.dumps(
                    {
                        "question_bank_version": "selected-bank.v1",
                        "items": [
                            {
                                "id": "SELECTED-ITEM",
                                "node_id": "M-G7-NUMBER-LINE",
                                "quality": {"canonical_structure_fingerprint": "SELECTED-FINGERPRINT"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            other_bank = tmp_path / "other-bank.json"
            other_bank.write_text(
                json.dumps({"question_bank_version": "other-bank.v1", "items": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
                bank_path=selected_bank,
            )
            requirement_path = tmp_path / "requirements.json"
            requirement_path.write_text(json.dumps(requirements, ensure_ascii=False), encoding="utf-8")
            slot = requirements["question_requirements"][0]

            plan = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id=slot["family_id"],
                design_brief_path=brief_path,
                requirement_plan_path=requirement_path,
                slot_id=slot["slot_id"],
            )

            with self.assertRaises(AdminProductionError):
                build_generation_plan(
                    root=PROJECT_ROOT,
                    node_id="M-G7-NUMBER-LINE",
                    family_id=slot["family_id"],
                    design_brief_path=brief_path,
                    requirement_plan_path=requirement_path,
                    slot_id=slot["slot_id"],
                    bank_path=other_bank,
                )

        self.assertEqual(str(selected_bank), requirements["question_bank_path"])
        self.assertEqual("selected-bank.v1", plan["question_bank_version"])
        self.assertEqual(str(selected_bank), plan["question_bank_path"])
        self.assertEqual(
            ["SELECTED-FINGERPRINT"],
            plan["bounded_candidate_packet"]["existing_structure_fingerprints"],
        )

    def test_generation_plan_fails_when_family_is_not_in_expert_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief_path = _write_temp_number_line_brief(Path(tmp))
            report = build_generation_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                family_id="integer_structure_arithmetic",
                design_brief_path=brief_path,
            )

        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("P1", report["finding_counts"])
        self.assertIn("family_missing_from_expert_brief", {finding["code"] for finding in report["findings"]})

    def test_legacy_design_brief_without_question_requirements_is_blocked(self) -> None:
        brief = _number_line_brief()
        brief.pop("question_requirements")
        brief.pop("requirement_count")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = tmp_path / "legacy_design_brief.json"
            brief_path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")

            report = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )

        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("design_brief_missing_question_requirements", {finding["code"] for finding in report["findings"]})

    def test_candidate_without_design_brief_lineage_must_regenerate(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["production_lineage"].pop("design_brief_id")

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("missing_lineage_design_brief_id", {finding["code"] for finding in report["findings"]})
        self.assertFalse(report["staging_allowed"])

    def test_candidate_that_self_authorizes_activation_must_regenerate(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["quality"]["activation_eligible"] = True

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("candidate_self_authorizes_activation", {finding["code"] for finding in report["findings"]})

    def test_good_candidate_can_continue_to_expert_review_but_not_stage(self) -> None:
        brief = _number_line_brief()
        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=_good_candidate(brief), design_brief=brief)

        self.assertIn(report["status"], {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"})
        self.assertEqual(["expert_review"], report["next_actions"])
        self.assertFalse(report["staging_allowed"])
        self.assertFalse(any(finding["severity"] in {"P0", "P1"} for finding in report["findings"]))

    def test_process_prompt_rejects_bare_result_as_complete_accepted_alternative(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["prompt"] = candidate["prompt"] + " 请说明理由并检验。"
        candidate["answer_format"] = "结论 + 理由 + 检验"
        candidate["accepted_alternatives"] = ["x=4"]

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("accepted_alternatives_answer_only_misalignment", {finding["code"] for finding in report["findings"]})

    def test_process_prompt_allows_bare_result_when_marked_as_final_form_only(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["prompt"] = candidate["prompt"] + " 请说明理由并检验。"
        candidate["answer_format"] = "结论 + 理由 + 检验"
        candidate["accepted_alternatives"] = ["最终结果可写成 x=4，但完整作答仍需包含理由和检验。"]

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertNotIn("accepted_alternatives_answer_only_misalignment", {finding["code"] for finding in report["findings"]})

    def test_standard_answer_semantics_are_delegated_to_model_expert_review(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["standard_answer"] = "先解得 x=6，但正确检验后应为 x=4。"
        candidate["expected_answer"] = "x=4。"

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertNotIn("contradictory_standard_answer", {finding["code"] for finding in report["findings"]})

    def test_standard_answer_allows_explicitly_rejected_wrong_value(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["standard_answer"] = "正确结果是 x=4。同学给出的 x=6 代入后不成立，所以 x=6 不是答案。"
        candidate["expected_answer"] = "x=4。"

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertNotIn("contradictory_standard_answer", {finding["code"] for finding in report["findings"]})

    def test_standard_answer_allows_equation_terms_before_final_symbol_value(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["standard_answer"] = "4x-2x=10+8，2x=18，x=9。"
        candidate["expected_answer"] = "x=9。"

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertNotIn("contradictory_standard_answer", {finding["code"] for finding in report["findings"]})

    def test_empty_rollback_candidates_is_valid_explicit_no_rollback(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        candidate["rollback_candidates"] = []

        report = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=candidate, design_brief=brief)

        self.assertIn(report["status"], {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"})
        self.assertNotIn("missing_rollback_candidates", {finding["code"] for finding in report["findings"]})

    def test_candidate_expert_review_receipt_can_drive_loop_to_qa(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")

            machine = validate_candidate_against_brief(
                root=PROJECT_ROOT,
                candidate={"item": candidate},
                design_brief=brief,
                required_slot=slot,
            )
            expert = build_candidate_expert_review(
                root=PROJECT_ROOT,
                candidate_path=candidate_path,
            )
            written = write_expert_quality_review(expert, root=tmp_path, apply=True)
            review_written = (tmp_path / written["review_json_path"]).exists()

        decision = decide_loop_next_action(machine_report=machine, expert_report=expert, generation_attempt=1)
        self.assertIn(machine["status"], {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"})
        self.assertEqual("PASS", expert["status"])
        self.assertEqual("LOOP_CONTINUE_TO_QA", decision["status"])
        self.assertEqual("qa_review", decision["next_action"])
        self.assertTrue(review_written)

    def test_candidate_bound_to_slot_can_continue_but_wrong_slot_must_regenerate(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            brief_path = _write_temp_number_line_brief(Path(tmp))
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
        slot = requirements["question_requirements"][0]
        candidate = _candidate_for_slot(brief, slot)

        pass_report = validate_candidate_against_brief(
            root=PROJECT_ROOT,
            candidate=candidate,
            design_brief=brief,
            required_slot=slot,
        )
        self.assertIn(pass_report["status"], {"SELF_CHECKED_PASS", "SELF_CHECKED_PASS_WITH_SCOPE"})

        wrong_slot = dict(slot)
        wrong_slot["slot_id"] = "M-G7-NUMBER-LINE:number_line_reference_frame:99"
        fail_report = validate_candidate_against_brief(
            root=PROJECT_ROOT,
            candidate=candidate,
            design_brief=brief,
            required_slot=wrong_slot,
        )
        self.assertEqual("NEEDS_REGENERATION", fail_report["status"])
        self.assertIn("candidate_slot_mismatch", {finding["code"] for finding in fail_report["findings"]})

    def test_regenerated_candidate_must_carry_rejection_reason_lineage(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        previous_rejection = {
            "findings": [
                {"severity": "P1", "code": "low_value_mechanical_prompt", "message": "过浅。"},
                {"severity": "P2", "code": "wording_can_improve", "message": "表达可优化。"},
            ]
        }

        report = validate_candidate_against_brief(
            root=PROJECT_ROOT,
            candidate=candidate,
            design_brief=brief,
            previous_rejection=previous_rejection,
        )

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("missing_rejection_reason_lineage", {finding["code"] for finding in report["findings"]})

    def test_staging_decision_blocks_expert_p1(self) -> None:
        brief = _number_line_brief()
        machine = validate_candidate_against_brief(root=PROJECT_ROOT, candidate=_good_candidate(brief), design_brief=brief)
        expert = {"status": "NEEDS_FIX", "finding_counts": {"P1": 1}}
        model_expert = _passing_model_expert_receipt(_good_candidate(brief))

        report = decide_staging_from_receipts(root=PROJECT_ROOT, machine_report=machine, expert_report=expert, model_expert_report=model_expert)

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertFalse(report["staging_allowed"])
        self.assertIn("expert_review_blocking_findings", {finding["code"] for finding in report["findings"]})

    def test_staging_decision_requires_model_expert_contract_and_semantic_qa_receipts(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            machine = validate_candidate_against_brief(
                root=PROJECT_ROOT,
                candidate={"item": candidate},
                design_brief=brief,
                required_slot=slot,
            )
            expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            model_expert = _passing_model_expert_receipt(
                candidate,
                source_path=str(candidate_path),
                question_requirement=slot,
            )
            qa_contract = build_candidate_qa_contract_check(root=PROJECT_ROOT, candidate_path=candidate_path)
            qa_contract = write_candidate_qa_contract_check(qa_contract, root=tmp_path, apply=True)
            semantic_qa = _semantic_qa_pass_receipt(candidate, source_path=str(candidate_path), contract_report=qa_contract)
            semantic_qa = write_candidate_semantic_qa_review(semantic_qa, root=tmp_path, apply=True)
            contract_path_exists = (tmp_path / qa_contract["qa_contract_check_json_path"]).exists()
            semantic_path_exists = (tmp_path / semantic_qa["qa_json_path"]).exists()
            missing_model_expert = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )
            missing_qa = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
            )
            ready = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )

        self.assertEqual("NEEDS_REGENERATION", missing_model_expert["status"])
        self.assertIn("missing_model_expert_board_review", {finding["code"] for finding in missing_model_expert["findings"]})
        self.assertEqual("NEEDS_REGENERATION", missing_qa["status"])
        missing_qa_codes = {finding["code"] for finding in missing_qa["findings"]}
        self.assertIn("missing_qa_contract_check", missing_qa_codes)
        self.assertIn("missing_semantic_qa_review", missing_qa_codes)
        self.assertEqual("PASS", qa_contract["status"])
        self.assertEqual("PASS", semantic_qa["status"])
        self.assertEqual("STAGED_READY", ready["status"])
        self.assertTrue(ready["staging_allowed"])
        self.assertEqual(machine["candidate_sha256"], ready["candidate_sha256"])
        self.assertEqual("PASS", ready["review_receipts"]["deterministic_expert_review"]["status"])
        self.assertEqual("PASS", ready["review_receipts"]["model_expert_board_review"]["status"])
        self.assertEqual("PASS", ready["review_receipts"]["guanzhi_qa_review"]["status"])
        self.assertEqual("PASS", ready["qa_contract_check"]["status"])
        self.assertEqual(machine["candidate_sha256"], ready["review_receipts"]["deterministic_expert_review"]["candidate_sha256"])
        self.assertEqual(machine["candidate_sha256"], ready["review_receipts"]["model_expert_board_review"]["candidate_sha256"])
        self.assertEqual(machine["candidate_sha256"], ready["review_receipts"]["guanzhi_qa_review"]["candidate_sha256"])
        self.assertEqual("machine_contract_check", ready["review_receipts"]["machine_check"]["role"])
        self.assertEqual("live_model_semantic_qa_review", ready["review_receipts"]["guanzhi_qa_review"]["role"])
        self.assertEqual(["stage_candidate"], ready["next_actions"])
        self.assertTrue(contract_path_exists)
        self.assertTrue(semantic_path_exists)

    def test_staging_decision_rejects_same_path_overwritten_candidate_payload(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", design_brief_path=brief_path)
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            model_expert = _passing_model_expert_receipt(
                candidate,
                source_path=str(candidate_path),
                question_requirement=slot,
            )
            qa_contract = _qa_contract_receipt(candidate, source_path=str(candidate_path))
            semantic_qa = _semantic_qa_pass_receipt(candidate, source_path=str(candidate_path), contract_report=qa_contract)

            overwritten = copy.deepcopy(candidate)
            overwritten["prompt"] = overwritten["prompt"] + " 请再补一句新的说明。"
            candidate_path.write_text(json.dumps({"item": overwritten}, ensure_ascii=False), encoding="utf-8")
            machine = validate_candidate_against_brief(root=PROJECT_ROOT, candidate={"item": overwritten}, design_brief=brief, required_slot=slot)

            report = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("expert_review_candidate_sha256_mismatch", codes)
        self.assertIn("model_expert_board_review_candidate_sha256_mismatch", codes)
        self.assertIn("qa_contract_check_candidate_sha256_mismatch", codes)
        self.assertIn("semantic_qa_candidate_sha256_mismatch", codes)
        self.assertIn("expert_review_source_file_sha256_mismatch", codes)
        self.assertIn("model_expert_board_review_source_file_sha256_mismatch", codes)
        self.assertIn("qa_contract_check_source_file_sha256_mismatch", codes)
        self.assertIn("semantic_qa_review_source_file_sha256_mismatch", codes)

    def test_staging_decision_rejects_handwritten_model_expert_stub(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", design_brief_path=brief_path)
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            machine = validate_candidate_against_brief(root=PROJECT_ROOT, candidate={"item": candidate}, design_brief=brief, required_slot=slot)
            expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            qa_contract = _qa_contract_receipt(candidate, source_path=str(candidate_path))
            semantic_qa = _semantic_qa_pass_receipt(candidate, source_path=str(candidate_path), contract_report=qa_contract)

            report = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=_handwritten_model_expert_stub(candidate),
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("model_expert_board_review_not_live_model", codes)
        self.assertIn("model_expert_board_review_missing_artifact_lineage", codes)

    def test_staging_decision_rejects_cross_candidate_receipts(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", design_brief_path=brief_path)
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            other = copy.deepcopy(candidate)
            other["id"] = "CAND-CROSS-OTHER"
            other_path = tmp_path / "other.json"
            other_path.write_text(json.dumps({"item": other}, ensure_ascii=False), encoding="utf-8")
            machine = validate_candidate_against_brief(root=PROJECT_ROOT, candidate={"item": candidate}, design_brief=brief, required_slot=slot)
            expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            model_expert = _passing_model_expert_receipt(
                other,
                source_path=str(other_path),
                question_requirement=slot,
            )
            qa_contract = _qa_contract_receipt(candidate, source_path=str(candidate_path))
            semantic_qa = _semantic_qa_pass_receipt(candidate, source_path=str(candidate_path), contract_report=qa_contract)

            report = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("model_expert_board_review_identity_mismatch", codes)
        self.assertIn("review_receipt_source_path_mismatch", codes)

    def test_staging_decision_accepts_generation_report_with_nested_machine_report(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            machine = validate_candidate_against_brief(
                root=PROJECT_ROOT,
                candidate={"item": candidate},
                design_brief=brief,
                required_slot=slot,
            )
            generation_report = {
                "schema_version": "2026-07-23.codex-admin.question-candidate-generation.v1",
                "status": "CANDIDATE_READY_FOR_EXPERT_REVIEW",
                "machine_report": machine,
            }
            expert = build_candidate_expert_review(root=PROJECT_ROOT, candidate_path=candidate_path)
            model_expert = _passing_model_expert_receipt(
                candidate,
                source_path=str(candidate_path),
                question_requirement=slot,
            )
            qa_contract = _qa_contract_receipt(candidate, source_path=str(candidate_path))
            semantic_qa = _semantic_qa_pass_receipt(candidate, source_path=str(candidate_path), contract_report=qa_contract)

            ready = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                machine_report=generation_report,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )

        self.assertEqual("STAGED_READY", ready["status"])
        self.assertEqual(machine["item_id"], ready["item_id"])

    def test_admin_cli_env_loader_does_not_override_or_return_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env.local"
            env_path.write_text(
                "\n".join([
                    "OPENAI_API_KEY=file-secret",
                    "OPENAI_BASE_URL=https://gateway.example/v1",
                    "export AI_QUESTION_MODEL='gpt-5.5'",
                ]),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "existing-secret"}, clear=True):
                loaded = load_local_env_file(env_path)
                self.assertEqual("existing-secret", os.environ["OPENAI_API_KEY"])
                self.assertEqual("https://gateway.example/v1", os.environ["OPENAI_BASE_URL"])
                self.assertEqual("gpt-5.5", os.environ["AI_QUESTION_MODEL"])

        self.assertNotIn("OPENAI_API_KEY", loaded)
        self.assertNotIn("file-secret", loaded)

    def test_stage_candidate_writes_staged_bank_without_activation_authority(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            machine, expert, model_expert, qa_contract, semantic_qa = _write_trusted_staging_receipts(
                artifact_root=tmp_path,
                candidate_path=candidate_path,
                candidate=candidate,
                brief=brief,
                slot=slot,
            )
            staging = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )
            staging_report = write_production_report(staging, root=tmp_path, apply=True)
            staged_bank = tmp_path / "staged.json"
            collision_path, collision_sha256 = _write_collision_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                candidate=candidate,
                staged_bank_path=staged_bank,
            )

            receipt = build_stage_candidate_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                staging_decision_path=tmp_path / staging_report["production_json_path"],
                staged_bank_path=staged_bank,
                semantic_collision_receipt_path=collision_path,
                semantic_collision_receipt_sha256=collision_sha256,
            )
            written = write_stage_candidate_receipt(receipt, root=tmp_path, apply=True)
            persisted = json.loads(staged_bank.read_text(encoding="utf-8"))
            second = build_stage_candidate_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                staging_decision_path=tmp_path / staging_report["production_json_path"],
                staged_bank_path=staged_bank,
                semantic_collision_receipt_path=collision_path,
                semantic_collision_receipt_sha256=collision_sha256,
            )

        self.assertEqual("STAGED_WRITABLE", receipt["status"])
        self.assertEqual("staged_not_active", persisted["status"])
        self.assertEqual(1, persisted["item_count"])
        self.assertEqual("staged", persisted["items"][0]["quality"]["review_status"])
        self.assertFalse(persisted["items"][0]["quality"]["activation_eligible"])
        review_evidence = persisted["items"][0]["quality"]["review_evidence"]
        self.assertEqual("2026-07-23.codex-admin.item-review-evidence.v1", review_evidence["schema_version"])
        self.assertEqual("PASS", review_evidence["receipts"]["deterministic_expert_review"]["status"])
        self.assertEqual("PASS", review_evidence["receipts"]["semantic_qa_review"]["status"])
        self.assertIn("QA-SEMANTIC-", review_evidence["receipts"]["semantic_qa_review"]["report_path"])
        self.assertEqual("live_model", review_evidence["review_logic"]["model_expert_board_review"]["required_provider_mode"])
        self.assertIn("frontline_math_teacher", review_evidence["review_logic"]["deterministic_expert_review"]["profiles"])
        self.assertEqual("deterministic_contract_check", staging["qa_contract_check"]["gate_type"])
        self.assertFalse(written["activation_allowed"])
        self.assertEqual("ALREADY_STAGED", second["status"])

    def test_stage_candidate_blocks_duplicate_structure_fingerprint(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(
                root=PROJECT_ROOT,
                node_id="M-G7-NUMBER-LINE",
                design_brief_path=brief_path,
            )
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            machine, expert, model_expert, qa_contract, semantic_qa = _write_trusted_staging_receipts(
                artifact_root=tmp_path,
                candidate_path=candidate_path,
                candidate=candidate,
                brief=brief,
                slot=slot,
            )
            staging = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                machine_report=machine,
                expert_report=expert,
                model_expert_report=model_expert,
                qa_contract_report=qa_contract,
                semantic_qa_report=semantic_qa,
            )
            staging_report = write_production_report(staging, root=tmp_path, apply=True)
            staged_bank = tmp_path / "staged.json"
            first_collision_path, first_collision_sha256 = _write_collision_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                candidate=candidate,
                staged_bank_path=staged_bank,
            )
            first = build_stage_candidate_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                staging_decision_path=tmp_path / staging_report["production_json_path"],
                staged_bank_path=staged_bank,
                semantic_collision_receipt_path=first_collision_path,
                semantic_collision_receipt_sha256=first_collision_sha256,
            )
            write_stage_candidate_receipt(first, root=tmp_path, apply=True)

            duplicate = copy.deepcopy(candidate)
            duplicate["id"] = "CAND-DUPLICATE"
            duplicate_path = tmp_path / "duplicate.json"
            duplicate_path.write_text(json.dumps({"item": duplicate}, ensure_ascii=False), encoding="utf-8")
            duplicate_machine, duplicate_expert, duplicate_model_expert, duplicate_contract, duplicate_semantic = _write_trusted_staging_receipts(
                artifact_root=tmp_path,
                candidate_path=duplicate_path,
                candidate=duplicate,
                brief=brief,
                slot=slot,
            )
            duplicate_staging = decide_staging_from_receipts(
                root=PROJECT_ROOT,
                artifact_root=tmp_path,
                machine_report=duplicate_machine,
                expert_report=duplicate_expert,
                model_expert_report=duplicate_model_expert,
                qa_contract_report=duplicate_contract,
                semantic_qa_report=duplicate_semantic,
            )
            duplicate_staging_report = write_production_report(duplicate_staging, root=tmp_path, apply=True)
            duplicate_staging_path = tmp_path / duplicate_staging_report["production_json_path"]
            duplicate_collision_path, duplicate_collision_sha256 = _write_collision_receipt(
                root=tmp_path,
                candidate_path=duplicate_path,
                candidate=duplicate,
                staged_bank_path=staged_bank,
            )

            with self.assertRaisesRegex(Exception, "DUPLICATE_STRUCTURE_FINGERPRINT"):
                build_stage_candidate_receipt(
                    root=tmp_path,
                    candidate_path=duplicate_path,
                    staging_decision_path=duplicate_staging_path,
                    staged_bank_path=staged_bank,
                    semantic_collision_receipt_path=duplicate_collision_path,
                    semantic_collision_receipt_sha256=duplicate_collision_sha256,
                )

    def test_stage_candidate_rejects_legacy_staged_ready_without_candidate_sha(self) -> None:
        brief = _number_line_brief()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_path = _write_temp_number_line_brief(tmp_path)
            requirements = build_question_requirement_plan(root=PROJECT_ROOT, node_id="M-G7-NUMBER-LINE", design_brief_path=brief_path)
            slot = requirements["question_requirements"][0]
            candidate = _candidate_for_slot(brief, slot)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps({"item": candidate}, ensure_ascii=False), encoding="utf-8")
            legacy_decision = {
                "schema_version": "2026-07-23.codex-admin.production-staging-decision.v1",
                "status": "STAGED_READY",
                "staging_allowed": True,
                "item_id": candidate["id"],
                "node_id": candidate["node_id"],
                "family_id": candidate["question_type"],
                "machine_report_sha256": "m",
                "expert_report_sha256": "e",
                "model_expert_report_sha256": "me",
                "qa_report_sha256": "q",
            }
            legacy_path = tmp_path / "legacy_decision.json"
            legacy_path.write_text(json.dumps(legacy_decision, ensure_ascii=False), encoding="utf-8")
            collision_path, collision_sha256 = _write_collision_receipt(
                root=tmp_path,
                candidate_path=candidate_path,
                candidate=candidate,
                staged_bank_path=tmp_path / "staged.json",
            )

            with self.assertRaisesRegex(Exception, "MISSING_CANDIDATE_SHA256"):
                build_stage_candidate_receipt(
                    root=tmp_path,
                    candidate_path=candidate_path,
                    staging_decision_path=legacy_path,
                    staged_bank_path=tmp_path / "staged.json",
                    semantic_collision_receipt_path=collision_path,
                    semantic_collision_receipt_sha256=collision_sha256,
                )

    def test_loop_decision_routes_failed_review_back_to_designer_until_budget_exhausts(self) -> None:
        machine = {
            "status": "NEEDS_REGENERATION",
            "item_id": "CAND-1",
            "node_id": "M-G7-NUMBER-LINE",
            "family_id": "number_line_reference_frame",
            "slot_id": "M-G7-NUMBER-LINE:number_line_reference_frame:01",
            "question_requirement_id": "REQ-test",
            "findings": [{"severity": "P1", "code": "low_value_mechanical_prompt"}],
        }

        retry = decide_loop_next_action(machine_report=machine, generation_attempt=1, max_attempts=3)
        self.assertEqual("LOOP_REGENERATE", retry["status"])
        self.assertEqual("regenerate_candidate", retry["next_action"])
        self.assertEqual(["low_value_mechanical_prompt"], retry["regeneration_input"]["previous_rejection_codes"])

        blocked = decide_loop_next_action(machine_report=machine, generation_attempt=3, max_attempts=3)
        self.assertEqual("LOOP_BLOCKED_MAX_ATTEMPTS", blocked["status"])
        self.assertEqual("escalate_human_design_review", blocked["next_action"])

    def test_cli_like_candidate_path_validation_writes_report(self) -> None:
        brief = _number_line_brief()
        candidate = _good_candidate(brief)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brief_result = write_expert_design_ideas(brief, root=tmp_path, apply=True)
            candidate_path = tmp_path / "candidate.json"
            candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

            report = build_candidate_check_from_paths(
                root=PROJECT_ROOT,
                candidate_path=candidate_path,
                design_brief_path=tmp_path / brief_result["design_json_path"],
                required_family_id="number_line_coordinate_location",
            )
            written = write_production_report(report, root=tmp_path, apply=True)

            self.assertTrue((tmp_path / written["production_json_path"]).exists())
            self.assertTrue((tmp_path / written["production_markdown_path"]).exists())

    def test_candidate_family_mismatch_must_regenerate(self) -> None:
        brief = _number_line_brief()
        candidate = copy.deepcopy(_good_candidate(brief))
        candidate["question_type"] = "number_sense_range_benchmark"
        candidate["production_lineage"]["family_id"] = "number_sense_range_benchmark"

        report = validate_candidate_against_brief(
            root=PROJECT_ROOT,
            candidate=candidate,
            design_brief=brief,
            required_family_id="number_line_coordinate_location",
        )

        self.assertEqual("NEEDS_REGENERATION", report["status"])
        self.assertIn("candidate_family_mismatch", {finding["code"] for finding in report["findings"]})


if __name__ == "__main__":
    unittest.main()
