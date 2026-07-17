import copy
import json
import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from learning_system import db, graph_runtime, question_bank, model_router

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE = 2
V12_V3_ITEM_SEMANTIC_FIELDS = {
    "version",
    "ux_verdict",
    "natural_self_contained_task",
    "natural_chinese",
    "rendered_notation_readiness",
    "age_dignity",
    "instruction_voice_family",
    "response_moves",
    "unprompted_process_evidence",
    "process_target_disclosed",
    "process_disclosure_evidence",
    "evidence",
    "repair_direction",
}
V12_V3_NODE_SET_OUTPUT_FIELDS = {
    "schema_version",
    "node_id",
    "graph_version",
    "question_bank_version",
    "verdict",
    "rejected_slots",
    "duplicate_groups",
    "distribution_scores",
    "semantic_evidence_version",
    "slot_semantic_evidence",
    "node_ux_verdict",
    "unprompted_slot_results",
    "instruction_voice_distribution",
    "repetitive_instruction_clusters",
    "overloaded_slots",
    "notation_failure_slots",
    "dignity_failure_slots",
    "ux_rejected_slots",
    "confidence",
    "reasons",
    "repair_instructions",
}
V12_V4_FOCAL_NODE_SET_OUTPUT_FIELDS = {
    "schema_version",
    "node_id",
    "graph_version",
    "question_bank_version",
    "semantic_evidence_version",
    "verdict",
    "rejected_slots",
    "duplicate_suspicions",
    "focal_slot_reviews",
    "confidence",
    "reasons",
    "repair_instructions",
}


def _v12_runtime_node_set_shards() -> list[list[int]]:
    shard_size = int(question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE)
    slots = list(range(1, question_bank.QUESTIONS_PER_GRAPH_NODE + 1))
    return [slots[index:index + shard_size] for index in range(0, len(slots), shard_size)]


def _v12_test_execution_policy() -> dict:
    expected_shards = _v12_runtime_node_set_shards()
    return {
        "schema_version": "2026-07-12.v12-live-runner-policy.v3",
        "slot_chunk_concurrency": 4,
        "node_review_concurrency": 1,
        "node_set_review_shard_size": V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE,
        "node_set_review_expected_shards": len(expected_shards),
        "semantic_evidence_policy": question_bank.v12_semantic_evidence_policy(),
    }


def _load_graph():
    return json.loads((PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json").read_text(encoding="utf-8"))


def _graph_version() -> str:
    return graph_runtime.GraphRuntimeService(project_root=PROJECT_ROOT).current_graph_version()


def _reviewer_evidence(item_id: str) -> dict:
    return {
        "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
        "engine_type": "model",
        "provenance_type": "v12_independent_semantic_review",
        "graph_bound": True,
        "incoming_grade_7_ready": True,
        "diagnostic_structure": True,
        "process_evidence_required": True,
        "not_mechanical_drill": True,
        "child_prompt_self_contained": True,
        "specific_expected_answer": True,
        "review_rationale": f"{item_id} is node-local and requires reasoning.",
    }


def _semantic_evidence_for_item(
    item: dict,
    *,
    version: str,
    overrides: dict[str, object] | None = None,
) -> dict:
    slot = int(item.get("slot") or 1)
    requires_unprompted = question_bank.v12_item_requires_unprompted_process_evidence(item)
    intended_voice = str(item.get("intended_instruction_voice_family") or "")
    evidence = {
        "version": version,
        "ux_verdict": "approved",
        "natural_self_contained_task": {
            "verdict": "pass",
            "score": 0.95,
            "reason": "The task is natural, self-contained, and mathematically actionable.",
        },
        "natural_chinese": {
            "verdict": "pass",
            "score": 0.95,
            "reason": "The child-facing Chinese is natural and concise.",
        },
        "rendered_notation_readiness": {
            "verdict": "pass",
            "score": 1.0,
            "reason": "All notation is ready for the rendered child surface.",
            "child_visible_risks": [],
        },
        "age_dignity": {
            "verdict": "pass",
            "score": 0.95,
            "reason": "The task respects an incoming Grade 7 learner.",
        },
        "instruction_voice_family": intended_voice or question_bank.V12_INSTRUCTION_VOICE_FAMILIES[
            (slot - 1) % len(question_bank.V12_INSTRUCTION_VOICE_FAMILIES)
        ],
        "response_moves": ["solve", "explain"],
        "unprompted_process_evidence": {
            "applicability": "required" if requires_unprompted else "not_applicable",
            "verdict": "satisfied" if requires_unprompted else "not_applicable",
            "score": 0.95,
            "reason": "The declared elicitation mode is semantically satisfied.",
        },
        "process_target_disclosed": False,
        "process_disclosure_evidence": {
            "verdict": "not_disclosed",
            "source_field": "none",
            "quote": "",
            "reason": "The child-visible prompt does not disclose a hidden process target.",
        },
        "evidence": "The prompt and expected response provide usable structured semantic evidence.",
        "repair_direction": "No repair is required for this approved fixture.",
    }
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(evidence.get(key), dict):
            evidence[key].update(value)
        else:
            evidence[key] = value
    return evidence


def _reviewer_v3_contract(module) -> dict:
    return json.loads(json.dumps(module._load_json(module.REVIEWER_CONTRACT_PATH)))


def _designer_v3_contract(module) -> dict:
    return json.loads(json.dumps(module._load_json(module.DESIGNER_CONTRACT_PATH)))


def _model_audit_artifact(
    *,
    provider_mode: str = "recorded_model",
    mode: str = "json_schema",
    artifact_role: str = "reviewer",
    agent_key: str = "",
    phase: str = "",
    model_name: str = "gpt-5.5",
    contract_key: str = "",
    contract_version: str = "",
    prompt_version_id: str = "",
    response_schema_version: str = "2026-07-12.math-qb-v12.test.schema.v1",
) -> dict:
    artifact = {
        "agent_key": agent_key,
        "phase": phase,
        "model_provider": "gpt",
        "model_name": model_name,
        "model_alias": model_name,
        "provider_mode": provider_mode,
        "artifact_role": artifact_role,
        "structured_json_mode": mode,
        "prompt_template_sha256": "prompt-template-sha256-test",
        "rendered_prompt_sha256": "rendered-prompt-sha256-test",
        "response_schema_version": response_schema_version,
        "response_schema_sha256": "schema-sha256-test",
        "batch_raw_response_sha256": "raw-response-sha256-test",
        "contract_key": contract_key,
        "contract_version": contract_version,
    }
    if prompt_version_id:
        artifact["prompt_version_id"] = prompt_version_id
    return artifact


def _v12_test_voice_family_for_role(role: str) -> str:
    policy = question_bank.v12_role_voice_policy(role)
    return str((policy.get("preferred") or policy.get("allowed") or question_bank.V12_INSTRUCTION_VOICE_FAMILIES)[0])


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _core_item(
    node: dict,
    slot: int,
    *,
    core: str | None = None,
    slot_role: str | None = None,
    provider_mode: str = "recorded_model",
) -> dict:
    core = core or f"{node['id']}-core-{slot:02d}"
    role = slot_role or question_bank.v12_slot_role_for_node(node, slot)
    item_id = f"QB12-{node['id']}-{slot:02d}".replace("--", "-")
    unprompted_process = (
        question_bank.v12_is_process_node(node)
        and slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS
    )
    prompt = (
        f"{node['name']}第{slot}题：给出表达式 {slot}+({slot}+2)，求它的值。"
        if unprompted_process
        else (
            f"{node['name']}第{slot}题：给出表达式 {slot}+({slot}+2)，"
            f"请说明它表示的关系，算出结果，并用代入或反例检查。"
        )
    )
    likely_error_tags = (
        (node.get("error_diagnosis") if isinstance(node.get("error_diagnosis"), dict) else {}).get("likely_error_tags")
        or ["general"]
    )
    item = {
        "id": item_id,
        "slot": slot,
        "slot_role": role,
        "node_id": node["id"],
        "kind": role,
        "question_type": f"{role}：{node['name']}",
        "variant_level": "L2" if slot <= 14 else "L3",
        "prompt": prompt,
        "interaction_schema": {
            "schema_version": question_bank.QUESTION_INTERACTION_SCHEMA_VERSION,
            "type": "short_text",
            "title": "写出关系、结果和检验",
            "allow_explanation": True,
            "explanation_label": "补充说明",
            "fields": [],
            "choices": [],
            "formula_label": "",
            "placeholder": "说明数量关系，写出计算结果，并给出检验。",
        },
        "answer_format": "关系说明 + 计算 + 检验",
        "expected_answer": f"它表示 {slot} 与 {slot + 2} 的和，结果是 {slot + slot + 2}；可代入检验。",
        "accepted_alternatives": [f"{slot}+({slot}+2)={slot + slot + 2}"],
        "solution_steps": [
            "先读出括号内外的两个量。",
            "说明加法关系。",
            "计算并用代入或反例检查。",
        ],
        "target_error_tags": [str(likely_error_tags[0])],
        "rollback_candidates": list(node.get("prerequisites") or [])[:2],
        "rollback_candidate_relations": [
            {"node_id": candidate, "relation": "prerequisite_chain"}
            for candidate in list(node.get("prerequisites") or [])[:2]
        ],
        "problem_family_id": f"PF-V12-{node['id']}-{slot:02d}",
        "core_stem_id": f"CS-V12-{core}",
        "math_core_signature": core,
        "evidence_goal": role,
        "elicitation_mode": (
            question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
            if unprompted_process
            else "direct_prompted_evidence"
        ),
        "child_surface_design": json.loads(json.dumps(question_bank.V12_CHILD_SURFACE_DESIGN)),
        "intended_instruction_voice_family": _v12_test_voice_family_for_role(role),
        "difficulty_vector": {
            "level": "L2",
            "concept_demand": 2,
            "reasoning_steps": 3,
            "calculation_load": 2,
            "representation_demand": 2 if role in {"representation_translation", "multi_representation"} else 1,
            "transfer_distance": 2 if role in {"near_transfer", "integrated_transfer"} else 1,
        },
        "requires_reasoning": True,
        "node_local_mainline": slot <= 14,
        "controlled_stretch": role == "controlled_stretch",
        "estimated_minutes": 5,
        "designer_artifact": {
            "designer_run_id": f"DESIGN-{item_id}",
            "prompt_version_id": question_bank.V12_DESIGNER_PROMPT_VERSION_ID,
            "design_rationale": f"Targets {role} for {node['name']}.",
            "pipeline_stage": "initial_generation",
            "stage_attempt": 1,
            **_model_audit_artifact(
                provider_mode=provider_mode,
                artifact_role="designer",
                agent_key=question_bank.QUESTION_DESIGNER_AGENT_KEY,
                phase="question_candidate",
                contract_key="math_question_bank_v12_designer_batch",
                contract_version=question_bank.V12_DESIGNER_CONTRACT_VERSION,
                response_schema_version=question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
            ),
        },
    }
    item["review_artifact"] = {
        "reviewer_run_id": f"REVIEW-{item_id}",
        "prompt_version_id": question_bank.V12_REVIEWER_PROMPT_VERSION_ID,
        "verdict": "approved",
        "scores": {
            "node_alignment": 0.95,
            "mathematical_correctness": 0.95,
            "reasoning_signal": 0.9,
            "non_mechanical": 0.9,
            "answer_alignment": 0.9,
        },
        "reasons": ["node-local reasoning item", "answer and steps are checkable"],
        "reviewer_evidence": _reviewer_evidence(item_id),
        "confidence": 0.95,
        "semantic_evidence_version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence": _semantic_evidence_for_item(
            item,
            version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        ),
        "pipeline_stage": "initial_generation",
        "stage_attempt": 1,
        **_model_audit_artifact(
            provider_mode=provider_mode,
            artifact_role="reviewer",
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            phase="question_review",
            contract_key="math_question_bank_v12_reviewer_batch",
            contract_version=question_bank.V12_REVIEWER_CONTRACT_VERSION,
            response_schema_version=question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
        ),
    }
    item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
    item["review_artifact"]["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(
        item,
        item["review_artifact"],
    )
    return item


def _refresh_v3_item_review_commitment(item: dict, *, reset_semantic_evidence: bool = False) -> None:
    review = item.get("review_artifact") if isinstance(item.get("review_artifact"), dict) else {}
    if reset_semantic_evidence:
        review["semantic_evidence_version"] = question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION
        review["semantic_evidence"] = _semantic_evidence_for_item(
            item,
            version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        )
    review["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
    review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)


def _manifest(
    node_ids=("M-G7-POS-NEG",),
    *,
    duplicate_core: bool = False,
    missing_review: bool = False,
    provider_mode: str = "recorded_model",
    status: str = "draft",
) -> dict:
    graph = _load_graph()
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    node_entries = []
    for node_id in node_ids:
        node = nodes_by_id[node_id]
        items = []
        for slot in range(1, 21):
            core = "shared-cross-node-core" if duplicate_core and slot <= 3 else None
            item = _core_item(node, slot, core=core, provider_mode=provider_mode)
            if missing_review and slot == 1:
                item["review_artifact"] = {
                    "verdict": "approved",
                    "candidate_sha256": question_bank.v12_external_candidate_sha256(item),
                }
            items.append(item)
        node_entry = {"node_id": node_id, "node_name": node["name"], "items": items}
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode=provider_mode)
        node_entries.append(node_entry)
    return {
        "schema_version": "2026-07-12.math-question-bank.v12.asset.v1",
        "manifest_id": "math_question_bank_v12_test_fixture",
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "graph_version": _graph_version(),
        "source_policy": "generated_from_project_graph_no_external_private_bank",
        "status": status,
        "execution_policy": _v12_test_execution_policy(),
        "nodes": node_entries,
    }


def _manifest_with_semantic_identity_slugs(*, provider_mode: str = "live_model") -> dict:
    manifest = _manifest(provider_mode=provider_mode, status="draft_live_model")
    for node_entry in manifest["nodes"]:
        for item in node_entry["items"]:
            slot = int(item["slot"])
            item["problem_family_id"] = f"concept_boundary_slug_{slot:02d}"
            item["core_stem_id"] = f"compare_method_slug_{slot:02d}"
            item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
            item["review_artifact"]["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(
                item,
                item["review_artifact"],
            )
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode=provider_mode)
    return manifest


def _node_review_artifact(
    node_entry: dict,
    *,
    provider_mode: str = "recorded_model",
    duplicate_groups: list[dict] | None = None,
    rejected_slots: set[int] | None = None,
) -> dict:
    node_candidate_sha256 = question_bank.v12_node_candidate_sha256(node_entry)
    constituent_reviews = []
    duplicate_groups = json.loads(json.dumps(duplicate_groups or []))
    rejected_slots = set(rejected_slots or set())
    duplicate_group_emitted = False
    for reviewed_slots in _v12_runtime_node_set_shards():
        start = reviewed_slots[0]
        shard_rejected_slots = sorted(rejected_slots.intersection(reviewed_slots))
        output = _node_set_review_response(
            node_entry,
            _graph_version(),
            reviewed_slots=reviewed_slots,
            rejected_slots=shard_rejected_slots,
        )
        if duplicate_groups and shard_rejected_slots and not duplicate_group_emitted:
            output["duplicate_groups"] = json.loads(json.dumps(duplicate_groups))
            duplicate_group_emitted = True
        output_sha = _sha256_json(output)
        constituent = {
            "shard_id": f"slots-{reviewed_slots[0]:02d}-{reviewed_slots[-1]:02d}",
            "reviewed_slots": reviewed_slots,
            "review_output": output,
            "review_output_sha256": output_sha,
            "node_candidate_sha256": node_candidate_sha256,
            "pipeline_stage": "node_set_review",
            "stage_attempt": 1,
            **_model_audit_artifact(
                provider_mode=provider_mode,
                artifact_role="node_set_review_shard",
                agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                phase="node_set_review",
                model_name="gpt-5.4",
                contract_key="math_question_bank_v12_node_set_focal_review",
                contract_version=question_bank.V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION,
                prompt_version_id=question_bank.V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID,
                response_schema_version=question_bank.V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION,
            ),
            "artifact_role": "node_set_focal_review_shard",
            "review_phase": "focal_shard",
            "semantic_evidence_version": question_bank.V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        }
        constituent["semantic_evidence_sha256"] = question_bank.v12_node_set_constituent_semantic_evidence_sha256(
            node_entry,
            constituent,
        )
        constituent_reviews.append(constituent)
    global_output = _node_set_global_finalizer_output(
        node_entry,
        constituent_reviews,
        rejected_slots=sorted(rejected_slots),
        duplicate_groups=duplicate_groups,
    )
    global_finalizer = _node_set_global_finalizer_artifact(
        node_entry,
        constituent_reviews,
        global_output,
        provider_mode=provider_mode,
    )
    recomputed = question_bank._v12_recompute_node_set_review_from_constituents(
        node_entry,
        constituent_reviews,
        global_finalizer,
    )
    aggregate = question_bank.v12_node_set_review_aggregate_payload(
        node_entry=node_entry,
        shard_reviews=constituent_reviews,
        global_finalizer_artifact=global_finalizer,
        reduced=recomputed,
    )
    artifact = {
        "node_reviewer_run_id": f"NODE-REVIEW-{node_entry.get('node_id')}",
        "verdict": recomputed["verdict"],
        "distribution_scores": recomputed["distribution_scores"],
        "duplicate_groups": recomputed["duplicate_groups"],
        "reasons": recomputed["reasons"],
        "repair_instructions": recomputed["repair_instructions"],
        "canonical_repair_plan": recomputed["repair_instructions"],
        "rejected_slots": recomputed["rejected_slots"],
        "confidence": recomputed["confidence"],
        "node_candidate_sha256": node_candidate_sha256,
        "constituent_reviews": constituent_reviews,
        "global_finalizer": global_finalizer,
        "global_review_output_sha256": global_finalizer["global_review_output_sha256"],
        "aggregation": aggregate["aggregation"],
        "execution_policy": {
            "node_review_concurrency": 1,
            "node_set_review_shard_size": V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE,
            "node_set_review_expected_shards": len(_v12_runtime_node_set_shards()),
            "global_finalizer_concurrency": 1,
        },
        "pipeline_stage": "node_set_global_finalizer",
        "stage_attempt": 1,
        **_model_audit_artifact(
            provider_mode=provider_mode,
            artifact_role="node_set_review",
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            phase="node_global_finalizer",
            model_name="gpt-5.4",
            contract_key="math_question_bank_v12_node_set_global_finalizer",
            contract_version=question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
            prompt_version_id=question_bank.V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
            response_schema_version=question_bank.V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        ),
        "review_phase": "global_finalizer_reduced",
        "semantic_evidence_version": question_bank.V12_NODE_SET_AGGREGATE_SEMANTIC_EVIDENCE_VERSION,
        "semantic_evidence_sha256": aggregate["semantic_evidence_sha256"],
        "semantic_evidence_coverage": aggregate["semantic_evidence_coverage"],
        **{
            key: value
            for key, value in recomputed.items()
            if key not in {
                "verdict",
                "distribution_scores",
                "duplicate_groups",
                "reasons",
                "repair_instructions",
                "confidence",
                "rejected_slots",
            }
        },
    }
    return artifact


def _refresh_v3_node_set_review(
    node_entry: dict,
    *,
    overrides: dict[str, float] | None = None,
    omitted: set[str] | None = None,
) -> None:
    artifact = _node_review_artifact(node_entry, provider_mode="live_model")
    omitted = omitted or set()
    if overrides or omitted:
        constituent_reviews = artifact["constituent_reviews"]
        global_output = json.loads(json.dumps(artifact["global_finalizer"]["global_review_output"], ensure_ascii=False))
        scores = global_output.setdefault("distribution_scores", {})
        for key in omitted:
            scores.pop(key, None)
        scores.update(overrides or {})
        global_finalizer = _node_set_global_finalizer_artifact(
            node_entry,
            constituent_reviews,
            global_output,
            provider_mode="live_model",
        )
        reduced = question_bank._v12_recompute_node_set_review_from_constituents(
            node_entry,
            constituent_reviews,
            global_finalizer,
        )
        aggregate = question_bank.v12_node_set_review_aggregate_payload(
            node_entry=node_entry,
            shard_reviews=constituent_reviews,
            global_finalizer_artifact=global_finalizer,
            reduced=reduced,
        )
        artifact.update({
            "global_finalizer": global_finalizer,
            "global_review_output_sha256": global_finalizer["global_review_output_sha256"],
            "aggregation": aggregate["aggregation"],
            "semantic_evidence_sha256": aggregate["semantic_evidence_sha256"],
            "semantic_evidence_coverage": aggregate["semantic_evidence_coverage"],
            **reduced,
            "canonical_repair_plan": reduced["repair_instructions"],
        })
    node_entry["node_review_artifact"] = artifact


def _recompute_v3_node_set_review(node_entry: dict) -> None:
    artifact = node_entry["node_review_artifact"]
    for review in artifact["constituent_reviews"]:
        review["review_output_sha256"] = _sha256_json(review["review_output"])
        review["semantic_evidence_sha256"] = question_bank.v12_node_set_constituent_semantic_evidence_sha256(
            node_entry,
            review,
        )
    global_output = (
        artifact.get("global_finalizer", {}).get("global_review_output")
        if isinstance(artifact.get("global_finalizer"), dict)
        else {}
    )
    global_finalizer = _node_set_global_finalizer_artifact(
        node_entry,
        artifact["constituent_reviews"],
        global_output,
        provider_mode="live_model",
    )
    recomputed = question_bank._v12_recompute_node_set_review_from_constituents(
        node_entry,
        artifact["constituent_reviews"],
        global_finalizer,
    )
    aggregate = question_bank.v12_node_set_review_aggregate_payload(
        node_entry=node_entry,
        shard_reviews=artifact["constituent_reviews"],
        global_finalizer_artifact=global_finalizer,
        reduced=recomputed,
    )
    artifact.update({
        "contract_version": question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
        "prompt_version_id": question_bank.V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
        "response_schema_version": question_bank.V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "global_finalizer": global_finalizer,
        "global_review_output_sha256": global_finalizer["global_review_output_sha256"],
        "aggregation": aggregate["aggregation"],
        "semantic_evidence_sha256": aggregate["semantic_evidence_sha256"],
        "semantic_evidence_coverage": aggregate["semantic_evidence_coverage"],
        **recomputed,
        "canonical_repair_plan": recomputed["repair_instructions"],
    })


def _v3_process_manifest() -> tuple[dict, dict]:
    graph = _load_graph()
    manifest = _manifest(
        node_ids=("M-BRIDGE-SOLUTION-HABIT",),
        provider_mode="live_model",
        status="draft_live_model",
    )
    node_entry = manifest["nodes"][0]
    node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
    for item in node_entry["items"]:
        slot = int(item["slot"])
        item["child_surface_design"] = json.loads(json.dumps(question_bank.V12_CHILD_SURFACE_DESIGN))
        if slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS:
            item["elicitation_mode"] = question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
        item["designer_artifact"].update({
            "contract_version": question_bank.V12_DESIGNER_CONTRACT_VERSION,
            "prompt_version_id": question_bank.V12_DESIGNER_PROMPT_VERSION_ID,
            "response_schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
        })
        review = item["review_artifact"]
        review.update({
            "contract_version": question_bank.V12_REVIEWER_CONTRACT_VERSION,
            "prompt_version_id": question_bank.V12_REVIEWER_PROMPT_VERSION_ID,
            "response_schema_version": question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        })
        review["semantic_evidence"] = _semantic_evidence_for_item(
            item,
            version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        )
        item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
        review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)
    node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")
    _refresh_v3_node_set_review(node_entry)
    return manifest, node


def _pilot_eq_denom_manifest() -> dict:
    return json.loads(
        (PROJECT_ROOT / "data/question_banks/math/math_question_bank_v12_pilot_eq_denom.json").read_text(
            encoding="utf-8"
        )
    )


def _runner_receipt_for_manifest(manifest: dict) -> dict:
    module = _load_v12_build_module()
    enriched = json.loads(json.dumps(manifest, ensure_ascii=False))
    graph = _load_graph()
    nodes = [node for node in enriched.get("nodes") or [] if isinstance(node, dict)]
    for index, node_entry in enumerate(nodes):
        node_id = str(node_entry.get("node_id") or "")
        generation = module._generation_cross_node_summary_bundle(
            focal_node_id=node_id,
            completed_nodes=nodes[:index],
            graph=graph,
        )["context"]
        full_audit = module._full_bank_cross_node_summary_bundle(
            focal_node_id=node_id,
            completed_nodes=nodes,
            graph=graph,
        )["context"]
        node_entry["_runner_summary_contexts"] = {
            "generation": generation,
            "full_bank_audit": full_audit,
        }
        node_entry["_runner_model_budget_commitment"] = {
            "schema_version": question_bank.V12_MODEL_BUDGET_SCHEMA_VERSION,
            "node_id": node_id,
            "semantic_calls": 1,
            "provider_attempts": 1,
            "max_semantic_calls": 512,
            "max_provider_attempts": 1536,
            "counter_chain_head_sha256": _sha256_json({"node_id": node_id, "kind": "counter"}),
            "integrity_sha256": _sha256_json({"node_id": node_id, "kind": "budget"}),
        }
    return module._runner_receipt_for_manifest(enriched)


def _reviewer_batch_response(module, node_id: str, graph_version: str, items: list[dict], *, reject_slots: set[int] | None = None) -> dict:
    reject_slots = reject_slots or set()
    item_reviews = []
    for item in items:
        semantic_item = json.loads(json.dumps(item, ensure_ascii=False))
        structured = semantic_item.get("structured_metadata") if isinstance(semantic_item.get("structured_metadata"), dict) else {}
        child_visible = semantic_item.get("child_visible") if isinstance(semantic_item.get("child_visible"), dict) else {}
        review_only = semantic_item.get("review_only") if isinstance(semantic_item.get("review_only"), dict) else {}
        semantic_item.update({
            key: value
            for key, value in {
                "prompt": child_visible.get("prompt"),
                "answer_format": review_only.get("answer_format"),
                "expected_answer": review_only.get("expected_answer"),
                "accepted_alternatives": review_only.get("accepted_alternatives"),
                "solution_steps": review_only.get("solution_steps"),
                "child_surface_design": structured.get("child_surface_design"),
                "intended_instruction_voice_family": structured.get("intended_instruction_voice_family"),
                "difficulty_vector": structured.get("difficulty_vector"),
                "node_local_mainline": structured.get("node_local_mainline"),
                "controlled_stretch": structured.get("controlled_stretch"),
                "target_error_tags": structured.get("target_error_tags"),
                "rollback_candidates": structured.get("rollback_candidates"),
                "math_core_signature": structured.get("math_core_signature"),
                "core_stem_id": structured.get("core_stem_id"),
                "problem_family_id": structured.get("problem_family_id"),
            }.items()
            if value is not None
        })
        verdict = "rejected" if int(item["slot"]) in reject_slots else "approved"
        evidence = _reviewer_evidence(item["id"])
        evidence.pop("engine_type", None)
        item_reviews.append({
            "item_id": item["id"],
            "candidate_sha256": item.get("candidate_sha256") or question_bank.v12_external_candidate_sha256(item),
            "verdict": verdict,
            "scores": {
                "node_alignment": 0.95,
                "mathematical_correctness": 0.95,
                "reasoning_signal": 0.9,
                "non_mechanical": 0.9 if verdict == "approved" else 0.4,
                "answer_alignment": 0.9,
            },
            "reasons": ["approved reasoning item"] if verdict == "approved" else ["mechanical or thin item"],
            "repair_instructions": [] if verdict == "approved" else ["replace with a node-local reasoning item"],
            "reviewer_evidence": evidence,
            "semantic_evidence": _semantic_evidence_for_item(
                semantic_item,
                version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
            ),
            "confidence": 0.93,
        })
    return {
        "schema_version": question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION,
        "node_id": node_id,
        "graph_version": graph_version,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "item_reviews": item_reviews,
        "batch_verdict": "needs_repair" if reject_slots else "approved",
        "batch_reason": "repair required" if reject_slots else "batch approved",
    }


def _reviewer_batch_response_for_payload(
    module,
    node_id: str,
    graph_version: str,
    payload: dict,
    *,
    reject_slots: set[int] | None = None,
) -> dict:
    items = _untrusted_candidate_batch_from_payload(payload).get("items") or []
    return _reviewer_batch_response(
        module,
        node_id,
        graph_version,
        items,
        reject_slots=reject_slots,
    )


def _node_set_review_response(
    node_entry: dict,
    graph_version: str,
    *,
    reviewed_slots: list[int] | None = None,
    rejected_slots: list[int] | None = None,
    confidence: float = 0.93,
) -> dict:
    node_id = str(node_entry["node_id"])
    reviewed_slots = reviewed_slots or [int(item["slot"]) for item in node_entry.get("items") or []]
    item_by_slot = {
        int(item.get("slot") or 0): item
        for item in node_entry.get("items") or []
        if isinstance(item, dict)
    }
    rejected_slots = rejected_slots or []
    focal_slot_reviews = [
        {
            "slot": slot,
            "item_id": item_by_slot[slot]["id"],
            "candidate_sha256": (
                item_by_slot[slot].get("candidate_sha256")
                or question_bank.v12_external_candidate_sha256(item_by_slot[slot])
            ),
            "item_review_semantic_evidence_sha256": (
                item_by_slot[slot].get("item_review_semantic_evidence_sha256")
                or (item_by_slot[slot].get("review_artifact") or {}).get("semantic_evidence_sha256")
            ),
            "verdict": "needs_repair" if slot in rejected_slots else "approved",
            "slot_fit": {"verdict": "pass", "score": 0.95, "reason": "The item fits its focal slot."},
            "mathematical_correctness": {"verdict": "pass", "score": 0.95, "reason": "The reference solution is mathematically sound."},
            "context_semantics": {"verdict": "pass", "score": 0.95, "reason": "The task context is clear and self-contained."},
            "prompt_answer_alignment": {"verdict": "pass", "score": 0.95, "reason": "The expected answer matches the prompt."},
            "duplicate_suspicion_ids": [],
            "evidence": "Focal mathematical and semantic checks completed.",
            "repair_direction": "repair the cited defect" if slot in rejected_slots else "none",
        }
        for slot in reviewed_slots
    ]
    return {
        "schema_version": question_bank.V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION,
        "node_id": node_id,
        "graph_version": graph_version,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_FOCAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": "needs_repair" if rejected_slots else "approved",
        "rejected_slots": rejected_slots,
        "duplicate_suspicions": [],
        "focal_slot_reviews": focal_slot_reviews,
        "confidence": confidence,
        "reasons": ["focal semantic evidence reviewed"],
        "repair_instructions": [
            {
                "slot": slot,
                "repair_scope": "focal_math_or_context",
                "preserved_role": str(item_by_slot[slot].get("slot_role") or ""),
                "preserve_or_replace_math_core": "replace_math_core",
                "required_voice_family": str(
                    item_by_slot[slot].get("intended_instruction_voice_family")
                    or "solve_and_interpret"
                ),
                "avoided_voice_families": [],
                "exact_target_delta": {
                    "dimension": "slot_fit",
                    "from_value": "focal_review_rejected",
                    "to_value": "role_compatible_distinct_evidence",
                },
                "evidence_refs": [f"focal_review:slot:{slot}"],
            }
            for slot in rejected_slots
        ],
    }


def _node_set_global_finalizer_output(
    node_entry: dict,
    constituent_reviews: list[dict],
    *,
    rejected_slots: list[int] | None = None,
    duplicate_groups: list[dict] | None = None,
    confidence: float = 0.95,
) -> dict:
    rejected_slots = sorted(set(int(slot) for slot in (rejected_slots or [])))
    duplicate_groups = json.loads(json.dumps(duplicate_groups or []))
    item_by_slot = {
        int(item.get("slot") or 0): item
        for item in node_entry.get("items") or []
        if isinstance(item, dict) and int(item.get("slot") or 0)
    }
    scores = {key: 0.95 for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS}
    if rejected_slots or duplicate_groups:
        scores["semantic_diversity"] = 0.7
        scores["problem_family_distribution"] = 0.7
    ux = question_bank.v12_node_set_ux_aggregate(
        node_entry,
        constituent_reviews,
        {
            "node_ux_verdict": "approved",
            "repetitive_instruction_clusters": [],
            "overloaded_slots": [],
            "notation_failure_slots": [],
            "dignity_failure_slots": [],
            "ux_rejected_slots": [],
        },
    )
    evidence_moves = list(question_bank.V12_PRIMARY_EVIDENCE_MOVES)
    answer_paths = list(question_bank.V12_ANSWER_PATH_FAMILIES)
    representations = list(question_bank.V12_REPRESENTATION_FAMILIES)
    classifications = []
    for index, item in enumerate(sorted(item_by_slot.values(), key=lambda value: int(value["slot"]))):
        subject = question_bank.v12_item_review_subject_binding(item)
        classifications.append({
            **{key: subject[key] for key in (
                "node_id", "slot", "item_id", "candidate_sha256", "child_surface_sha256",
                "item_review_request_sha256", "item_review_semantic_evidence_sha256",
            )},
            "ownership_mode": "current_node_mainline",
            "current_node_indispensable": "yes",
            "primary_evidence_move": evidence_moves[index % len(evidence_moves)],
            "answer_path_family": answer_paths[index % len(answer_paths)],
            "representation_family": representations[index % len(representations)],
            "difficulty_verdict": "L2" if index < 14 else "L3",
            "difficulty_features": [],
            "prompt_interaction_verdict": "aligned",
            "reason": "fixture classification follows the actual child surface",
        })
    bound_duplicate_groups = []
    for group in duplicate_groups:
        slots = sorted(set(group.get("slots") or []))
        bound_duplicate_groups.append({
            **group,
            "subject_sha256s": sorted(
                question_bank.v12_item_review_subject_binding(item_by_slot[slot])["subject_sha256"]
                for slot in slots
            ),
        })
    return {
        "schema_version": question_bank.V12_NODE_SET_GLOBAL_FULL_OUTPUT_SCHEMA_VERSION,
        "node_id": node_entry["node_id"],
        "graph_version": _graph_version(),
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_REVIEW_SEMANTIC_EVIDENCE_VERSION,
        "verdict": "needs_repair" if rejected_slots or duplicate_groups else "approved",
        "node_ux_verdict": "approved",
        "slot_evidence_coverage": question_bank.v12_node_set_semantic_evidence_coverage(
            node_entry,
            constituent_reviews,
        ),
        "distribution_scores": scores,
        "item_classifications": classifications,
        "homogeneous_clusters": [],
        "instruction_voice_distribution": ux["instruction_voice_distribution"],
        "unprompted_slot_results": ux["unprompted_slot_results"],
        "repetitive_instruction_clusters": [],
        "duplicate_groups": bound_duplicate_groups,
        "overloaded_slots": [],
        "notation_failure_slots": [],
        "dignity_failure_slots": [],
        "ux_rejected_slots": [],
        "rejected_slots": rejected_slots,
        "confidence": confidence,
        "reasons": ["global compact review completed"],
        "repair_plan": [
            {
                "slot": slot,
                "repair_scope": "global_slot_fit",
                "preserved_role": str(item_by_slot.get(slot, {}).get("slot_role") or ""),
                "preserve_or_replace_math_core": "replace_math_core",
                "required_voice_family": str(
                    item_by_slot.get(slot, {}).get("intended_instruction_voice_family")
                    or "solve_and_interpret"
                ),
                "avoided_voice_families": [],
                "exact_target_delta": {
                    "dimension": "slot_fit",
                    "from_value": "node_set_semantic_repair",
                    "to_value": "role_compatible_distinct_evidence",
                },
                "evidence_refs": [f"global_finalizer:slot:{slot}"],
            }
            for slot in rejected_slots
        ],
    }


def _node_set_global_finalizer_artifact(
    node_entry: dict,
    constituent_reviews: list[dict],
    output: dict,
    *,
    provider_mode: str = "live_model",
) -> dict:
    module = _load_v12_build_module()
    lineage = module._global_finalizer_expected_lineage(node_entry, constituent_reviews)
    model_judgment = {
        "schema_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "node_id": output.get("node_id"),
        "graph_version": output.get("graph_version"),
        "question_bank_version": output.get("question_bank_version"),
        "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION,
        "item_classifications": output.get("item_classifications") or [],
        "homogeneous_clusters": output.get("homogeneous_clusters") or [],
        "distribution_scores": output.get("distribution_scores") or {},
        "repetitive_instruction_clusters": output.get("repetitive_instruction_clusters") or [],
        "duplicate_groups": output.get("duplicate_groups") or [],
        "confidence": output.get("confidence"),
        "reasons": output.get("reasons") or [],
        "repair_plan": output.get("repair_plan") or [],
    }
    artifact = {
        "global_review_output": output,
        "global_review_output_sha256": _sha256_json(output),
        "model_judgment_output": model_judgment,
        "model_judgment_output_sha256": _sha256_json(model_judgment),
        "node_candidate_sha256": question_bank.v12_node_candidate_sha256(node_entry),
        "constituent_semantic_evidence_sha256": [
            review.get("semantic_evidence_sha256", "")
            for review in constituent_reviews
        ],
        **_model_audit_artifact(
            provider_mode=provider_mode,
            artifact_role="node_set_global_finalizer",
            agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
            phase="node_global_finalizer",
            model_name="gpt-5.4",
            contract_key="math_question_bank_v12_node_set_global_finalizer",
            contract_version=question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
            prompt_version_id=question_bank.V12_GLOBAL_FINALIZER_PROMPT_VERSION_ID,
            response_schema_version=question_bank.V12_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        ),
        "review_phase": "global_finalizer",
        "pipeline_stage": "node_set_global_finalizer",
        "stage_attempt": 1,
        "semantic_evidence_version": question_bank.V12_GLOBAL_FINALIZER_SEMANTIC_EVIDENCE_VERSION,
        **{
            key: lineage[key]
            for key in (
                "prompt_template_sha256",
                "rendered_prompt_sha256",
                "response_schema_sha256",
                "request_lineage_version",
                "trusted_context_sha256",
                "untrusted_payload_sha256",
                "request_options_sha256",
                "request_input_sha256",
                "request_lineage_sha256",
            )
        },
    }
    artifact["semantic_evidence_sha256"] = _sha256_json({
        "semantic_evidence_version": artifact["semantic_evidence_version"],
        "node_candidate_sha256": artifact["node_candidate_sha256"],
        "constituent_semantic_evidence_sha256": artifact["constituent_semantic_evidence_sha256"],
        "global_review_output_sha256": artifact["global_review_output_sha256"],
    })
    return artifact


def _v4_duplicate_node_set_aggregate(
    module,
    node_entry: dict,
    graph_version: str,
    *,
    duplicate_slots: list[int],
    rejected_slots: list[int],
    reason: str,
) -> dict:
    suspicion_id = "duplicate-core-across-focal-shards"
    focal_contract = module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH)
    focal_prompt = module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    shard_reviews = []
    for shard_slots in _v12_runtime_node_set_shards():
        local_rejected = sorted(set(shard_slots).intersection(rejected_slots))
        output = _node_set_review_response(
            node_entry,
            graph_version,
            reviewed_slots=shard_slots,
            rejected_slots=local_rejected,
        )
        if set(shard_slots).intersection(duplicate_slots):
            output["duplicate_suspicions"] = [{
                "suspicion_id": suspicion_id,
                "slots": duplicate_slots,
                "reason": reason,
                "evidence_refs": [f"slot:{slot}" for slot in duplicate_slots],
            }]
            for focal_review in output["focal_slot_reviews"]:
                if int(focal_review["slot"]) in duplicate_slots:
                    focal_review["duplicate_suspicion_ids"] = [suspicion_id]
        for directive in output["repair_instructions"]:
            directive["exact_target_delta"] = {
                "dimension": "mathematical_core",
                "from_value": "duplicate_core",
                "to_value": "distinct_node_local_core",
            }
        result = module.model_router.StructuredJSONResult(
            value=output,
            mode="json_schema",
            raw_response={"duplicate_suspicion": suspicion_id, "slots": shard_slots},
        )
        shard_reviews.append(module._node_set_review_constituent_artifact(
            node_entry=node_entry,
            reviewed_slots=shard_slots,
            output=output,
            contract=focal_contract,
            prompt_template=focal_prompt,
            rendered_prompt=f"focal-duplicate-{shard_slots[0]}",
            result=result,
            route=module.model_router.question_node_set_review_route(),
            stage_attempt=1,
        ))

    duplicate_group = {
        "group_id": suspicion_id,
        "slots": duplicate_slots,
        "reason": reason,
        "evidence_refs": [f"focal_suspicion:{suspicion_id}"],
    }
    global_output = _node_set_global_finalizer_output(
        node_entry,
        shard_reviews,
        rejected_slots=rejected_slots,
        duplicate_groups=[duplicate_group],
    )
    for directive in global_output["repair_plan"]:
        directive["repair_scope"] = "global_duplicate"
        directive["exact_target_delta"] = {
            "dimension": "mathematical_core",
            "from_value": "duplicate_core",
            "to_value": "distinct_node_local_core",
        }
    global_result = module.model_router.StructuredJSONResult(
        value=global_output,
        mode="json_schema",
        raw_response={"duplicate_group": duplicate_slots},
    )
    global_lineage = module._global_finalizer_expected_lineage(node_entry, shard_reviews)
    global_artifact = module._node_set_global_finalizer_artifact(
        node_entry=node_entry,
        constituent_reviews=shard_reviews,
        output=global_output,
        contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
        prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
        rendered_prompt=global_lineage["rendered_prompt"],
        result=global_result,
        route=module.model_router.question_node_global_finalizer_route(),
        stage_attempt=1,
    )
    return module._aggregate_node_set_review_outputs(
        node_entry=node_entry,
        shard_reviews=shard_reviews,
        global_finalizer_artifact=global_artifact,
    )


def _node_set_review_response_for_payload(
    node_id: str,
    graph_version: str,
    payload: dict,
    *,
    rejected_slots: list[int] | None = None,
    confidence: float = 0.93,
) -> dict:
    reviewed_slots = _reviewed_slots_from_payload(payload)
    untrusted = (
        _untrusted_candidate_batch_from_payload(payload)
        or _json_section_from_payload(payload, "Untrusted Focal And Comparison Payload")
        or _json_section_from_payload(payload, "Untrusted Payload JSON")
    )
    return _node_set_review_response(
        {"node_id": node_id, "items": untrusted.get("items") or []},
        graph_version,
        reviewed_slots=reviewed_slots,
        rejected_slots=rejected_slots,
        confidence=confidence,
    )


def _node_set_global_finalizer_response_for_payload(payload: dict, *, confidence: float = 0.95) -> dict:
    trusted = _json_section_from_payload(payload, "Trusted Context")
    untrusted = (
        _json_section_from_payload(payload, "Untrusted Global Evidence Packet")
        or _json_section_from_payload(payload, "Untrusted Node Set Review Payload")
        or _json_section_from_payload(payload, "Untrusted Payload JSON")
    )
    item_cards = untrusted.get("item_cards") if isinstance(untrusted.get("item_cards"), list) else []
    focal_summaries = (
        untrusted.get("focal_review_summaries")
        if isinstance(untrusted.get("focal_review_summaries"), list)
        else []
    )
    card_by_slot = {
        int(card.get("slot") or 0): card
        for card in item_cards
        if isinstance(card, dict) and int(card.get("slot") or 0)
    }
    slots_by_family: dict[str, list[int]] = {}
    unprompted: list[dict] = []
    overloaded_slots: list[int] = []
    notation_failure_slots: list[int] = []
    dignity_failure_slots: list[int] = []
    ux_rejected_slots: list[int] = []
    for card in item_cards:
        if not isinstance(card, dict):
            continue
        slot = int(card.get("slot") or 0)
        family = str(card.get("instruction_voice_family") or "")
        if family in question_bank.V12_INSTRUCTION_VOICE_FAMILIES and 1 <= slot <= question_bank.QUESTIONS_PER_GRAPH_NODE:
            slots_by_family.setdefault(family, []).append(slot)
        response_moves = card.get("response_moves") if isinstance(card.get("response_moves"), list) else []
        if len(response_moves) > question_bank.V12_MAX_RESPONSE_MOVES:
            overloaded_slots.append(slot)
        summary = card.get("item_semantic_summary") if isinstance(card.get("item_semantic_summary"), dict) else {}
        notation = summary.get("rendered_notation_readiness") if isinstance(summary.get("rendered_notation_readiness"), dict) else {}
        if (
            notation.get("verdict") != "pass"
            or abs(float(notation.get("score") or 0.0) - question_bank.V12_RENDERED_NOTATION_REQUIRED_SCORE) > 1e-9
            or bool(notation.get("child_visible_risks") or [])
        ):
            notation_failure_slots.append(slot)
        dignity = summary.get("age_dignity") if isinstance(summary.get("age_dignity"), dict) else {}
        if dignity.get("verdict") != "pass" or float(dignity.get("score") or 0.0) < question_bank.V12_AGE_DIGNITY_MIN_SCORE:
            dignity_failure_slots.append(slot)
        process = summary.get("unprompted_process_evidence") if isinstance(summary.get("unprompted_process_evidence"), dict) else {}
        disclosure = summary.get("process_disclosure_evidence") if isinstance(summary.get("process_disclosure_evidence"), dict) else {}
        if process.get("applicability") == "required":
            unprompted.append({
                "slot": slot,
                "item_id": card.get("item_id"),
                "candidate_sha256": card.get("candidate_sha256"),
                "process_target_disclosed": summary.get("process_target_disclosed"),
                "verdict": process.get("verdict"),
                "score": process.get("score"),
                "source_field": disclosure.get("source_field"),
                "quote": disclosure.get("quote"),
                "reason": process.get("reason"),
            })
    deterministic_ux = (
        trusted.get("deterministic_ux_projection")
        if isinstance(trusted.get("deterministic_ux_projection"), dict)
        else {}
    )
    if deterministic_ux:
        slots_by_family = {
            str(entry.get("instruction_voice_family") or ""): list(entry.get("slots") or [])
            for entry in deterministic_ux.get("instruction_voice_distribution") or []
            if isinstance(entry, dict)
        }
        unprompted = list(deterministic_ux.get("unprompted_slot_results") or [])
        overloaded_slots = list(deterministic_ux.get("overloaded_slots") or [])
        notation_failure_slots = list(deterministic_ux.get("notation_failure_slots") or [])
        dignity_failure_slots = list(deterministic_ux.get("dignity_failure_slots") or [])
        ux_rejected_slots = list(deterministic_ux.get("ux_rejected_slots") or [])
    focal_rejected_slots = sorted({
        int(slot)
        for summary in focal_summaries
        if isinstance(summary, dict)
        for slot in (summary.get("rejected_slots") or [])
        if isinstance(slot, int)
    })
    focal_directive_by_slot = {
        int(directive.get("slot") or 0): directive
        for summary in focal_summaries
        if isinstance(summary, dict)
        for directive in (summary.get("repair_instructions") or [])
        if isinstance(directive, dict) and int(directive.get("slot") or 0)
    }
    repair_plan = []
    for slot in focal_rejected_slots:
        card = card_by_slot.get(slot, {})
        voice = str(card.get("instruction_voice_family") or "solve_and_interpret")
        focal_delta = (
            focal_directive_by_slot.get(slot, {}).get("exact_target_delta")
            if isinstance(focal_directive_by_slot.get(slot, {}).get("exact_target_delta"), dict)
            else {}
        )
        repair_plan.append({
            "slot": slot,
            "repair_scope": "global_slot_fit",
            "preserved_role": str(card.get("slot_role") or ""),
            "preserve_or_replace_math_core": "replace_math_core",
            "required_voice_family": voice,
            "avoided_voice_families": [],
            "exact_target_delta": {
                "dimension": "slot_fit",
                "from_value": str(focal_delta.get("from_value") or "focal_rejected_or_duplicate"),
                "to_value": "distinct_node_local_evidence",
            },
            "evidence_refs": [f"focal_review:slot:{slot}"],
        })
    distribution = [
        {"instruction_voice_family": family, "slots": sorted(set(slots_by_family[family]))}
        for family in question_bank.V12_INSTRUCTION_VOICE_FAMILIES
        if slots_by_family.get(family)
    ]
    ux_rejected_slots = sorted(set(overloaded_slots + notation_failure_slots + dignity_failure_slots + ux_rejected_slots))
    rejected_slots = sorted(set(focal_rejected_slots + ux_rejected_slots))
    node = trusted.get("node") if isinstance(trusted.get("node"), dict) else {}
    evidence_moves = list(question_bank.V12_PRIMARY_EVIDENCE_MOVES)
    answer_paths = list(question_bank.V12_ANSWER_PATH_FAMILIES)
    representations = list(question_bank.V12_REPRESENTATION_FAMILIES)
    classifications = []
    for index, card in enumerate(sorted(item_cards, key=lambda value: int(value.get("slot") or 0))):
        subject = card.get("review_subject") if isinstance(card.get("review_subject"), dict) else {}
        classifications.append({
            "slot": int(card.get("slot") or 0),
            "node_id": str(subject.get("node_id") or node.get("id") or ""),
            "item_id": str(subject.get("item_id") or card.get("item_id") or ""),
            "candidate_sha256": str(subject.get("candidate_sha256") or "model-echo"),
            "child_surface_sha256": str(subject.get("child_surface_sha256") or "model-echo"),
            "item_review_request_sha256": str(subject.get("item_review_request_sha256") or "model-echo"),
            "item_review_semantic_evidence_sha256": str(subject.get("item_review_semantic_evidence_sha256") or "model-echo"),
            "ownership_mode": "current_node_mainline",
            "current_node_indispensable": "yes",
            "primary_evidence_move": evidence_moves[index % len(evidence_moves)],
            "answer_path_family": answer_paths[index % len(answer_paths)],
            "representation_family": representations[index % len(representations)],
            "difficulty_verdict": "L2" if index < 14 else "L3",
            "difficulty_features": [],
            "prompt_interaction_verdict": "aligned",
            "reason": "actual child surface requires this evidence move and answer path",
        })
    return {
        "schema_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "node_id": untrusted.get("node_id") or node.get("id"),
        "graph_version": trusted.get("graph_version") or _graph_version(),
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION,
        "item_classifications": classifications,
        "homogeneous_clusters": [],
        "distribution_scores": {key: 0.95 for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS},
        "repetitive_instruction_clusters": [],
        "duplicate_groups": [],
        "confidence": confidence,
        "reasons": ["global compact review completed"],
        "repair_plan": repair_plan,
    }


def _designer_batch_items(items: list[dict]) -> list[dict]:
    sanitized = []
    for item in items:
        copied = json.loads(json.dumps(item))
        copied.pop("review_artifact", None)
        copied.pop("rollback_candidate_relations", None)
        copied.setdefault("child_surface_design", json.loads(json.dumps(question_bank.V12_CHILD_SURFACE_DESIGN)))
        copied.setdefault("elicitation_mode", "direct_prompted_evidence")
        copied.setdefault(
            "intended_instruction_voice_family",
            _v12_test_voice_family_for_role(str(copied.get("slot_role") or "")),
        )
        if isinstance(copied.get("difficulty_vector"), dict):
            copied["difficulty_vector"].pop("level", None)
        artifact = copied.get("designer_artifact") if isinstance(copied.get("designer_artifact"), dict) else {}
        copied["designer_artifact"] = {
            "designer_run_id": artifact.get("designer_run_id", ""),
            "prompt_version_id": question_bank.V12_DESIGNER_PROMPT_VERSION_ID,
            "design_rationale": artifact.get("design_rationale", ""),
        }
        sanitized.append(copied)
    return sanitized


def _requested_slots_from_payload(payload: dict) -> list[int]:
    return _slot_list_from_payload(payload, marker="requested_slots")


def _reviewed_slots_from_payload(payload: dict) -> list[int]:
    return _slot_list_from_payload(payload, marker="reviewed_slots")


def _slot_list_from_payload(payload: dict, *, marker: str) -> list[int]:
    rendered = str(payload.get("instructions") or "")
    self_index = rendered.find(f'"{marker}"')
    if self_index < 0:
        return []
    decoder = json.JSONDecoder()
    search = rendered.find("[", self_index)
    while search >= 0:
        try:
            value, _ = decoder.raw_decode(rendered[search:])
        except json.JSONDecodeError:
            search = rendered.find("[", search + 1)
            continue
        if isinstance(value, list) and all(isinstance(item, int) for item in value):
            return value
        search = rendered.find("[", search + 1)
    return []


def _json_section_from_payload(payload: dict, heading: str) -> dict:
    rendered = str(payload.get("instructions") or "")
    marker = f"## {heading}"
    start = rendered.find(marker)
    if start < 0:
        return {}
    json_start = rendered.find("{", start)
    next_heading = rendered.find("\n## ", json_start)
    section = rendered[json_start: next_heading if next_heading >= 0 else len(rendered)]
    return json.loads(section)


def _untrusted_candidate_batch_from_payload(payload: dict) -> dict:
    rendered = str(payload.get("instructions") or "")
    start_tag = "<untrusted_data>"
    end_tag = "</untrusted_data>"
    start = rendered.find(start_tag)
    end = rendered.find(end_tag, start + len(start_tag))
    if start < 0 or end < 0:
        return {}
    return json.loads(rendered[start + len(start_tag):end].strip())


def _load_v12_build_module():
    script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
    spec = importlib.util.spec_from_file_location("build_math_question_bank_v12_repair_budget_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load v12 question-bank build module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _incomplete_live_checkpoint(node_entry: dict, graph_version: str, *, local_round: int) -> dict:
    copied = json.loads(json.dumps(node_entry, ensure_ascii=False))
    copied.pop("node_review_artifact", None)
    return {
        "node_id": copied["node_id"],
        "graph_version": graph_version,
        "status": "incomplete",
        "rounds_used": local_round,
        "rejected_rounds": 0,
        "issue_count": 0,
        "blocking_issue_types": [],
        "node": copied,
        "accepted_slots": {
            str(item["slot"]): item
            for item in copied["items"]
        },
        "slot_rounds": {
            str(item["slot"]): local_round
            for item in copied["items"]
        },
        "cross_node_summary_contexts": _test_cross_node_contexts(
            copied["node_id"],
            graph_version,
        ),
    }


def _test_cross_node_contexts(node_id: str, graph_version: str) -> dict:
    return {
        "generation": {
            "schema_version": "qa.cross-node-context.v1",
            "selector_policy_version": "qa.selector.v1",
            "registry_scope": "qa_fixture",
            "focal_node_id": node_id,
            "graph_version": graph_version,
            "ordered_source_node_ids": [],
            "full_registry_digest_sha256": _sha256_json([]),
            "selected_summary_digest_sha256": _sha256_json([]),
        }
    }


def _build_live_node_test_kwargs(
    module,
    *,
    node: dict,
    graph: dict,
    graph_version: str,
    checkpoint_dir: Path,
    max_rounds: int,
) -> dict:
    return {
        "node": node,
        "graph": graph,
        "graph_version": graph_version,
        "checkpoint_dir": checkpoint_dir,
        "max_rounds": max_rounds,
        "chunk_concurrency": 1,
        "node_review_concurrency": 1,
        "resume": True,
        "designer_contract": {},
        "reviewer_contract": {},
        "node_set_reviewer_contract": {},
        "global_finalizer_contract": {},
        "designer_prompt_template": "",
        "reviewer_prompt_template": "",
        "node_set_reviewer_prompt_template": "",
        "global_finalizer_prompt_template": "",
        "accepted_core_summaries": [],
        "cross_node_summary_contexts": _test_cross_node_contexts(
            node["id"],
            graph_version,
        ),
    }


def _v12_repair_chain_event(
    *,
    event_index: int,
    stage: str,
    stage_attempt: int,
    slot: int,
    reason: str,
    instruction: dict,
    old_candidate_sha256: str,
    new_candidate_sha256: str,
    source_review_artifact_sha256: str,
    previous_event_sha256: str = "",
) -> dict:
    payload = {
        "event_index": event_index,
        "stage": stage,
        "stage_attempt": stage_attempt,
        "slot": slot,
        "reason": reason,
        "instruction_sha256": _sha256_json(instruction),
        "old_candidate_sha256": old_candidate_sha256,
        "new_candidate_sha256": new_candidate_sha256,
        "source_review_artifact_sha256": source_review_artifact_sha256,
        "previous_event_sha256": previous_event_sha256,
    }
    return {**payload, "event_sha256": _sha256_json(payload)}


def _v12_repair_chain_commitment(events: list[dict]) -> tuple[str, str]:
    head_sha256 = str(events[-1]["event_sha256"] if events else "")
    chain_sha256 = _sha256_json({
        "repair_chain_events": events,
        "repair_chain_head_sha256": head_sha256,
    })
    return head_sha256, chain_sha256


def _v12_incomplete_checkpoint_integrity_payload(checkpoint: dict) -> dict:
    node_entry = checkpoint.get("node") if isinstance(checkpoint.get("node"), dict) else {}
    partial_review = (
        node_entry.get("node_review_artifact")
        if isinstance(node_entry.get("node_review_artifact"), dict)
        else {}
    )
    payload = {
        "node_id": checkpoint.get("node_id"),
        "graph_version": checkpoint.get("graph_version"),
        "status": checkpoint.get("status"),
        "accepted_slots": checkpoint.get("accepted_slots") or {},
        "source_node_candidate_sha256": checkpoint.get("source_node_candidate_sha256") or "",
        "pending_repair_by_slot": checkpoint.get("pending_repair_by_slot") or {},
        "stage_counters": checkpoint.get("stage_counters") or {},
        "partial_node_review_artifact": partial_review,
        "semantic_evidence_commitment": checkpoint.get("semantic_evidence_commitment") or {},
        "repair_chain_events": checkpoint.get("repair_chain_events") or [],
        "repair_chain_head_sha256": checkpoint.get("repair_chain_head_sha256") or "",
    }
    if "cross_node_summary_contexts" in checkpoint:
        payload["cross_node_summary_contexts"] = (
            checkpoint.get("cross_node_summary_contexts") or {}
        )
    if "cross_node_context_requirement" in checkpoint:
        payload["cross_node_context_requirement"] = (
            checkpoint.get("cross_node_context_requirement") or {}
        )
    return payload


def _seal_v12_incomplete_checkpoint(checkpoint: dict) -> dict:
    node_entry = checkpoint.get("node") if isinstance(checkpoint.get("node"), dict) else {}
    checkpoint["semantic_evidence_commitment"] = question_bank.v12_node_semantic_evidence_commitment(node_entry)
    checkpoint["checkpoint_integrity_sha256"] = _sha256_json(
        _v12_incomplete_checkpoint_integrity_payload(checkpoint)
    )
    return checkpoint


def _reseal_v12_completed_checkpoint(module, checkpoint: dict) -> dict:
    node_entry = checkpoint.get("node") if isinstance(checkpoint.get("node"), dict) else {}
    checkpoint["semantic_evidence_commitment"] = question_bank.v12_node_semantic_evidence_commitment(node_entry)
    checkpoint["completed_node_receipt"] = module._completed_checkpoint_node_receipt(
        node_entry=node_entry,
        graph_version=str(checkpoint.get("graph_version") or ""),
        repair_chain_hash=str(checkpoint.get("repair_chain_hash") or ""),
        model_budget_commitment=module._model_budget_receipt_commitment(
            checkpoint.get("model_budget") or {}
        ),
    )
    checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(checkpoint)
    return checkpoint


def _v12_completed_checkpoint_with_repair_chain(module, node_entry: dict, graph_version: str) -> dict:
    final_item = node_entry["items"][6]
    old_candidate = json.loads(json.dumps(final_item, ensure_ascii=False))
    old_candidate["prompt"] = "Thin local-round candidate before repair."
    middle_candidate = json.loads(json.dumps(final_item, ensure_ascii=False))
    middle_candidate["math_core_signature"] = "node-set-middle-core-before-final-repair"
    old_sha256 = question_bank.v12_external_candidate_sha256(old_candidate)
    middle_sha256 = question_bank.v12_external_candidate_sha256(middle_candidate)
    final_sha256 = question_bank.v12_external_candidate_sha256(final_item)
    source_review_sha256 = _sha256_json(final_item.get("review_artifact") or {})
    local_instruction = {"slot": 7, "reason": "local_item_repair", "guidance": "repair local reasoning"}
    node_set_instruction = {
        "slot": 7,
        "reason": "v12_node_set_semantic_review",
        "guidance": "replace the mathematical core",
    }
    duplicate_instruction = {
        "slot": 7,
        "reason": "v12_node_set_duplicate_group",
        "guidance": "replace the model-reported duplicate mathematical core",
    }
    first = _v12_repair_chain_event(
        event_index=1,
        stage="local_item_repair",
        stage_attempt=3,
        slot=7,
        reason=local_instruction["reason"],
        instruction=local_instruction,
        old_candidate_sha256=old_sha256,
        new_candidate_sha256=middle_sha256,
        source_review_artifact_sha256=source_review_sha256,
    )
    second = _v12_repair_chain_event(
        event_index=2,
        stage="node_set_semantic_repair",
        stage_attempt=1,
        slot=7,
        reason=node_set_instruction["reason"],
        instruction=node_set_instruction,
        old_candidate_sha256=middle_sha256,
        new_candidate_sha256=final_sha256,
        source_review_artifact_sha256=source_review_sha256,
        previous_event_sha256=first["event_sha256"],
    )
    third = _v12_repair_chain_event(
        event_index=3,
        stage="node_set_semantic_repair",
        stage_attempt=2,
        slot=7,
        reason=duplicate_instruction["reason"],
        instruction=duplicate_instruction,
        old_candidate_sha256=final_sha256,
        new_candidate_sha256=final_sha256,
        source_review_artifact_sha256=source_review_sha256,
        previous_event_sha256=second["event_sha256"],
    )
    events = [first, second, third]
    head_sha256, chain_sha256 = _v12_repair_chain_commitment(events)
    model_budget = {
        "schema_version": module.V12_MODEL_BUDGET_SCHEMA_VERSION,
        "node_id": node_entry["node_id"],
        "semantic_calls": 0,
        "provider_attempts": 0,
        "max_semantic_calls": module.DEFAULT_MAX_SEMANTIC_CALLS,
        "max_provider_attempts": module.DEFAULT_MAX_PROVIDER_ATTEMPTS,
        "counter_events": [],
        "counter_chain_head_sha256": "",
        "migrations": [],
        "interruptions": [],
        "status": "completed",
        "reason": "",
        "run_ids": ["TEST-COMPLETED-CHECKPOINT"],
    }
    model_budget["integrity_sha256"] = module._model_budget_integrity_sha256(model_budget)
    checkpoint = {
        "node_id": node_entry["node_id"],
        "graph_version": graph_version,
        "status": "completed",
        "rounds_used": 3,
        "rejected_rounds": 3,
        "issue_count": 0,
        "blocking_issue_types": [],
        "node": node_entry,
        "accepted_slots": {str(item["slot"]): item for item in node_entry["items"]},
        "source_node_candidate_sha256": question_bank.v12_node_candidate_sha256(node_entry),
        "repair_chain_events": events,
        "repair_chain_head_sha256": head_sha256,
        "repair_chain_hash": chain_sha256,
        "model_budget": model_budget,
        "semantic_evidence_commitment": question_bank.v12_node_semantic_evidence_commitment(node_entry),
        "completed_node_receipt": module._completed_checkpoint_node_receipt(
            node_entry=node_entry,
            graph_version=graph_version,
            repair_chain_hash=chain_sha256,
            model_budget_commitment=module._model_budget_receipt_commitment(model_budget),
        ),
    }
    checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(checkpoint)
    return checkpoint


def _run_v12_stage_repair_scenario(module, *, stage: str) -> tuple[dict, dict, dict]:
    graph = _load_graph()
    manifest = _manifest(provider_mode="live_model", status="draft_live_model")
    node_entry = manifest["nodes"][0]
    node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
    local_round = 2 if stage == "local_item_repair" else 3
    local_instruction = {
        "reason": "v12_local_semantic_repair",
        "slot": 7,
        "slots": [7],
        "repair_instructions": ["replace the local reasoning core"],
    }
    node_set_instruction = {
        "reason": "v12_node_set_semantic_review",
        "slot": 7,
        "slots": [7],
        "repair_instructions": ["replace the node-set mathematical core"],
    }
    local_calls = {"count": 0}
    node_set_calls = {"count": 0}

    def fake_local_repair(*args, **kwargs):
        local_calls["count"] += 1
        if stage == "local_item_repair" and local_calls["count"] == 1:
            return [local_instruction]
        return []

    def fake_node_set_review(**kwargs):
        node_set_calls["count"] += 1
        if stage == "node_set_semantic_repair" and node_set_calls["count"] == 1:
            return {"repair_instructions": [node_set_instruction], "node_review_artifact": None}
        artifact = _node_review_artifact(kwargs["node_entry"], provider_mode="live_model")
        artifact.update({
            "pipeline_stage": "node_set_review",
            "stage_attempt": int(kwargs.get("stage_attempt") or node_set_calls["count"]),
        })
        for review in artifact.get("constituent_reviews") or []:
            review.update({
                "pipeline_stage": "node_set_review",
                "stage_attempt": artifact["stage_attempt"],
            })
        return {"repair_instructions": [], "node_review_artifact": artifact}

    raw_items = _designer_batch_items(node_entry["items"])

    def fake_batch_agent(**kwargs):
        route = kwargs["route"]
        if route.agent_key == question_bank.QUESTION_DESIGNER_AGENT_KEY:
            requested_slots = list(kwargs["trusted_context"]["requested_slots"])
            items = []
            for slot in requested_slots:
                item = json.loads(json.dumps(raw_items[slot - 1], ensure_ascii=False))
                item["math_core_signature"] = f"{stage}-repaired-core-{slot:02d}"
                item["core_stem_id"] = f"CS-{stage}-{slot:02d}"
                items.append(item)
            value = {
                "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                "node_id": node_entry["node_id"],
                "graph_version": manifest["graph_version"],
                "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                "items": items,
                "batch_confidence": 0.94,
                "design_notes": [f"deterministic {stage} fixture"],
            }
        else:
            candidates = kwargs["untrusted_payload"]["items"]
            value = _reviewer_batch_response(
                module,
                node_entry["node_id"],
                manifest["graph_version"],
                candidates,
            )
        return (
            module.model_router.StructuredJSONResult(
                value=value,
                mode="json_schema",
                raw_response={"recorded_stage": stage, "agent_key": route.agent_key},
            ),
            f"recorded rendered prompt for {stage} {route.agent_key}",
        )

    with tempfile.TemporaryDirectory() as tmp:
        checkpoint_dir = Path(tmp) / "checkpoints"
        checkpoint_dir.mkdir()
        checkpoint = _incomplete_live_checkpoint(
            node_entry,
            manifest["graph_version"],
            local_round=local_round,
        )
        checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
        checkpoint["pending_repair_by_slot"] = {}
        checkpoint["stage_counters"] = {
            "local_item_rounds_by_slot": {str(slot): local_round for slot in range(1, 21)},
            "node_set_review_round": 0,
            "node_set_repair_rounds_by_slot": {},
            "cross_node_repair_rounds_by_slot": {},
        }
        checkpoint["repair_chain_events"] = []
        checkpoint["repair_chain_head_sha256"] = ""
        _seal_v12_incomplete_checkpoint(checkpoint)
        checkpoint_path = checkpoint_dir / f"{node_entry['node_id']}.json"
        checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
        kwargs = _build_live_node_test_kwargs(
            module,
            node=node,
            graph=graph,
            graph_version=manifest["graph_version"],
            checkpoint_dir=checkpoint_dir,
            max_rounds=3,
        )
        kwargs.update({
            "designer_contract": module._load_json(module.DESIGNER_CONTRACT_PATH),
            "reviewer_contract": module._load_json(module.REVIEWER_CONTRACT_PATH),
            "node_set_reviewer_contract": module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
            "designer_prompt_template": module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
            "reviewer_prompt_template": module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
            "node_set_reviewer_prompt_template": module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
        })
        with mock.patch.object(
            module.question_bank,
            "validate_external_question_bank_v12",
            return_value={"issues": []},
        ), mock.patch.object(
            module,
            "_node_level_repair_instructions",
            side_effect=fake_local_repair,
        ), mock.patch.object(
            module,
            "_node_set_semantic_repair_instructions",
            side_effect=fake_node_set_review,
        ), mock.patch.object(
            module,
            "_call_v12_batch_agent",
            side_effect=fake_batch_agent,
        ):
            result = module._build_live_node(**kwargs)
        saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    result_manifest = {
        "schema_version": question_bank.QUESTION_BANK_V12_SCHEMA_VERSION,
        "manifest_id": f"v12_stage_attempt_{stage}",
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "graph_version": manifest["graph_version"],
        "source_policy": "generated_from_project_graph_no_external_private_bank",
        "status": "draft_live_model",
        "nodes": [result],
    }
    return result, saved, module._runner_receipt_for_manifest(result_manifest)


class QuestionBankV12Test(unittest.TestCase):
    def _seed_manifest_into_conn(self, manifest: dict, conn: sqlite3.Connection) -> None:
        graph = _load_graph()
        for node in graph["nodes"]:
            summer = node.get("summer_execution", {})
            conn.execute(
                """
                insert or replace into graph_nodes(
                  id, name, stage, domain, priority, summer_mode, sequence_band,
                  prerequisites_json, unlocks_json, raw_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                db._node_values(node, summer),
            )
        db.seed_external_question_bank_v12(
            conn,
            manifest,
            project_root=PROJECT_ROOT,
            runner_receipt=_runner_receipt_for_manifest(manifest),
            commit=False,
        )

    def test_v12_candidate_packet_ranks_initial_review_by_evidence_role_not_slot_order(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_id = manifest["nodes"][0]["node_id"]
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                self._seed_manifest_into_conn(manifest, conn)

                packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="initial_review",
                )

                self.assertLessEqual(packet["candidate_count"], 8)
                self.assertGreaterEqual(packet["candidate_count"], 5)
                first = packet["candidates"][0]
                self.assertNotEqual(f"QB12-{node_id}-01", first["question_id"])
                self.assertIn(
                    first["slot_role"],
                    {
                        "necessary_condition",
                        "misconception_boundary",
                        "multi_representation",
                        "representation_translation",
                        "near_transfer",
                        "integrated_transfer",
                    },
                )
                self.assertNotIn("controlled_stretch", {item["slot_role"] for item in packet["candidates"]})
                self.assertNotIn("stretch_readiness_check", {item["slot_role"] for item in packet["candidates"]})
                for candidate in packet["candidates"]:
                    self.assertTrue(candidate["slot_role"])
                    self.assertTrue(candidate["evidence_role"])
                    self.assertTrue(candidate["kind"])
                    self.assertIn("difficulty_vector", candidate)
                    self.assertIn("age_floor", candidate)
                    self.assertIn("dignity_profile", candidate)
            finally:
                conn.close()

    def test_v12_candidate_packet_intents_gate_transfer_and_stretch_roles(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_id = manifest["nodes"][0]["node_id"]
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                self._seed_manifest_into_conn(manifest, conn)

                partial_packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="partial_unstable",
                )
                partial_roles = [item["slot_role"] for item in partial_packet["candidates"]]
                self.assertTrue(set(partial_roles) & {"same_structure_confirmation", "wrong_solution_repair", "standard_model", "standard_example"})
                self.assertFalse(set(partial_roles) & {"near_transfer", "integrated_transfer", "multi_representation", "stretch_readiness_check", "controlled_stretch"})

                transfer_packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="correct_narrow",
                    next_evidence_goal="near_transfer_retest",
                )
                transfer_roles = [item["slot_role"] for item in transfer_packet["candidates"]]
                self.assertTrue(set(transfer_roles[:4]) & {"near_transfer", "integrated_transfer", "multi_representation", "alternative_method"})
                self.assertNotIn("stretch_readiness_check", transfer_roles)

                unstable_stretch_packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="stable_ready",
                    learner_status="B",
                    prerequisite_ready=False,
                )
                self.assertNotIn("stretch_readiness_check", [item["slot_role"] for item in unstable_stretch_packet["candidates"]])

                stable_stretch_packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="stable_ready",
                    learner_status="A",
                    prerequisite_ready=True,
                )
                self.assertIn("stretch_readiness_check", [item["slot_role"] for item in stable_stretch_packet["candidates"]])
            finally:
                conn.close()

    def test_v12_candidate_packet_new_knowledge_teaching_anchors_on_model_context_not_repair_or_stretch(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_id = manifest["nodes"][0]["node_id"]
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                self._seed_manifest_into_conn(manifest, conn)

                packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="new_knowledge_teaching",
                    next_evidence_goal="teaching_context",
                    prerequisite_ready=True,
                )

                roles = [item["slot_role"] for item in packet["candidates"]]
                self.assertTrue(roles)
                self.assertIn(roles[0], {"essence_model", "standard_model", "standard_example", "core_representation"})
                self.assertNotIn("wrong_solution_repair", roles)
                self.assertNotIn("stretch_readiness_check", roles)
                self.assertNotIn("controlled_stretch", roles)
                self.assertEqual("new_knowledge_teaching", packet["selection_intent"])
            finally:
                conn.close()

    def test_legacy_candidate_packet_does_not_escalate_role_from_prose_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                graph_version = graph_runtime.GraphRuntimeService(conn, project_root=PROJECT_ROOT).current_graph_version()
                node_id = "M-G7-POS-NEG"
                base = db.find_question_for_node(conn, node_id)
                raw = dict(base["raw"])
                source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
                source.pop("slot_role", None)
                source.pop("evidence_role", None)
                raw["source"] = source
                raw["id"] = "QB11-LEGACY-PROSE-ROLE-GUARD"
                raw["item_version"] = question_bank.QUESTION_BANK_VERSION
                raw["source_type"] = "graph_generated"
                raw["node_id"] = node_id
                raw["kind"] = "general_check"
                raw["question_type"] = "general_check"
                raw["variant_level"] = "L2"
                raw["graph_version"] = graph_version
                raw["question_bank_version"] = question_bank.QUESTION_BANK_VERSION
                raw.pop("slot_role", None)
                raw.pop("evidence_role", None)
                raw["evidence_goal"] = "这是一段普通说明，里面有迁移、stretch、错解这些词，但它们不是结构化角色。"
                reviewer_run = db.record_agent_run(
                    conn,
                    agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    engine_type="deterministic",
                    session_id=None,
                    phase="test_question_quality_review",
                    trigger="legacy-prose-role-guard",
                    input_refs={"question_id": raw["id"]},
                    status="accepted",
                    confidence=1.0,
                    output={"review_status": "approved"},
                    commit=False,
                )
                db.upsert_question(conn, raw, reviewer_run_id=reviewer_run["id"])
                other_ids = [
                    row["id"]
                    for row in conn.execute(
                        "select id from question_items where node_id = ? and id <> ?",
                        (node_id, raw["id"]),
                    ).fetchall()
                ]

                packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=graph_version,
                    question_bank_version=question_bank.QUESTION_BANK_VERSION,
                    limit=8,
                    exclusions={"recent_question_ids": other_ids},
                    selection_intent="stable_ready",
                    learner_status="A",
                    prerequisite_ready=True,
                )

                self.assertEqual(1, packet["candidate_count"])
                candidate = packet["candidates"][0]
                self.assertEqual(raw["id"], candidate["question_id"])
                self.assertEqual("legacy_mainline", candidate["slot_role"])
                self.assertEqual("direct", candidate["evidence_role"])
                self.assertFalse(candidate["controlled_stretch"])
            finally:
                conn.close()

    def test_v12_process_node_unprompted_slots_require_structured_elicitation_mode_only(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        graph = _load_graph()
        node = next(item for item in graph["nodes"] if item["id"] == "M-BRIDGE-SOLUTION-HABIT")
        bad = _core_item(node, 9)
        bad.pop("elicitation_mode", None)
        bad["prompt"] = "读题后请写出关系、步骤、单位和检查，再给出答案。"

        errors = module._validate_chunk_generation_metadata([bad], node=node)

        self.assertIn(9, errors)
        self.assertTrue(any("elicitation_mode" in error for error in errors[9]))

        good = _core_item(node, 9)
        good["elicitation_mode"] = "unprompted_process_evidence"
        good["prompt"] = "读题后请写出关系、步骤、单位和检查，再给出答案。"

        self.assertEqual({}, module._validate_chunk_generation_metadata([good], node=node))

        prose_only_node = {
            **node,
            "id": "TEST-PROSE-ONLY",
            "taxonomy": {"concept_type": "concept"},
            "tags": [],
            "mastery_criteria": [
                "能写出关键步骤、完成检验、检查过程是否可靠。"
            ],
        }
        prose_only = _core_item({**node, "id": "TEST-PROSE-ONLY"}, 9)
        prose_only.pop("elicitation_mode", None)

        self.assertFalse(question_bank.v12_is_process_node(prose_only_node))
        self.assertEqual({}, module._validate_chunk_generation_metadata([prose_only], node=prose_only_node))

    def test_v12_root_node_slot13_uses_root_readiness_probe_and_non_root_keeps_prerequisite_probe(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        graph = _load_graph()
        root_node = next(item for item in graph["nodes"] if item["id"] == "M-BRIDGE-SOLUTION-HABIT")
        non_root = next(item for item in graph["nodes"] if item["id"] == "M-G7-EQ-DENOM")

        root_context = module._trusted_context(
            node=root_node,
            graph=graph,
            graph_version=_graph_version(),
            accepted_core_summaries=[],
            accepted_items=[],
            round_number=1,
            requested_slots=[13],
        )
        non_root_context = module._trusted_context(
            node=non_root,
            graph=graph,
            graph_version=_graph_version(),
            accepted_core_summaries=[],
            accepted_items=[],
            round_number=1,
            requested_slots=[13],
        )

        self.assertEqual("root_readiness_probe", root_context["requested_slot_roles"][0]["slot_role"])
        self.assertEqual("prerequisite_probe", non_root_context["requested_slot_roles"][0]["slot_role"])
        self.assertTrue(module._validate_requested_designer_slots_for_node(
            [{"slot": 13, "slot_role": "prerequisite_probe"}],
            requested_slots=[13],
            node=root_node,
        ))
        self.assertEqual([], module._validate_requested_designer_slots_for_node(
            [{"slot": 13, "slot_role": "root_readiness_probe"}],
            requested_slots=[13],
            node=root_node,
        ))

    def test_v12_evidence_goal_survives_external_conversion_and_candidate_metadata(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_id = manifest["nodes"][0]["node_id"]
        detailed_goal = "distinguish sign direction from absolute-value distance using a number-line comparison"
        manifest["nodes"][0]["items"][0]["evidence_goal"] = detailed_goal
        _refresh_v3_item_review_commitment(manifest["nodes"][0]["items"][0])
        manifest["nodes"][0]["node_review_artifact"] = _node_review_artifact(
            manifest["nodes"][0],
            provider_mode="live_model",
        )
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                self._seed_manifest_into_conn(manifest, conn)
                packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=node_id,
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=8,
                    selection_intent="general",
                )
                by_id = {candidate["question_id"]: candidate for candidate in packet["candidates"]}
                converted = db.get_question(conn, manifest["nodes"][0]["items"][0]["id"])
                self.assertEqual(detailed_goal, converted["raw"]["evidence_goal"])
                self.assertEqual(detailed_goal, converted["raw"]["source"]["evidence_goal"])
                self.assertEqual(detailed_goal, by_id[manifest["nodes"][0]["items"][0]["id"]]["evidence_goal"])
            finally:
                conn.close()

    def test_v12_ambiguous_context_semantics_are_rejected_by_recorded_reviewer_artifact(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        item = node_entry["items"][9]
        item["prompt"] = "小林绕操场往返一圈共用了6分钟，速度不变。问他跑一圈要多久？"
        item["expected_answer"] = "3分钟。"
        item["review_artifact"] = {
            **item["review_artifact"],
            "verdict": "needs_repair",
            "scores": {
                **item["review_artifact"]["scores"],
                "mathematical_correctness": 0.72,
                "answer_alignment": 0.65,
            },
            "reasons": ["recorded reviewer fixture: ambiguous context; 往返一圈 target quantity is not well-defined"],
            "repair_instructions": ["Replace with a self-contained context whose quantity and path are unambiguous."],
            "confidence": 0.91,
        }
        item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                with self.assertRaisesRegex(ValueError, "v12_missing_independent_review_artifact|v12_review_score_below_gate"):
                    self._seed_manifest_into_conn(manifest, conn)
            finally:
                conn.close()

    def test_v12_prompted_process_compliance_is_rejected_by_recorded_node_set_reviewer_artifact(self):
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        for slot in (9, 14, 19, 20):
            item = node_entry["items"][slot - 1]
            item["elicitation_mode"] = "unprompted_process_evidence"
            _refresh_v3_item_review_commitment(item, reset_semantic_evidence=True)
        artifact = _node_review_artifact(node_entry, provider_mode="live_model", rejected_slots={9})
        focal_review = next(
            review
            for review in artifact["constituent_reviews"]
            if 9 in review["reviewed_slots"]
        )
        focal_review["review_output"]["reasons"] = [
            "recorded node-set reviewer fixture: process slots only prove prompted checklist compliance, not unprompted evidence."
        ]
        focal_review["review_output"]["repair_instructions"][0]["exact_target_delta"] = {
            "dimension": "slot_fit",
            "from_value": "prompted_process_compliance",
            "to_value": "unprompted_process_evidence",
        }
        artifact["global_finalizer"]["global_review_output"]["reasons"] = list(
            focal_review["review_output"]["reasons"]
        )
        artifact["global_finalizer"]["global_review_output"]["repair_plan"][0]["exact_target_delta"] = {
            "dimension": "slot_fit",
            "from_value": "prompted_process_compliance",
            "to_value": "unprompted_process_evidence",
        }
        node_entry["node_review_artifact"] = artifact
        _recompute_v3_node_set_review(node_entry)

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                with self.assertRaisesRegex(ValueError, "v12_node_set_review_not_approved|v12_node_set_review_score_below_gate"):
                    self._seed_manifest_into_conn(manifest, conn)
            finally:
                conn.close()

    def test_v12_prompts_name_unprompted_process_root_readiness_and_ambiguous_context_policy(self):
        designer = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_designer_batch.v1.md").read_text(encoding="utf-8")
        reviewer = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_reviewer_batch.v1.md").read_text(encoding="utf-8")
        node_set = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_node_set_reviewer.v1.md").read_text(encoding="utf-8")

        for text in (designer, reviewer, node_set):
            self.assertIn("unprompted_process_evidence", text)
            self.assertIn("root_readiness_probe", text)
            self.assertIn("ambiguous context", text)

    def test_model_router_wall_clock_deadline_terminates_isolated_http_worker(self):
        route = model_router.ModelRoute(
            agent_key="question_designer_agent",
            task="question_candidate",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=0.05,
            model_params={},
        )

        class HangingProcess:
            def __init__(self):
                self.terminated = False
                self.killed = False
                self.join_calls: list[float | None] = []

            def join(self, timeout=None):
                self.join_calls.append(timeout)

            def is_alive(self):
                return not self.killed

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

        class SilentPipe:
            def poll(self, timeout):
                self.timeout = timeout
                return False

            def close(self):
                self.closed = True

        process = HangingProcess()
        pipe = SilentPipe()
        with mock.patch.object(model_router, "_spawn_http_json_process", return_value=(process, pipe)):
            with self.assertRaisesRegex(model_router.ModelCallError, "wall-clock timeout.*question_designer_agent:question_candidate"):
                model_router.call_responses(route, {"input": "hold"})

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(0.05, pipe.timeout)
        self.assertTrue(process.join_calls)
        self.assertLessEqual(max(timeout for timeout in process.join_calls if timeout is not None), model_router.HTTP_WORKER_TERMINATE_GRACE_SECONDS)

    def test_model_router_reaps_successful_exited_http_worker(self):
        route = model_router.ModelRoute(
            agent_key="question_designer_agent",
            task="question_candidate",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=0.05,
            model_params={},
        )

        class ExitedProcess:
            def __init__(self):
                self.join_calls: list[float | None] = []
                self.terminated = False
                self.killed = False

            def join(self, timeout=None):
                self.join_calls.append(timeout)

            def is_alive(self):
                return False

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

        class SuccessPipe:
            def poll(self, timeout):
                return True

            def recv(self):
                return {"ok": True, "raw": "{\"ok\": true}"}

            def close(self):
                self.closed = True

        process = ExitedProcess()
        pipe = SuccessPipe()
        with mock.patch.object(model_router, "_spawn_http_json_process", return_value=(process, pipe)):
            self.assertEqual({"ok": True}, model_router.call_responses(route, {"input": "done"}))

        self.assertTrue(process.join_calls)
        self.assertFalse(process.terminated)
        self.assertFalse(process.killed)

    def test_model_router_cleanup_terminates_successful_but_lingering_http_worker(self):
        route = model_router.ModelRoute(
            agent_key="question_reviewer_agent",
            task="question_review",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=0.05,
            model_params={},
        )

        class LingeringProcess:
            def __init__(self):
                self.join_calls: list[float | None] = []
                self.terminated = False
                self.killed = False

            def join(self, timeout=None):
                self.join_calls.append(timeout)

            def is_alive(self):
                return not self.killed

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

        class SuccessPipe:
            def poll(self, timeout):
                return True

            def recv(self):
                return {"ok": True, "raw": "{\"ok\": true}"}

            def close(self):
                self.closed = True

        process = LingeringProcess()
        pipe = SuccessPipe()
        with mock.patch.object(model_router, "_spawn_http_json_process", return_value=(process, pipe)):
            self.assertEqual({"ok": True}, model_router.call_chat_completions(route, {"messages": []}))

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertTrue(process.join_calls)
        self.assertLessEqual(max(timeout for timeout in process.join_calls if timeout is not None), model_router.HTTP_WORKER_TERMINATE_GRACE_SECONDS)

    def test_v12_batch_retry_uses_bounded_backoff_and_jitter_without_sleeping(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        route = model_router.ModelRoute(
            agent_key="question_designer_agent",
            task="question_candidate",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=30,
            model_params={},
        )
        contract = {
            "contract_key": "retry_unit",
            "response_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        }
        calls = {"count": 0}
        sleeps: list[float] = []

        def flaky_call(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                raise model_router.ModelCallError("HTTP 504 gateway timeout")
            return model_router.StructuredJSONResult(
                value={"ok": True},
                mode="json_schema",
                raw_response={"ok": True},
            )

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=flaky_call), \
             mock.patch.object(module, "_LIVE_RETRY_SLEEPER", side_effect=lambda seconds: sleeps.append(seconds)), \
             mock.patch.object(module, "_LIVE_RETRY_JITTER", side_effect=lambda attempt: 0.25):
            result, _ = module._call_v12_batch_agent(
                contract=contract,
                prompt_template="{trusted_context_json}\n{untrusted_payload_json}",
                route=route,
                trusted_context={},
                untrusted_payload={},
            )

        self.assertEqual({"ok": True}, result.value)
        self.assertEqual([2.25, 4.25], sleeps)
        self.assertEqual(3, calls["count"])

    def test_model_router_retryable_transport_disconnect_errors_are_classified(self):
        retryable_messages = [
            "Remote end closed connection without response",
            "Connection reset by peer",
            "connection aborted by remote host",
            "Broken pipe",
            "unexpected EOF during SSL read",
            "http.client.IncompleteRead: incomplete read",
            "Temporary failure in name resolution",
            "Name or service not known",
            "Connection refused",
        ]
        for message in retryable_messages:
            with self.subTest(message=message):
                self.assertTrue(
                    model_router.is_retryable_model_call_error(model_router.ModelCallError(message)),
                    message,
                )

        non_retryable_messages = [
            "model response is not valid JSON",
            "schema mismatch: missing required key",
            "JSON contract validation failed",
            "math validation rejected candidate",
            "HTTP 400 invalid json_schema",
        ]
        for message in non_retryable_messages:
            with self.subTest(message=message):
                self.assertFalse(
                    model_router.is_retryable_model_call_error(model_router.ModelCallError(message)),
                    message,
                )

    def test_v12_batch_retry_recovers_from_remote_disconnect_transport_error(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        route = model_router.ModelRoute(
            agent_key="question_designer_agent",
            task="question_candidate",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=30,
            model_params={},
        )
        contract = {
            "contract_key": "remote_disconnect_retry_unit",
            "response_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        }
        calls = {"count": 0}
        sleeps: list[float] = []

        def flaky_transport_call(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise model_router.ModelCallError("Remote end closed connection without response")
            return model_router.StructuredJSONResult(
                value={"ok": True},
                mode="json_schema",
                raw_response={"ok": True},
            )

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=flaky_transport_call), \
             mock.patch.object(module, "_LIVE_RETRY_SLEEPER", side_effect=lambda seconds: sleeps.append(seconds)), \
             mock.patch.object(module, "_LIVE_RETRY_JITTER", return_value=0):
            result, _ = module._call_v12_batch_agent(
                contract=contract,
                prompt_template="{trusted_context_json}\n{untrusted_payload_json}",
                route=route,
                trusted_context={},
                untrusted_payload={},
            )

        self.assertEqual({"ok": True}, result.value)
        self.assertEqual(2, calls["count"])
        self.assertEqual([2.0], sleeps)

    def test_v12_batch_retry_exhaustion_reports_attempt_elapsed_and_preserves_error_class(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        route = model_router.ModelRoute(
            agent_key="question_reviewer_agent",
            task="question_review",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=30,
            model_params={},
        )
        contract = {
            "contract_key": "retry_exhaustion_unit",
            "response_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        }

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=model_router.ModelCallError("HTTP 429 rate limit")), \
             mock.patch.object(module, "_LIVE_RETRY_SLEEPER", side_effect=lambda seconds: None), \
             mock.patch.object(module, "_LIVE_RETRY_JITTER", return_value=0), \
             mock.patch.object(module, "_LIVE_MONOTONIC", side_effect=[10.0, 13.5]):
            with self.assertRaisesRegex(
                model_router.ModelCallError,
                r"retry budget exhausted.*error_class=ModelCallError.*attempt=3.*elapsed=3\.50s.*HTTP 429",
            ):
                module._call_v12_batch_agent(
                    contract=contract,
                    prompt_template="{trusted_context_json}\n{untrusted_payload_json}",
                    route=route,
                    trusted_context={},
                    untrusted_payload={},
                )

    def test_v12_batch_retry_exhaustion_reports_remote_disconnect_metadata(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        route = model_router.ModelRoute(
            agent_key="question_reviewer_agent",
            task="question_review",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=30,
            model_params={},
        )
        contract = {
            "contract_key": "remote_disconnect_exhaustion_unit",
            "response_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        }

        with mock.patch.object(
            module.model_router,
            "call_structured_json",
            side_effect=model_router.ModelCallError("Remote end closed connection without response"),
        ), mock.patch.object(module, "_LIVE_RETRY_SLEEPER", side_effect=lambda seconds: None), \
             mock.patch.object(module, "_LIVE_RETRY_JITTER", return_value=0), \
             mock.patch.object(module, "_LIVE_MONOTONIC", side_effect=[20.0, 25.25]):
            with self.assertRaisesRegex(
                model_router.ModelCallError,
                r"retry budget exhausted.*error_class=ModelCallError.*attempt=3.*elapsed=5\.25s.*Remote end closed",
            ):
                module._call_v12_batch_agent(
                    contract=contract,
                    prompt_template="{trusted_context_json}\n{untrusted_payload_json}",
                    route=route,
                    trusted_context={},
                    untrusted_payload={},
                )

    def test_v12_batch_retry_does_not_backoff_or_retry_schema_errors(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        route = model_router.ModelRoute(
            agent_key="question_reviewer_agent",
            task="question_review",
            provider="gpt",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://example.invalid",
            api_key="test-key",
            timeout_seconds=30,
            model_params={},
        )
        contract = {
            "contract_key": "schema_error_unit",
            "response_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        }
        sleeps: list[float] = []

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=model_router.ModelJSONParseError("schema mismatch")) as call, \
             mock.patch.object(module, "_LIVE_RETRY_SLEEPER", side_effect=lambda seconds: sleeps.append(seconds)):
            with self.assertRaisesRegex(model_router.ModelJSONParseError, "schema mismatch"):
                module._call_v12_batch_agent(
                    contract=contract,
                    prompt_template="{trusted_context_json}\n{untrusted_payload_json}",
                    route=route,
                    trusted_context={},
                    untrusted_payload={},
                )

        self.assertEqual(1, call.call_count)
        self.assertEqual([], sleeps)

    def test_v12_asset_validator_accepts_recorded_node_with_twenty_reviewed_items(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        node_artifact = manifest["nodes"][0]["node_review_artifact"]

        self.assertEqual([], report["issues"])
        self.assertEqual(20, report["node_summaries"][0]["item_count"])
        self.assertEqual(14, report["node_summaries"][0]["node_local_mainline_count"])
        self.assertEqual("approved", node_artifact["node_ux_verdict"])
        self.assertGreaterEqual(
            len(node_artifact["instruction_voice_distribution"]),
            question_bank.V12_MIN_INSTRUCTION_VOICE_FAMILIES,
        )
        self.assertEqual(
            [],
            question_bank._v12_consecutive_voice_violation_slots(
                node_artifact["instruction_voice_distribution"],
            ),
        )
        for field in (
            "repetitive_instruction_clusters",
            "overloaded_slots",
            "notation_failure_slots",
            "dignity_failure_slots",
            "ux_rejected_slots",
        ):
            self.assertEqual([], node_artifact[field], field)
        self.assertEqual(question_bank.QUESTION_BANK_VERSION, "2026-07-08.bank.v11")

    def test_v12_completed_checkpoint_repair_chain_tamper_is_rejected(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        checkpoint = _v12_completed_checkpoint_with_repair_chain(
            module,
            node_entry,
            manifest["graph_version"],
        )
        checkpoint["repair_chain_events"][1]["new_candidate_sha256"] = "tampered-candidate"

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.model_router.ModelCallError, "repair chain"):
                module._read_completed_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph=graph,
                    graph_version=manifest["graph_version"],
                )

    def test_v12_incomplete_checkpoint_integrity_tamper_is_rejected_on_resume(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        checkpoint = _incomplete_live_checkpoint(
            node_entry,
            manifest["graph_version"],
            local_round=1,
        )
        checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
        checkpoint["pending_repair_by_slot"] = {}
        checkpoint["stage_counters"] = {
            "local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)},
            "node_set_review_round": 0,
            "node_set_repair_rounds_by_slot": {},
            "cross_node_repair_rounds_by_slot": {},
        }
        checkpoint["repair_chain_events"] = []
        checkpoint["repair_chain_head_sha256"] = ""
        _seal_v12_incomplete_checkpoint(checkpoint)
        checkpoint["accepted_slots"]["7"]["prompt"] = "tampered prompt after seal"

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.model_router.ModelCallError, "checkpoint integrity"):
                module._read_live_node_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph_version=manifest["graph_version"],
                )

    def test_v12_legacy_unsealed_incomplete_checkpoint_cannot_mint_activation_receipt(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        checkpoint = _incomplete_live_checkpoint(
            node_entry,
            manifest["graph_version"],
            local_round=1,
        )
        checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
        checkpoint["pending_repair_by_slot"] = {}
        checkpoint["stage_counters"] = {
            "local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)},
            "node_set_review_round": 0,
            "node_set_repair_rounds_by_slot": {},
            "cross_node_repair_rounds_by_slot": {},
        }
        checkpoint["repair_chain_events"] = []
        checkpoint["repair_chain_head_sha256"] = ""

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(
                     module,
                     "_node_set_semantic_repair_instructions",
                     return_value={
                         "repair_instructions": [],
                         "node_review_artifact": node_entry["node_review_artifact"],
                     },
                 ), self.assertRaisesRegex(module.model_router.ModelCallError, "--no-resume|fresh checkpoint"):
                module._build_live_node(**_build_live_node_test_kwargs(
                    module,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    checkpoint_dir=checkpoint_dir,
                    max_rounds=3,
                ))

    def test_v12_repair_artifact_stage_attempt_is_stage_local(self):
        module = _load_v12_build_module()

        result, saved, receipt = _run_v12_stage_repair_scenario(
            module,
            stage="node_set_semantic_repair",
        )

        repaired = next(item for item in result["items"] if item["slot"] == 7)
        self.assertEqual(3, saved["stage_counters"]["local_item_rounds_by_slot"]["7"])
        self.assertEqual("node_set_semantic_repair", repaired["designer_artifact"]["pipeline_stage"])
        self.assertEqual(1, repaired["designer_artifact"]["stage_attempt"])
        self.assertEqual("node_set_semantic_repair", repaired["review_artifact"]["pipeline_stage"])
        self.assertEqual(1, repaired["review_artifact"]["stage_attempt"])
        receipt_item = next(item for item in receipt["items"] if item["slot"] == 7)
        self.assertEqual(1, receipt_item["designer"]["stage_attempt"])
        self.assertEqual(1, receipt_item["reviewer"]["stage_attempt"])

    def test_v12_node_set_repair_episode_counts_once_per_slot_with_multiple_instructions(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        semantic_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "semantic core must be replaced",
            "repair_instructions": ["Replace the mathematical core."],
        }
        duplicate_instruction = {
            "reason": "v12_node_set_duplicate_group",
            "slot": 7,
            "slots": [7],
            "details": "duplicate wrapper/core group",
            "repair_instructions": ["Keep the retained slot and repair slot 7."],
        }
        second_episode_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "second node-set review still rejects slot 7",
            "repair_instructions": ["Replace with a third core."],
        }
        review_calls = {"count": 0}
        pre_repair_snapshots = []
        repaired_items = []

        def fake_node_set_review(**kwargs):
            review_calls["count"] += 1
            if review_calls["count"] == 1:
                return {
                    "repair_instructions": [semantic_instruction, duplicate_instruction],
                    "node_review_artifact": {"review_episode": 1},
                }
            if review_calls["count"] == 2:
                return {
                    "repair_instructions": [second_episode_instruction],
                    "node_review_artifact": {"review_episode": 2},
                }
            artifact = _node_review_artifact(kwargs["node_entry"], provider_mode="live_model")
            artifact.update({
                "pipeline_stage": "node_set_review",
                "stage_attempt": int(kwargs.get("stage_attempt") or review_calls["count"]),
            })
            for review in artifact.get("constituent_reviews") or []:
                review.update({
                    "pipeline_stage": "node_set_review",
                    "stage_attempt": artifact["stage_attempt"],
                })
            return {"repair_instructions": [], "node_review_artifact": artifact}

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint = _incomplete_live_checkpoint(
                node_entry,
                manifest["graph_version"],
                local_round=3,
            )
            checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
            checkpoint["pending_repair_by_slot"] = {}
            checkpoint["stage_counters"] = {
                "local_item_rounds_by_slot": {str(slot): 3 for slot in range(1, 21)},
                "node_set_review_round": 0,
                "node_set_repair_rounds_by_slot": {},
                "cross_node_repair_rounds_by_slot": {},
            }
            checkpoint["repair_chain_events"] = []
            checkpoint["repair_chain_head_sha256"] = ""
            _seal_v12_incomplete_checkpoint(checkpoint)
            checkpoint_path = checkpoint_dir / f"{node_entry['node_id']}.json"
            checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")

            def fake_process_live_slot_chunk(**kwargs):
                pre_repair_snapshots.append(json.loads(checkpoint_path.read_text(encoding="utf-8")))
                repaired = json.loads(json.dumps(node_entry["items"][6], ensure_ascii=False))
                repaired["math_core_signature"] = f"episode-count-repaired-core-{len(repaired_items) + 1}"
                repaired["core_stem_id"] = f"CS-episode-count-{len(repaired_items) + 1}"
                repaired["designer_artifact"] = {
                    **repaired["designer_artifact"],
                    "pipeline_stage": kwargs["pipeline_stage"],
                    "stage_attempt": kwargs["stage_attempt"],
                }
                repaired["review_artifact"] = {
                    **repaired["review_artifact"],
                    "pipeline_stage": kwargs["pipeline_stage"],
                    "stage_attempt": kwargs["stage_attempt"],
                    "candidate_sha256": question_bank.v12_external_candidate_sha256(repaired),
                }
                repaired_items.append(repaired)
                return {
                    "round_number": kwargs["round_number"],
                    "requested_slots": [7],
                    "accepted_by_slot": {7: repaired},
                    "rejected_slots": [],
                    "repair_instructions": [],
                }

            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(module, "_node_set_semantic_repair_instructions", side_effect=fake_node_set_review), \
                 mock.patch.object(module, "_process_live_slot_chunk", side_effect=fake_process_live_slot_chunk):
                result = module._build_live_node(**_build_live_node_test_kwargs(
                    module,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    checkpoint_dir=checkpoint_dir,
                    max_rounds=3,
                ))
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        self.assertGreaterEqual(len(pre_repair_snapshots), 2)
        first_episode = pre_repair_snapshots[0]
        self.assertEqual(1, first_episode["stage_counters"]["node_set_repair_rounds_by_slot"]["7"])
        self.assertEqual(
            [semantic_instruction, duplicate_instruction],
            first_episode["pending_repair_by_slot"]["7"],
        )
        first_rejections = [
            event for event in saved["repair_chain_events"]
            if event.get("stage") == "node_set_semantic_repair"
            and event.get("reason") in {"v12_node_set_semantic_review", "v12_node_set_duplicate_group"}
        ][:2]
        self.assertEqual(2, len(first_rejections))
        self.assertEqual([1, 1], [event["stage_attempt"] for event in first_rejections])
        self.assertEqual(1, repaired_items[0]["designer_artifact"]["stage_attempt"])
        self.assertEqual(1, repaired_items[0]["review_artifact"]["stage_attempt"])
        self.assertEqual(2, pre_repair_snapshots[1]["stage_counters"]["node_set_repair_rounds_by_slot"]["7"])
        self.assertEqual(2, saved["stage_counters"]["node_set_repair_rounds_by_slot"]["7"])
        self.assertEqual(20, len(result["items"]))

    def test_v12_validator_flags_declared_node_core_overuse_and_missing_independent_review_as_p1(self):
        manifest = _manifest(("M-G7-POS-NEG", "M-G7-COMPARE"), duplicate_core=True, missing_review=True)

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}

        self.assertIn("v12_core_reused_too_often", issue_types)
        self.assertIn("v12_missing_independent_review_artifact", issue_types)
        self.assertNotIn("v12_cross_node_math_core_reuse", issue_types)

    def test_v12_validator_requires_all_reviewer_scores_and_confidence_above_gate(self):
        manifest = _manifest()
        weak_item = manifest["nodes"][0]["items"][0]
        weak_item["review_artifact"]["scores"]["reasoning_signal"] = 0.79
        weak_item["review_artifact"]["scores"]["answer_alignment"] = 0.75
        weak_item["review_artifact"]["confidence"] = 0.79
        node_artifact = manifest["nodes"][0]["node_review_artifact"]
        node_artifact["distribution_scores"]["semantic_diversity"] = 0.79
        node_artifact["confidence"] = 0.87

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}

        self.assertIn("v12_review_score_below_gate", issue_types)
        self.assertIn("v12_review_confidence_below_gate", issue_types)
        self.assertIn("v12_node_set_review_score_below_gate", issue_types)
        self.assertIn("v12_node_set_review_confidence_below_gate", issue_types)

    def test_v12_validator_requires_complete_planner_difficulty_vector(self):
        manifest = _manifest()
        first = manifest["nodes"][0]["items"][0]
        second = manifest["nodes"][0]["items"][1]
        first["difficulty_vector"] = {}
        second["difficulty_vector"] = {
            "concept_demand": 2,
            "reasoning_steps": 3,
            "calculation_load": 5,
            "representation_demand": 2,
            "transfer_distance": 1,
        }

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        details = [issue["detail"] for issue in report["issues"] if issue["type"] == "v12_invalid_difficulty_vector"]

        self.assertTrue(any(first["id"] in detail and "concept_demand" in detail for detail in details))
        self.assertTrue(any(second["id"] in detail and "calculation_load" in detail for detail in details))

    def test_v12_validator_rejects_unknown_error_tags_and_chain_external_rollback(self):
        manifest = _manifest()
        first = manifest["nodes"][0]["items"][0]
        second = manifest["nodes"][0]["items"][1]
        first["target_error_tags"] = ["invented_tag"]
        second["rollback_candidates"] = ["M-G7-EQ-WORD"]

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}
        details = [issue["detail"] for issue in report["issues"]]

        self.assertIn("v12_unknown_target_error_tag", issue_types)
        self.assertIn("v12_illegal_rollback_candidate", issue_types)
        self.assertTrue(any(first["id"] in detail and "invented_tag" in detail for detail in details))
        self.assertTrue(any(second["id"] in detail and "M-G7-EQ-WORD" in detail for detail in details))

    def test_v12_model_response_contracts_have_explicit_closed_object_shapes(self):
        contract_paths = [
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_designer_batch.v1.json",
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_reviewer_batch.v1.json",
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_node_set_reviewer.v1.json",
        ]
        violations = []

        def walk(node, path):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                violations.append(path)
            properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            for key, value in properties.items():
                walk(value, f"{path}.properties.{key}")
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, f"{path}.items")

        for path in contract_paths:
            contract = json.loads(path.read_text(encoding="utf-8"))
            walk(contract["response_schema"], path.name)

        self.assertEqual([], violations)

    def test_v12_model_response_contracts_are_openai_strict_required_complete(self):
        contract_paths = [
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_designer_batch.v1.json",
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_reviewer_batch.v1.json",
            PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_node_set_reviewer.v1.json",
        ]
        violations = []

        def walk(node, path):
            if not isinstance(node, dict):
                return
            properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            if node.get("type") == "object" and properties:
                missing = sorted(set(properties) - set(node.get("required") or []))
                if missing:
                    violations.append({
                        "type": "openai_strict_missing_required_property",
                        "path": path,
                        "missing": missing,
                    })
            for key, value in properties.items():
                walk(value, f"{path}.properties.{key}")
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, f"{path}.items")

        for path in contract_paths:
            contract = json.loads(path.read_text(encoding="utf-8"))
            walk(contract["response_schema"], path.name)

        self.assertEqual([], violations)

    def test_v12_designer_contract_requires_planner_difficulty_dimensions(self):
        contract = json.loads((PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_designer_batch.v1.json").read_text(encoding="utf-8"))
        difficulty = contract["response_schema"]["properties"]["items"]["items"]["properties"]["difficulty_vector"]

        self.assertEqual(
            [
                "concept_demand",
                "reasoning_steps",
                "calculation_load",
                "representation_demand",
                "transfer_distance",
            ],
            difficulty["required"],
        )
        for key, bounds in {
            "concept_demand": (1, 4),
            "reasoning_steps": (1, 8),
            "calculation_load": (1, 4),
            "representation_demand": (1, 4),
            "transfer_distance": (0, 4),
        }.items():
            self.assertEqual("integer", difficulty["properties"][key]["type"])
            self.assertEqual(bounds[0], difficulty["properties"][key]["minimum"])
            self.assertEqual(bounds[1], difficulty["properties"][key]["maximum"])

    def test_v12_node_set_review_uses_question_reviewer_agent_phase_and_confidence_gate(self):
        contract = json.loads(
            (PROJECT_ROOT / "learning_system/agent_contracts/math_question_bank_v12_node_set_reviewer.v1.json").read_text(
                encoding="utf-8"
            )
        )
        schema = contract["response_schema"]

        self.assertEqual(question_bank.QUESTION_REVIEWER_AGENT_KEY, contract["agent_key"])
        self.assertIn("confidence", schema["required"])
        self.assertEqual({"type": "number", "minimum": 0, "maximum": 1}, schema["properties"]["confidence"])

    def test_v12_chunk_prompts_do_not_contradict_requested_slot_schema(self):
        designer_prompt = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_designer_batch.v1.md").read_text(encoding="utf-8")
        reviewer_prompt = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_reviewer_batch.v1.md").read_text(encoding="utf-8")

        self.assertIn("trusted_context.requested_slots", designer_prompt)
        self.assertIn("Return only items for those requested slots", designer_prompt)
        self.assertIn("trusted_context.requested_slots", reviewer_prompt)
        self.assertIn("Review only the submitted candidates for the requested slots", reviewer_prompt)

    def test_v12_node_set_review_prompt_is_expert_phase_contract_not_new_agent(self):
        prompt = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_node_set_reviewer.v1.md").read_text(encoding="utf-8")

        for phrase in [
            "existing `question_reviewer_agent` running the `node_set_review` phase",
            "Reconstruct the node boundary",
            "Cluster by givens, unknown, relation/equation structure, transformation path, error mechanism, answer path",
            "Reject impossible real-world contexts",
            "Return `approved` only when",
            "confidence",
            "(x-1)/3 + 2 = (x+5)/6",
        ]:
            self.assertIn(phrase, prompt)

    def test_v12_live_runner_uses_single_slot_chunks_with_four_worker_cap(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        designer_prompt = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_designer_batch.v1.md").read_text(encoding="utf-8")
        reviewer_prompt = (PROJECT_ROOT / "learning_system/prompts/math_question_bank_v12_reviewer_batch.v1.md").read_text(encoding="utf-8")

        self.assertEqual(1, module.V12_LIVE_CHUNK_SIZE)
        self.assertEqual(4, module.V12_LIVE_MAX_CHUNK_CONCURRENCY)
        self.assertEqual([[1], [2], [3], [4]], module._slot_chunks([1, 2, 3, 4], size=module.V12_LIVE_CHUNK_SIZE))
        with self.assertRaisesRegex(ValueError, "1-1"):
            module._chunk_response_schema(
                module._load_json(module.DESIGNER_CONTRACT_PATH),
                array_key="items",
                item_count=2,
            )
        for stale_phrase in [
            "design exactly 20 candidate items",
            "Create exactly one item for each slot",
            "Build a 20-row design table",
            "Compare all 20 prompts",
            "Review all candidates together",
            "Cluster the full batch",
        ]:
            self.assertNotIn(stale_phrase, designer_prompt)
            self.assertNotIn(stale_phrase, reviewer_prompt)

    def test_v12_trusted_context_includes_bounded_node_knowledge_packet(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        graph = _load_graph()
        nodes_by_id = {node["id"]: node for node in graph["nodes"]}
        node = nodes_by_id["M-G7-EQ-DENOM"]

        context = module._trusted_context(
            node=node,
            graph=graph,
            graph_version=_graph_version(),
            accepted_core_summaries=[],
            accepted_items=[],
            round_number=1,
            requested_slots=[1, 2, 3, 4, 5],
        )
        packet_text = json.dumps(context["node_knowledge_packet"], ensure_ascii=False, sort_keys=True)

        self.assertIn("每一项都要乘最小公倍数", packet_text)
        self.assertIn("漏乘没有分母的项", packet_text)
        self.assertIn("回分数通分和基础方程", packet_text)
        self.assertIn("M-G7-EQ-SOLVE", packet_text)
        self.assertIn("M-PRE-FRACTION-OPS", packet_text)
        self.assertIn("分数加减靠通分", packet_text)
        self.assertNotIn("M-G7-EQ-WORD", packet_text)
        self.assertLess(len(packet_text), 12000)

    def test_v12_converter_uses_reviewer_artifact_not_curated_seed_self_approval(self):
        manifest = _manifest()
        graph = _load_graph()
        node = next(item for item in graph["nodes"] if item["id"] == manifest["nodes"][0]["node_id"])
        core_item = manifest["nodes"][0]["items"][0]

        converted = question_bank.external_v12_item_to_question_item(manifest, node, core_item)

        self.assertEqual(question_bank.QUESTION_BANK_V12_VERSION, converted["item_version"])
        self.assertEqual("v12_independent_semantic_review", converted["source"]["reviewer_evidence"]["provenance_type"])
        self.assertNotEqual(question_bank.GRAPH_SEED_REVIEW_MANIFEST_ID, converted["source"].get("curated_manifest_id"))
        self.assertEqual("approved", question_bank.review_item_quality(converted)["review_status"])
        self.assertEqual(core_item["difficulty_vector"], converted["difficulty_vector"])

    def test_v12_converter_canonicalizes_external_semantic_identity_slugs(self):
        manifest = _manifest_with_semantic_identity_slugs()
        graph = _load_graph()
        node = next(item for item in graph["nodes"] if item["id"] == manifest["nodes"][0]["node_id"])
        external_item = manifest["nodes"][0]["items"][0]
        external_candidate_sha256 = question_bank.v12_external_candidate_sha256(external_item)

        converted = question_bank.external_v12_item_to_question_item(manifest, node, external_item)

        self.assertEqual("concept_boundary_slug_01", external_item["problem_family_id"])
        self.assertEqual("compare_method_slug_01", external_item["core_stem_id"])
        self.assertEqual(external_candidate_sha256, question_bank.v12_external_candidate_sha256(external_item))
        self.assertEqual("PF-V12-CONCEPT-BOUNDARY-SLUG-01", converted["problem_family_id"])
        self.assertEqual("CS-V12-COMPARE-METHOD-SLUG-01", converted["core_stem_id"])
        for surface in (
            converted["source"],
            converted["node_alignment"],
            converted["source"]["node_alignment"],
            converted["quality"],
        ):
            self.assertEqual(converted["problem_family_id"], surface["problem_family_id"])
            self.assertEqual(converted["core_stem_id"], surface["core_stem_id"])
        self.assertEqual("approved", converted["quality"]["review_status"])

    def test_v12_db_seed_helper_records_per_item_designer_and_reviewer_runs(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                graph = _load_graph()
                for node in graph["nodes"]:
                    summer = node.get("summer_execution", {})
                    conn.execute(
                        """
                        insert or replace into graph_nodes(
                          id, name, stage, domain, priority, summer_mode, sequence_band,
                          prerequisites_json, unlocks_json, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        db._node_values(node, summer),
                    )
                receipt_path = Path(tmp) / "math_question_bank_v12.json.runner_receipt.json"
                receipt_path.write_text(
                    json.dumps(_runner_receipt_for_manifest(manifest), ensure_ascii=False),
                    encoding="utf-8",
                )
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                node_receipt = receipt["nodes"][0]["node_set_review"]
                self.assertEqual(question_bank.QUESTION_REVIEWER_AGENT_KEY, node_receipt["agent_key"])
                self.assertEqual("node_global_finalizer", node_receipt["phase"])
                expected_shards = _v12_runtime_node_set_shards()
                constituent_receipts = node_receipt["constituent_reviews"]
                self.assertEqual(10, len(constituent_receipts))
                self.assertEqual(expected_shards, [review["reviewed_slots"] for review in constituent_receipts])
                self.assertEqual(
                    [review["review_output_sha256"] for review in constituent_receipts],
                    node_receipt["aggregation"]["constituent_hashes"],
                )
                self.assertEqual(10, node_receipt["aggregation"]["constituent_count"])
                self.assertEqual(list(range(1, 21)), node_receipt["aggregation"]["reviewed_slots"])
                self.assertEqual(
                    list(range(1, 21)),
                    [entry["slot"] for entry in node_receipt["semantic_evidence_coverage"]],
                )
                result = db.seed_external_question_bank_v12(
                    conn,
                    manifest,
                    project_root=PROJECT_ROOT,
                    runner_receipt_path=receipt_path,
                    commit=False,
                )
                self.assertEqual(20, result["questions_upserted"])
                self.assertEqual(20, result["designer_runs_recorded"])
                self.assertEqual(20, result["reviewer_runs_recorded"])
                self.assertEqual(1, result["node_set_review_runs_recorded"])
                self.assertEqual(20, conn.execute(
                    "select count(*) from question_review_records where item_version = ? and active_eligible = 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0])
                node_set_runs = conn.execute(
                    "select phase, input_refs_json, output_json, model_provider, model_name, model_params_json from agent_runs where agent_key = ? and phase = 'node_global_finalizer'",
                    (question_bank.QUESTION_REVIEWER_AGENT_KEY,),
                ).fetchall()
                self.assertEqual(1, len(node_set_runs))
                node_refs = db.json_load(node_set_runs[0]["input_refs_json"], {})
                node_output = db.json_load(node_set_runs[0]["output_json"], {})
                node_params = db.json_load(node_set_runs[0]["model_params_json"], {})
                self.assertTrue(node_refs.get("node_candidate_sha256"))
                self.assertEqual("approved", node_output.get("verdict"))
                self.assertTrue(node_output.get("constituent_reviews"))
                self.assertTrue(node_output.get("aggregation", {}).get("aggregate_sha256"))
                self.assertEqual("gpt", node_set_runs[0]["model_provider"])
                self.assertEqual("gpt-5.4", node_set_runs[0]["model_name"])
                self.assertEqual("recorded_model", node_params.get("trust_mode"))
                second_result = db.seed_external_question_bank_v12(
                    conn,
                    manifest,
                    project_root=PROJECT_ROOT,
                    runner_receipt_path=receipt_path,
                    commit=False,
                )
                self.assertEqual(0, second_result["node_set_review_runs_recorded"])
                self.assertEqual(1, conn.execute(
                    "select count(*) from agent_runs where agent_key = ? and phase = 'node_global_finalizer'",
                    (question_bank.QUESTION_REVIEWER_AGENT_KEY,),
                ).fetchone()[0])
                reviewer_runs = conn.execute(
                    "select phase, input_refs_json, output_json, model_provider, model_name, model_params_json from agent_runs where agent_key = ? and phase = 'question_quality_review'",
                    (question_bank.QUESTION_REVIEWER_AGENT_KEY,),
                ).fetchall()
                self.assertEqual(20, len(reviewer_runs))
                refs = db.json_load(reviewer_runs[0]["input_refs_json"], {})
                output = db.json_load(reviewer_runs[0]["output_json"], {})
                model_params = db.json_load(reviewer_runs[0]["model_params_json"], {})
                self.assertTrue(refs.get("candidate_sha256"))
                self.assertEqual("approved", output.get("review_status"))
                self.assertIn("scores", output)
                self.assertEqual("gpt", reviewer_runs[0]["model_provider"])
                self.assertEqual("gpt-5.5", reviewer_runs[0]["model_name"])
                self.assertEqual("live_model", model_params.get("origin_provider_mode"))
                self.assertEqual("recorded_model", model_params.get("trust_mode"))
                packet = question_bank.QuestionBankService.candidate_packet_for_node(
                    conn,
                    node_id=manifest["nodes"][0]["node_id"],
                    graph_version=manifest["graph_version"],
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    limit=1,
                )
                self.assertEqual(1, packet["candidate_count"])
                self.assertEqual(
                    {
                        "level",
                        "concept_demand",
                        "reasoning_steps",
                        "calculation_load",
                        "representation_demand",
                        "transfer_distance",
                    },
                    set(packet["candidates"][0]["difficulty_vector"]),
                )
                self.assertNotEqual({}, packet["candidates"][0]["difficulty_vector"])
            finally:
                conn.close()

    def test_v12_active_seed_rejects_tampered_ten_shard_hashes_and_coverage(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")

        def remove_constituent(receipt: dict) -> None:
            receipt["nodes"][0]["node_set_review"]["constituent_reviews"].pop()

        def tamper_constituent_hash(receipt: dict) -> None:
            receipt["nodes"][0]["node_set_review"]["constituent_reviews"][0]["review_output_sha256"] = "tampered"

        def remove_aggregate_hash(receipt: dict) -> None:
            receipt["nodes"][0]["node_set_review"]["aggregation"]["constituent_hashes"].pop()

        def remove_semantic_coverage(receipt: dict) -> None:
            receipt["nodes"][0]["node_set_review"]["semantic_evidence_coverage"].pop()

        scenarios = [
            ("missing_tenth_shard", remove_constituent, "node_set_review:constituent_reviews"),
            (
                "tampered_constituent_hash",
                tamper_constituent_hash,
                "node_set_review:constituent:0:review_output_sha256:mismatch",
            ),
            ("missing_aggregate_hash", remove_aggregate_hash, "node_set_review:aggregation:mismatch"),
            (
                "missing_semantic_coverage",
                remove_semantic_coverage,
                "node_set_review:semantic_evidence_coverage:mismatch",
            ),
        ]
        for scenario, mutate, expected_error in scenarios:
            with self.subTest(scenario=scenario):
                receipt = _runner_receipt_for_manifest(manifest)
                mutate(receipt)
                conn = sqlite3.connect(":memory:")
                conn.row_factory = sqlite3.Row
                try:
                    db.init_schema(conn)
                    with self.assertRaisesRegex(ValueError, expected_error):
                        db.seed_external_question_bank_v12(
                            conn,
                            manifest,
                            project_root=PROJECT_ROOT,
                            runner_receipt=receipt,
                            commit=False,
                        )
                finally:
                    conn.close()

    def test_v12_seed_accepts_external_semantic_identity_slugs_with_original_receipt_hashes(self):
        manifest = _manifest_with_semantic_identity_slugs()
        first_external_item = manifest["nodes"][0]["items"][0]
        first_external_hash = question_bank.v12_external_candidate_sha256(first_external_item)
        receipt = _runner_receipt_for_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                graph = _load_graph()
                for node in graph["nodes"]:
                    summer = node.get("summer_execution", {})
                    conn.execute(
                        """
                        insert or replace into graph_nodes(
                          id, name, stage, domain, priority, summer_mode, sequence_band,
                          prerequisites_json, unlocks_json, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        db._node_values(node, summer),
                    )
                seed_result = db.seed_external_question_bank_v12(
                    conn,
                    manifest,
                    project_root=PROJECT_ROOT,
                    runner_receipt=receipt,
                    commit=False,
                )
                self.assertEqual(20, seed_result["questions_upserted"])
                raw = db.json_load(
                    conn.execute(
                        "select raw_json from question_items where id = ?",
                        (first_external_item["id"],),
                    ).fetchone()["raw_json"],
                    {},
                )
                self.assertEqual("PF-V12-CONCEPT-BOUNDARY-SLUG-01", raw["problem_family_id"])
                self.assertEqual("CS-V12-COMPARE-METHOD-SLUG-01", raw["core_stem_id"])
                self.assertEqual(raw["problem_family_id"], raw["source"]["problem_family_id"])
                self.assertEqual(raw["core_stem_id"], raw["source"]["core_stem_id"])
                self.assertEqual(raw["problem_family_id"], raw["node_alignment"]["problem_family_id"])
                self.assertEqual(raw["core_stem_id"], raw["node_alignment"]["core_stem_id"])

                designer_refs = db.json_load(
                    conn.execute(
                        """
                        select input_refs_json
                        from agent_runs
                        where agent_key = ? and phase = 'question_design'
                          and trigger like ?
                        limit 1
                        """,
                        (question_bank.QUESTION_DESIGNER_AGENT_KEY, f"%:{first_external_item['id']}:%"),
                    ).fetchone()["input_refs_json"],
                    {},
                )
                reviewer_refs = db.json_load(
                    conn.execute(
                        """
                        select input_refs_json
                        from agent_runs
                        where agent_key = ? and phase = 'question_quality_review'
                          and trigger like ?
                        limit 1
                        """,
                        (question_bank.QUESTION_REVIEWER_AGENT_KEY, f"%:{first_external_item['id']}:%"),
                    ).fetchone()["input_refs_json"],
                    {},
                )
                self.assertEqual(first_external_hash, designer_refs["external_candidate_sha256"])
                self.assertEqual(first_external_hash, reviewer_refs["external_candidate_sha256"])
                self.assertEqual(first_external_hash, receipt["items"][0]["candidate_sha256"])

                staged = db.stage_question_bank_version(
                    conn,
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    graph_version=manifest["graph_version"],
                    manifest_id=manifest["manifest_id"],
                    manifest_sha256=question_bank.v12_canonical_manifest_sha256(manifest),
                    node_count=len(manifest["nodes"]),
                    item_count=sum(len(node["items"]) for node in manifest["nodes"]),
                    commit=False,
                )
                self.assertEqual("staged", staged["status"])
                with self.assertRaisesRegex(ValueError, "full-bank coverage"):
                    db.activate_question_bank_version(
                        conn,
                        question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                        expected_current_version=question_bank.QUESTION_BANK_VERSION,
                        reason="partial v12 must remain staged",
                        commit=False,
                    )
                self.assertEqual(question_bank.QUESTION_BANK_VERSION, db.get_active_question_bank_version(conn))
            finally:
                conn.close()

    def test_v12_db_seed_rejects_forged_recorded_review_artifacts_for_active_use(self):
        manifest = _manifest(provider_mode="recorded_model", status="draft_live_model")
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                graph = _load_graph()
                for node in graph["nodes"]:
                    summer = node.get("summer_execution", {})
                    conn.execute(
                        """
                        insert or replace into graph_nodes(
                          id, name, stage, domain, priority, summer_mode, sequence_band,
                          prerequisites_json, unlocks_json, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        db._node_values(node, summer),
                    )
                with self.assertRaisesRegex(ValueError, "v12_node_set_review_contract_identity_mismatch"):
                    db.seed_external_question_bank_v12(conn, manifest, project_root=PROJECT_ROOT, commit=False)
                self.assertEqual(0, conn.execute(
                    "select count(*) from question_review_records where item_version = ? and active_eligible = 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0])
            finally:
                conn.close()

    def test_v12_db_seed_requires_matching_independent_live_runner_receipt_for_active_use(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                graph = _load_graph()
                for node in graph["nodes"]:
                    summer = node.get("summer_execution", {})
                    conn.execute(
                        """
                        insert or replace into graph_nodes(
                          id, name, stage, domain, priority, summer_mode, sequence_band,
                          prerequisites_json, unlocks_json, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        db._node_values(node, summer),
                    )
                with self.assertRaisesRegex(ValueError, "runner receipt"):
                    db.seed_external_question_bank_v12(conn, manifest, project_root=PROJECT_ROOT, commit=False)

                wrong_receipt = _runner_receipt_for_manifest(manifest)
                wrong_receipt["canonical_manifest_sha256"] = "wrong"
                with self.assertRaisesRegex(ValueError, "runner receipt"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=wrong_receipt,
                        commit=False,
                    )
                self.assertEqual(0, conn.execute(
                    "select count(*) from question_review_records where item_version = ? and active_eligible = 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0])
            finally:
                conn.close()

    def test_v12_fresh_live_runner_receipt_requires_repair_chain_commitment_for_active_seed(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        receipt = module._runner_receipt_for_manifest(manifest)
        node_receipt = receipt["nodes"][0]

        self.assertFalse(node_receipt.get("reused_from_checkpoint"))
        self.assertTrue(node_receipt.get("completed_node_receipt_sha256"))
        self.assertTrue(node_receipt.get("repair_chain_hash"))

        missing_commitment = json.loads(json.dumps(receipt, ensure_ascii=False))
        missing_commitment["nodes"][0].pop("repair_chain_hash", None)
        tampered_commitment = json.loads(json.dumps(receipt, ensure_ascii=False))
        tampered_commitment["nodes"][0]["completed_node_receipt_sha256"] = "tampered-receipt"

        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                with self.assertRaisesRegex(ValueError, "repair_chain_hash"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=missing_commitment,
                        commit=False,
                    )
                with self.assertRaisesRegex(ValueError, "completed_node_receipt_sha256"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=tampered_commitment,
                        commit=False,
                    )
            finally:
                conn.close()

    def test_v12_build_script_uses_recorded_repair_loop_and_checkpoint_without_keys(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest()
        repaired_manifest = _manifest()
        first_item = repaired_manifest["nodes"][0]["items"][0]
        rejected_item = {**first_item, "prompt": "1+1=?", "solution_steps": ["算出2。"]}
        rejected_item["review_artifact"] = {
            "reviewer_run_id": "REVIEW-REJECTED",
            "verdict": "rejected",
            "candidate_sha256": question_bank.v12_external_candidate_sha256(rejected_item),
            "reasons": ["mechanical drill"],
            "reviewer_evidence": {**_reviewer_evidence("REVIEW-REJECTED"), "not_mechanical_drill": False},
        }
        repaired_node_entry = {
            "node_id": manifest["nodes"][0]["node_id"],
            "node_name": manifest["nodes"][0]["node_name"],
            "items": repaired_manifest["nodes"][0]["items"],
        }
        repaired_node_entry["node_review_artifact"] = _node_review_artifact(
            repaired_node_entry,
            provider_mode="live_model",
        )
        fixture = {
            "schema_version": "2026-07-12.math-qb-v12.recorded-fixture.v1",
            "graph_version": manifest["graph_version"],
            "nodes": [{
                "node_id": manifest["nodes"][0]["node_id"],
                "node_name": manifest["nodes"][0]["node_name"],
                "rounds": [
                    {"round": 1, "items": [rejected_item]},
                    {
                        "round": 2,
                        "items": repaired_node_entry["items"],
                        "node_review_artifact": repaired_node_entry["node_review_artifact"],
                    },
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fixture_path = tmp_path / "fixture.json"
            output_path = tmp_path / "math_question_bank_v12.json"
            checkpoint_dir = tmp_path / "checkpoints"
            fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")

            result = module.build_from_recorded_fixture(
                fixture_path=fixture_path,
                output_path=output_path,
                checkpoint_dir=checkpoint_dir,
                project_root=PROJECT_ROOT,
                node_ids=[manifest["nodes"][0]["node_id"]],
                max_rounds=3,
            )

            self.assertEqual(1, result["nodes_completed"])
            built = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(20, len(built["nodes"][0]["items"]))
            checkpoint_text = next(checkpoint_dir.glob("*.json")).read_text(encoding="utf-8").lower()
            self.assertIn("rounds_used", checkpoint_text)
            self.assertNotIn("api_key", checkpoint_text)
            self.assertNotIn("secret", checkpoint_text)

    def test_v12_live_runner_repairs_rejected_slots_and_persists_model_audit_without_secrets(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest()
        node_entry = manifest["nodes"][0]
        raw_items = _designer_batch_items(node_entry["items"])
        first_slot_rejected_once = {"done": False}
        calls = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            self.assertEqual(1, len(requested_slots))
            self.assertEqual(sorted(requested_slots), requested_slots)
            self.assertEqual(schema.get("properties", {}).get("items", schema.get("properties", {}).get("item_reviews", {})).get("maxItems"), len(requested_slots))
            self.assertFalse(retryable_errors_fallback)
            calls.append((route.agent_key, requested_slots, payload))
            if route.agent_key == "question_designer_agent":
                self.assertEqual("question_designer_agent", route.agent_key)
                chunk_items = [json.loads(json.dumps(raw_items[slot - 1])) for slot in requested_slots]
                if 1 in requested_slots and not first_slot_rejected_once["done"]:
                    chunk_items[0]["prompt"] = "1+1=?"
                    chunk_items[0]["math_core_signature"] = "too-mechanical-slot-1"
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": chunk_items,
                        "batch_confidence": 0.91,
                        "design_notes": [f"chunk {requested_slots}"],
                    },
                    mode="json_object",
                    raw_response={"designer": requested_slots},
                )
            self.assertEqual("question_reviewer_agent", route.agent_key)
            reject_slots = {1} if 1 in requested_slots and not first_slot_rejected_once["done"] else set()
            if reject_slots:
                first_slot_rejected_once["done"] = True
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                    reject_slots=reject_slots,
                ),
                mode="json_object",
                raw_response={"reviewer": requested_slots, "reject": sorted(reject_slots)},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=1,
                    resume=True,
                )

            self.assertEqual(1, result["nodes_completed"])
            self.assertEqual(1, result["effective_concurrency"])
            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            receipt_path = Path(result["runner_receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            first_item = built["nodes"][0]["items"][0]
            node_artifact = built["nodes"][0]["node_review_artifact"]
            self.assertEqual(node_entry["items"][0]["prompt"], first_item["prompt"])
            self.assertEqual("gpt", first_item["designer_artifact"]["model_provider"])
            self.assertEqual("gpt-5.5", first_item["designer_artifact"]["model_name"])
            self.assertEqual("gpt-5.5", first_item["review_artifact"]["model_name"])
            self.assertEqual("gpt-5.5", node_artifact["model_name"])
            self.assertEqual("json_object", first_item["review_artifact"]["structured_json_mode"])
            self.assertTrue(receipt_path.exists())
            self.assertEqual("live", receipt["runner_mode"])
            self.assertEqual("completed", receipt["status"])
            self.assertEqual(module._sha256_json(built), receipt["canonical_manifest_sha256"])
            self.assertEqual(20, receipt["item_count"])
            self.assertEqual("gpt", receipt["items"][0]["designer"]["model_provider"])
            self.assertEqual("gpt-5.5", receipt["items"][0]["reviewer"]["model_name"])
            self.assertEqual("gpt-5.5", receipt["nodes"][0]["node_set_review"]["model_name"])
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(first_item),
                receipt["items"][0]["candidate_sha256"],
            )
            receipt_text = receipt_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("api_key", receipt_text)
            self.assertNotIn("base_url", receipt_text)
            self.assertNotIn("secret", receipt_text)
            self.assertEqual([1], [slots for agent, slots, _ in calls if agent == "question_designer_agent"][-1])
            checkpoint_text = next((tmp_path / "checkpoints").glob("*.json")).read_text(encoding="utf-8").lower()
            self.assertIn("accepted_slots", checkpoint_text)
            self.assertIn("batch_raw_response_sha256", checkpoint_text)
            self.assertNotIn("api_key", checkpoint_text)
            self.assertNotIn("base_url", checkpoint_text)
            self.assertNotIn("secret", checkpoint_text)

    def test_v12_node_review_concurrency_defaults_to_one_even_when_slot_generation_uses_four(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest()
        node_entry = manifest["nodes"][0]
        active_node_reviews = {"count": 0, "max": 0}
        reviewed_shards = []
        lock = threading.Lock()

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                with lock:
                    active_node_reviews["count"] += 1
                    active_node_reviews["max"] = max(active_node_reviews["max"], active_node_reviews["count"])
                time.sleep(0.005)
                with lock:
                    active_node_reviews["count"] -= 1
                reviewed_slots = _reviewed_slots_from_payload(payload)
                reviewed_shards.append(reviewed_slots)
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": reviewed_slots},
                )
            requested_slots = _requested_slots_from_payload(payload)
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][requested_slots[0] - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )
            receipt = json.loads(Path(result["runner_receipt_path"]).read_text(encoding="utf-8"))

        self.assertEqual(4, result["slot_chunk_concurrency"])
        self.assertEqual(1, result["node_review_concurrency"])
        self.assertEqual(1, active_node_reviews["max"])
        self.assertEqual(_v12_runtime_node_set_shards(), reviewed_shards)
        self.assertTrue(all(len(shard) == V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE for shard in reviewed_shards))
        self.assertEqual(1, receipt["execution_policy"]["node_review_concurrency"])
        self.assertEqual(4, receipt["execution_policy"]["slot_chunk_concurrency"])
        self.assertEqual("2026-07-12.v12-live-runner-policy.v4", receipt["execution_policy"]["schema_version"])
        self.assertEqual("spawn_process_terminate_then_kill_on_wall_deadline", receipt["execution_policy"]["http_worker_isolation"])
        self.assertIn("http_429", receipt["execution_policy"]["retryable_error_classes"])
        self.assertIn("http_504", receipt["execution_policy"]["retryable_error_classes"])
        self.assertIn("timeout", receipt["execution_policy"]["retryable_error_classes"])
        self.assertIn("schema_validation", receipt["execution_policy"]["non_retryable_error_classes"])
        self.assertIn("compatibility_alias", receipt["execution_policy"]["legacy_effective_concurrency_field"])
        self.assertEqual("legacy_alias", result["effective_concurrency_compatibility"]["field_status"])

    def test_v12_node_review_concurrency_above_one_is_rejected_before_model_call(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node_entry.pop("node_review_artifact", None)
        model_calls = {"count": 0}

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            model_calls["count"] += 1
            self.fail(f"invalid activation concurrency reached model call: {route.agent_key}:{route.task}")

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
            for concurrency in (2, 3, 4):
                with self.subTest(node_review_concurrency=concurrency):
                    with self.assertRaisesRegex(ValueError, "node_review_concurrency exactly 1"):
                        module._node_set_semantic_repair_instructions(
                            node_entry=node_entry,
                            node=_load_graph()["nodes"][0],
                            graph=_load_graph(),
                            graph_version=manifest["graph_version"],
                            contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                            prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                            global_finalizer_contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
                            global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                            accepted_core_summaries=[],
                            node_review_concurrency=concurrency,
                        )

        self.assertEqual(0, model_calls["count"])

    def test_v12_live_runner_resume_skips_accepted_slot_checkpoint_after_crash(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest()
        node_entry = manifest["nodes"][0]
        first_run_slots = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            rendered = str(payload.get("instructions") or "")
            requested_slots = _requested_slots_from_payload(payload)
            first_run_slots.append((route.agent_key, requested_slots))
            self.assertIn('"requested_slots"', rendered)
            if requested_slots != [1]:
                raise RuntimeError("simulated crash after first accepted chunk checkpoint")
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][slot - 1] for slot in requested_slots]),
                        "batch_confidence": 0.92,
                        "design_notes": ["first chunk"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                with self.assertRaises(RuntimeError):
                    module.build_live(
                        output_path=tmp_path / "math_question_bank_v12.json",
                        checkpoint_dir=tmp_path / "checkpoints",
                        project_root=PROJECT_ROOT,
                        node_ids=[node_entry["node_id"]],
                        max_rounds=3,
                        max_concurrency=1,
                        resume=True,
                    )
            checkpoint = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(["1"], sorted(checkpoint["accepted_slots"], key=int))
            resume_slots = []

            def resume_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                    return module.model_router.StructuredJSONResult(
                        value=_node_set_global_finalizer_response_for_payload(payload),
                        mode="json_schema",
                        raw_response={"node_global_finalizer": "approved"},
                    )
                if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                    return module.model_router.StructuredJSONResult(
                        value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                        mode="json_schema",
                        raw_response={"node_set_review": "approved"},
                    )
                rendered = str(payload.get("instructions") or "")
                requested_slots = _requested_slots_from_payload(payload)
                resume_slots.append((route.agent_key, requested_slots))
                self.assertNotIn('"requested_slots": [\n    1\n  ]', rendered)
                self.assertNotEqual([1], requested_slots)
                self.assertEqual(1, len(requested_slots))
                if route.agent_key == "question_designer_agent":
                    return module.model_router.StructuredJSONResult(
                        value={
                            "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                            "node_id": node_entry["node_id"],
                            "graph_version": manifest["graph_version"],
                            "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                            "items": _designer_batch_items([node_entry["items"][slot - 1] for slot in requested_slots]),
                            "batch_confidence": 0.92,
                            "design_notes": ["resume batch"],
                        },
                        mode="json_schema",
                        raw_response={"designer": requested_slots},
                    )
                return module.model_router.StructuredJSONResult(
                    value=_reviewer_batch_response_for_payload(
                        module,
                        node_entry["node_id"],
                        manifest["graph_version"],
                        payload,
                    ),
                    mode="json_schema",
                    raw_response={"reviewer": requested_slots},
                )

            with mock.patch.object(module.model_router, "call_structured_json", side_effect=resume_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=1,
                    resume=True,
                )

            self.assertEqual(1, result["nodes_completed"])
            requested_on_resume = [slots for _, slots in resume_slots]
            self.assertNotIn([1], requested_on_resume)
            self.assertIn([2], requested_on_resume)

    def test_v12_live_runner_normalizes_model_item_ids_before_review_and_checkpoint(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-POS-NEG", "M-G7-COMPARE"), provider_mode="live_model", status="draft_live_model")
        calls = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                node_entry = manifest["nodes"][0] if '"id": "M-G7-POS-NEG"' in rendered else manifest["nodes"][1]
                calls.append((node_entry["node_id"], route.agent_key, [], payload))
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                node_entry = manifest["nodes"][0] if '"id": "M-G7-POS-NEG"' in rendered else manifest["nodes"][1]
                calls.append((node_entry["node_id"], route.agent_key, [], payload))
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            node_entry = manifest["nodes"][0] if '"id": "M-G7-POS-NEG"' in rendered else manifest["nodes"][1]
            calls.append((node_entry["node_id"], route.agent_key, requested_slots, payload))
            if route.agent_key == "question_designer_agent":
                items = []
                for slot in requested_slots:
                    item = json.loads(json.dumps(_designer_batch_items([node_entry["items"][slot - 1]])[0]))
                    item["id"] = "Q1"
                    items.append(item)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": items,
                        "batch_confidence": 0.93,
                        "design_notes": ["model reused Q1 but runtime owns ids"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            submitted = payload["input"]
            if isinstance(submitted, str):
                submitted_text = submitted
            else:
                submitted_text = json.dumps(submitted, ensure_ascii=False)
            self.assertNotIn('"id": "Q1"', submitted_text)
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node["node_id"] for node in manifest["nodes"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )

            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            ids = [item["id"] for node in built["nodes"] for item in node["items"]]
            self.assertEqual(2, result["nodes_completed"])
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn("QB12-M-G7-POS-NEG-01", ids)
            self.assertIn("QB12-M-G7-COMPARE-01", ids)
            checkpoint_ids = []
            for checkpoint_path in (tmp_path / "checkpoints").glob("*.json"):
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint_ids.extend(item["id"] for item in checkpoint.get("accepted_slots", {}).values())
            self.assertNotIn("Q1", checkpoint_ids)
            self.assertIn("QB12-M-G7-POS-NEG-01", checkpoint_ids)

    def test_v12_live_runner_normalizes_ineligible_controlled_stretch_before_review_hash_and_receipt(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-EQ-DENOM", "M-BRIDGE-CLOCK-ANGLE"), provider_mode="live_model", status="draft_live_model")
        original_by_node_slot = {
            (node["node_id"], int(item["slot"])): {
                "prompt": item["prompt"],
                "expected_answer": item["expected_answer"],
                "node_local_mainline": item["node_local_mainline"],
            }
            for node in manifest["nodes"]
            for item in node["items"]
        }
        reviewer_seen_slot19 = {}

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                node_entry = manifest["nodes"][0] if '"id": "M-G7-EQ-DENOM"' in rendered else manifest["nodes"][1]
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            node_entry = manifest["nodes"][0] if '"id": "M-G7-EQ-DENOM"' in rendered else manifest["nodes"][1]
            if route.agent_key == "question_designer_agent":
                items = []
                for slot in requested_slots:
                    item = json.loads(json.dumps(_designer_batch_items([node_entry["items"][slot - 1]])[0]))
                    if slot == 19:
                        item["controlled_stretch"] = True
                    items.append(item)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": items,
                        "batch_confidence": 0.93,
                        "design_notes": ["designer may mislabel controlled_stretch; runtime normalizes policy fields"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            if requested_slots == [19]:
                submitted_batch = _untrusted_candidate_batch_from_payload(payload)
                submitted_item = submitted_batch["items"][0]
                submitted_metadata = (
                    submitted_item.get("structured_metadata")
                    if isinstance(submitted_item.get("structured_metadata"), dict)
                    else {}
                )
                submitted_controlled_stretch = submitted_metadata.get(
                    "controlled_stretch",
                    submitted_item.get("controlled_stretch"),
                )
                if node_entry["node_id"] == "M-G7-EQ-DENOM":
                    self.assertIs(submitted_controlled_stretch, False)
                    reviewer_seen_slot19[node_entry["node_id"]] = False
                else:
                    self.assertIs(submitted_controlled_stretch, True)
                    reviewer_seen_slot19[node_entry["node_id"]] = True
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node["node_id"] for node in manifest["nodes"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )

            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            receipt = json.loads(Path(result["runner_receipt_path"]).read_text(encoding="utf-8"))
            by_node = {node["node_id"]: node for node in built["nodes"]}
            eq_item = by_node["M-G7-EQ-DENOM"]["items"][18]
            clock_item = by_node["M-BRIDGE-CLOCK-ANGLE"]["items"][18]
            self.assertEqual({"M-G7-EQ-DENOM": False, "M-BRIDGE-CLOCK-ANGLE": True}, reviewer_seen_slot19)
            self.assertFalse(eq_item["controlled_stretch"])
            self.assertTrue(clock_item["controlled_stretch"])
            self.assertEqual(original_by_node_slot[("M-G7-EQ-DENOM", 19)]["prompt"], eq_item["prompt"])
            self.assertEqual(original_by_node_slot[("M-G7-EQ-DENOM", 19)]["expected_answer"], eq_item["expected_answer"])
            self.assertEqual(original_by_node_slot[("M-G7-EQ-DENOM", 19)]["node_local_mainline"], eq_item["node_local_mainline"])
            normalization = eq_item["designer_artifact"].get("policy_normalization")
            self.assertEqual("controlled_stretch_forced_false", normalization.get("action"))
            self.assertEqual("selective_core", normalization.get("summer_execution_mode"))
            self.assertNotIn("policy_normalization", clock_item["designer_artifact"])
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(eq_item),
                eq_item["review_artifact"]["candidate_sha256"],
            )
            receipt_by_id = {item["item_id"]: item for item in receipt["items"]}
            self.assertEqual(
                question_bank.v12_external_candidate_sha256(eq_item),
                receipt_by_id[eq_item["id"]]["candidate_sha256"],
            )
            checkpoint_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "checkpoints").glob("*.json"))
            self.assertIn("controlled_stretch_forced_false", checkpoint_text)

    def test_v12_live_runner_actual_receipt_seeds_active_bank_with_canonical_manifest_digest(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": _reviewed_slots_from_payload(payload)},
                )
            requested_slots = _requested_slots_from_payload(payload)
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][requested_slots[0] - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["seed receipt integration"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )
            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            receipt_path = Path(result["runner_receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(question_bank.v12_canonical_manifest_sha256(built), receipt["canonical_manifest_sha256"])

            conn = sqlite3.connect(tmp_path / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                for node in _load_graph()["nodes"]:
                    conn.execute(
                        """
                        insert or replace into graph_nodes(
                          id, name, stage, domain, priority, summer_mode, sequence_band,
                          prerequisites_json, unlocks_json, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        db._node_values(node, node.get("summer_execution", {})),
                    )
                seed_result = db.seed_external_question_bank_v12(
                    conn,
                    built,
                    project_root=PROJECT_ROOT,
                    runner_receipt_path=receipt_path,
                    commit=False,
                )
                self.assertEqual(20, seed_result["questions_upserted"])
                self.assertEqual(20, conn.execute(
                    "select count(*) from question_review_records where item_version = ? and active_eligible = 1",
                    (question_bank.QUESTION_BANK_V12_VERSION,),
                ).fetchone()[0])
            finally:
                conn.close()

    def test_v12_completed_checkpoint_resume_marks_reused_node_receipt_without_model_call(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": _reviewed_slots_from_payload(payload)},
                )
            requested_slots = _requested_slots_from_payload(payload)
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][requested_slots[0] - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["checkpoint provenance"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                module.build_live(
                    output_path=tmp_path / "first.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )
            checkpoint = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual("completed_node_checkpoint_receipt", checkpoint["completed_node_receipt"]["artifact_role"])

            def no_model_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                raise AssertionError(f"completed checkpoint resume should not call model: {route.agent_key}:{route.task}")

            with mock.patch.object(module.model_router, "call_structured_json", side_effect=no_model_call):
                result = module.build_live(
                    output_path=tmp_path / "second.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )
            receipt = json.loads(Path(result["runner_receipt_path"]).read_text(encoding="utf-8"))
            self.assertTrue(receipt["nodes"][0]["reused_from_checkpoint"])
            self.assertEqual(
                checkpoint["completed_node_receipt"]["receipt_sha256"],
                receipt["nodes"][0]["completed_node_receipt_sha256"],
            )

    def test_v12_active_seed_rejects_per_item_agent_phase_contract_forgery(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        manifest["nodes"][0]["items"][0]["designer_artifact"]["phase"] = "question_design"
        _refresh_v3_item_review_commitment(manifest["nodes"][0]["items"][0])
        manifest["nodes"][0]["node_review_artifact"] = _node_review_artifact(
            manifest["nodes"][0],
            provider_mode="live_model",
        )
        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        self.assertTrue(any(
            issue["type"] == "v12_designer_contract_identity_mismatch"
            and issue["detail"].endswith(":phase")
            for issue in report["issues"]
        ))
        receipt = _runner_receipt_for_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                with self.assertRaisesRegex(ValueError, "v12_designer_contract_identity_mismatch"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=receipt,
                        commit=False,
                    )
            finally:
                conn.close()

    def test_v12_active_seed_rejects_receipt_contract_and_v3_ux_evidence_mismatch(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        receipt = _runner_receipt_for_manifest(manifest)
        receipt["items"][0]["reviewer"]["phase"] = "question_quality_review"
        missing_ux_receipt = _runner_receipt_for_manifest(manifest)
        missing_ux_receipt["nodes"][0]["node_set_review"].pop("node_ux_verdict", None)
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "learning.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                with self.assertRaisesRegex(ValueError, "reviewer:phase:mismatch"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=receipt,
                        commit=False,
                    )
                with self.assertRaisesRegex(ValueError, "node_set_review:node_ux_verdict:mismatch"):
                    db.seed_external_question_bank_v12(
                        conn,
                        manifest,
                        project_root=PROJECT_ROOT,
                        runner_receipt=missing_ux_receipt,
                        commit=False,
                    )
            finally:
                conn.close()

    def test_v12_node_set_review_route_defaults_to_gpt55_and_records_operator_override(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        with mock.patch.dict(os.environ, {}, clear=True):
            default_route = module.model_router.question_node_set_review_route()
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "gpt-9-test"}, clear=True):
            global_override_route = module.model_router.question_node_set_review_route()
        with mock.patch.dict(os.environ, {"AI_QUESTION_NODE_SET_REVIEW_MODEL": "gpt-5.4-review-override"}, clear=True):
            override_route = module.model_router.question_node_set_review_route()

        self.assertEqual("gpt-5.5", default_route.model)
        self.assertEqual("gpt-9-test", global_override_route.model)
        self.assertEqual("gpt-5.4-review-override", override_route.model)

    def test_v12_live_runner_retries_transient_batch_network_errors_without_losing_node(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        call_count = {"count": 0}

        def flaky_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            self.assertEqual(1, len(requested_slots))
            self.assertFalse(retryable_errors_fallback)
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise module.model_router.ModelCallError("HTTP 504 gateway timeout")
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][slot - 1] for slot in requested_slots]),
                        "batch_confidence": 0.92,
                        "design_notes": ["retried batch"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=flaky_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )

            self.assertEqual(1, result["nodes_completed"])
            self.assertEqual(1, result["effective_concurrency"])
            self.assertEqual(41, call_count["count"])
            self.assertTrue(next((tmp_path / "checkpoints").glob("*.json")).exists())

    def test_v12_live_runner_does_not_invent_cross_node_repair_from_declared_core_identity(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-POS-NEG", "M-G7-COMPARE"), provider_mode="live_model", status="draft_live_model")
        first_node, second_node = manifest["nodes"]
        conflicting_second_items = _designer_batch_items(second_node["items"])
        conflicting_second_items[0]["math_core_signature"] = first_node["items"][0]["math_core_signature"]
        conflicting_second_items[0]["core_stem_id"] = first_node["items"][0]["core_stem_id"]
        calls = []
        second_slot1_designer_prompts = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            is_designer = route.agent_key == "question_designer_agent"
            node_entry = first_node if f'"id": "{first_node["node_id"]}"' in rendered else second_node
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": node_entry["node_id"]},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            calls.append((node_entry["node_id"], "designer" if is_designer else "reviewer", rendered))
            self.assertEqual(1, len(requested_slots))
            if is_designer:
                if node_entry["node_id"] == second_node["node_id"] and requested_slots == [1]:
                    second_slot1_designer_prompts.append(rendered)
                use_conflict = (
                    node_entry["node_id"] == second_node["node_id"]
                    and 1 in requested_slots
                )
                chunk_items = [
                    json.loads(json.dumps((conflicting_second_items if use_conflict else _designer_batch_items(node_entry["items"]))[slot - 1]))
                    for slot in requested_slots
                ]
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": chunk_items,
                        "batch_confidence": 0.92,
                        "design_notes": ["conflict" if use_conflict else "clean"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots, "conflict": use_conflict},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[first_node["node_id"], second_node["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )

            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            report = question_bank.validate_external_question_bank_v12(built, _load_graph())
            p1_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}
            self.assertEqual(2, result["nodes_completed"])
            self.assertEqual(1, result["effective_concurrency"])
            self.assertNotIn("v12_cross_node_math_core_reuse", p1_types)
            self.assertEqual(1, len(second_slot1_designer_prompts))
            self.assertFalse(any(
                "v12_cross_node_math_core_reuse" in rendered or "independent_math_fingerprint" in rendered
                for rendered in second_slot1_designer_prompts
            ))
            self.assertEqual(
                built["nodes"][0]["items"][0]["math_core_signature"],
                built["nodes"][1]["items"][0]["math_core_signature"],
            )

    def test_v12_cross_node_duplicate_repair_is_driven_by_structured_node_set_rejection(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-EQ-DENOM", "M-G7-POS-NEG"), provider_mode="live_model", status="draft_live_model")
        first_node, second_node = manifest["nodes"]
        first_items = _designer_batch_items(first_node["items"])
        first_items[0]["prompt"] = r"解方程：\frac{x-1}{3}+2=\frac{x+5}{6}，写出清分母过程。"
        first_items[0]["expected_answer"] = "方程等价于 2(x-1)+12=x+5，解得 x=-5。"
        duplicate_second_items = _designer_batch_items(second_node["items"])
        duplicate_second_items[0]["prompt"] = r"小检测：\frac{x-1}{3}+2=\frac{x+5}{6}，请先乘最小公倍数再求 x。"
        duplicate_second_items[0]["expected_answer"] = "2(x-1)+12=x+5，所以 x=-5。"
        duplicate_second_items[0]["math_core_signature"] = "declared-different-core"
        duplicate_second_items[0]["core_stem_id"] = "CS-V12-declared-different-core"
        duplicate_second_items[0]["problem_family_id"] = "PF-V12-declared-different-family"
        clean_second_items = _designer_batch_items(second_node["items"])
        repaired_slots = set()
        structured_rejections = []
        legacy_repair_seen = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            node_entry = first_node if f'"id": "{first_node["node_id"]}"' in rendered else second_node
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": node_entry["node_id"]},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                reviewed_slots = _reviewed_slots_from_payload(payload)
                rejected_slots = []
                if (
                    node_entry["node_id"] == second_node["node_id"]
                    and 1 in reviewed_slots
                    and not structured_rejections
                ):
                    rejected_slots = [1]
                    structured_rejections.append(1)
                output = _node_set_review_response_for_payload(
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                    rejected_slots=rejected_slots,
                )
                if rejected_slots:
                    output["reasons"] = ["The node-set reviewer found a semantic duplicate of prior-node evidence."]
                    output["repair_instructions"][0]["exact_target_delta"]["from_value"] = (
                        "cross_node_duplicate_model_review"
                    )
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"node_set_review": reviewed_slots, "rejected_slots": rejected_slots},
                )
            requested_slots = _requested_slots_from_payload(payload)
            self.assertEqual(1, len(requested_slots))
            if route.agent_key == "question_designer_agent":
                slot = requested_slots[0]
                if "v12_cross_node_math_core_reuse" in rendered or "independent_math_fingerprint" in rendered:
                    legacy_repair_seen.append(slot)
                use_structured_repair = (
                    node_entry["node_id"] == second_node["node_id"]
                    and slot == 1
                    and (
                        "focal_review:slot:1" in rendered
                        or '"repair_scope": "global_slot_fit"' in rendered
                    )
                )
                if node_entry["node_id"] == first_node["node_id"]:
                    source_items = first_items
                elif use_structured_repair:
                    source_items = clean_second_items
                else:
                    source_items = duplicate_second_items
                if use_structured_repair:
                    repaired_slots.add(slot)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([source_items[slot - 1]]),
                        "batch_confidence": 0.92,
                        "design_notes": ["structured repair" if use_structured_repair else "initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots, "structured_repair": use_structured_repair},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[first_node["node_id"], second_node["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )

        self.assertEqual(2, result["nodes_completed"])
        self.assertEqual([1], structured_rejections)
        self.assertIn(1, repaired_slots)
        self.assertEqual([], legacy_repair_seen)

    def test_v12_live_runner_repairs_cross_chunk_node_core_reuse_before_failing_node(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        duplicate_slots = {1, 6, 11}
        repaired_slots = set()
        calls = []

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            calls.append((route.agent_key, requested_slots, rendered))
            self.assertEqual(1, len(requested_slots))
            if route.agent_key == "question_designer_agent":
                items = []
                for slot in requested_slots:
                    item = json.loads(json.dumps(_designer_batch_items([node_entry["items"][slot - 1]])[0]))
                    if slot in duplicate_slots and slot not in repaired_slots and "v12_core_reused_too_often" not in rendered:
                        item["math_core_signature"] = "cross-chunk-duplicate-core"
                        item["core_stem_id"] = "CS-V12-cross-chunk-duplicate-core"
                    else:
                        repaired_slots.add(slot)
                    items.append(item)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": items,
                        "batch_confidence": 0.92,
                        "design_notes": ["repair" if "v12_core_reused_too_often" in rendered else "initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=2,
                    resume=True,
                )

            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            report = question_bank.validate_external_question_bank_v12(built, _load_graph())
            p1_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}
            repair_designer_calls = [
                (slots, rendered)
                for agent, slots, rendered in calls
                if agent == "question_designer_agent" and "v12_core_reused_too_often" in rendered
            ]
            self.assertEqual(1, result["nodes_completed"])
            self.assertNotIn("v12_core_reused_too_often", p1_types)
            self.assertTrue(repair_designer_calls)
            self.assertTrue(any(slots == [11] for slots, _ in repair_designer_calls))

    def test_v12_rendered_notation_readiness_is_driven_by_structured_semantic_evidence(self):
        module = _load_v12_build_module()
        manifest = _manifest(("M-G7-EQ-DENOM",), provider_mode="live_model", status="draft_live_model")
        graph = _load_graph()
        node = next(item for item in graph["nodes"] if item["id"] == "M-G7-EQ-DENOM")
        node_entry = manifest["nodes"][0]
        item = node_entry["items"][1]
        item["prompt"] = r"已知 \frac{3}{5}x=12，求 x。"
        _refresh_v3_item_review_commitment(item)

        designer_item = _designer_batch_items([item])[0]
        self.assertEqual({}, module._validate_chunk_generation_metadata([designer_item], node=node))

        review = item["review_artifact"]
        review["semantic_evidence"]["rendered_notation_readiness"].update({
            "reason": "The child-visible surface contains unrendered authoring notation.",
            "child_visible_risks": ["unrendered authoring notation"],
        })
        _refresh_v3_item_review_commitment(item)
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        report = question_bank.validate_external_question_bank_v12(manifest, graph)
        self.assertTrue(any(
            issue["type"] == "v12_item_semantic_evidence_failed"
            and "semantic_evidence.rendered_notation_readiness:child_visible_risks_present" in issue["detail"]
            for issue in report["issues"]
        ))

    def test_v12_structured_semantic_approval_is_not_overridden_by_legacy_prompt_heuristics(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        graph = _load_graph()
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        item = node_entry["items"][0]
        item["prompt"] = "学校围绕“节约用水”记录一周用水变化。周三比周二少 3 吨，周二为 18 吨，周三是多少吨？"
        item["expected_answer"] = "周三用水 18-3=15 吨。"
        item["accepted_alternatives"] = ["15 吨", "18-3=15"]
        item["solution_steps"] = ["确定周三比周二少 3 吨。", "计算 18-3=15，并保留单位。"]
        _refresh_v3_item_review_commitment(item, reset_semantic_evidence=True)
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        report = question_bank.validate_external_question_bank_v12(manifest, graph)
        self.assertEqual([], [issue for issue in report["issues"] if issue["severity"] in {"P0", "P1"}])

        converted = question_bank.external_v12_item_to_question_item(manifest, node, item)
        self.assertEqual("approved", converted["quality"]["review_status"])
        self.assertEqual([], converted["quality"]["rejection_reasons"])

        failing_manifest = json.loads(json.dumps(manifest, ensure_ascii=False))
        failing_node = failing_manifest["nodes"][0]
        failing_item = failing_node["items"][0]
        failing_item["review_artifact"]["semantic_evidence"]["natural_self_contained_task"].update({
            "verdict": "fail",
            "score": 0.2,
            "reason": "The structured semantic reviewer found the task not self-contained.",
        })
        _refresh_v3_item_review_commitment(failing_item)
        failing_node["node_review_artifact"] = _node_review_artifact(failing_node, provider_mode="live_model")
        failing_report = question_bank.validate_external_question_bank_v12(failing_manifest, graph)
        self.assertTrue(any(
            issue["type"] == "v12_item_semantic_evidence_failed"
            and "semantic_evidence.natural_self_contained_task:verdict_not_pass" in issue["detail"]
            for issue in failing_report["issues"]
        ))

    def test_v12_live_runner_processes_slot_waves_so_later_slots_see_prior_accepted_summaries(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        designer_seen_prior_summary = {"slot5": False}

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": "approved"},
                )
            requested_slots = _requested_slots_from_payload(payload)
            rendered = str(payload.get("instructions") or "")
            self.assertEqual(1, len(requested_slots))
            slot = requested_slots[0]
            if route.agent_key == "question_designer_agent":
                if slot == 5 and "QB12-M-G7-POS-NEG-01" in rendered:
                    designer_seen_prior_summary["slot5"] = True
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][slot - 1]]),
                        "batch_confidence": 0.92,
                        "design_notes": [f"slot {slot}"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            if route.agent_key == "question_reviewer_agent":
                self.assertEqual("question_review", route.task)
                return module.model_router.StructuredJSONResult(
                    value=_reviewer_batch_response_for_payload(
                        module,
                        node_entry["node_id"],
                        manifest["graph_version"],
                        payload,
                    ),
                    mode="json_schema",
                    raw_response={"reviewer": requested_slots},
                )
            self.fail(f"unexpected route for v12 build: {route.agent_key}:{route.task}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )

        self.assertTrue(designer_seen_prior_summary["slot5"])

    def test_v12_node_set_reviewer_forces_repair_for_real_pilot_semantic_duplicates_and_bad_context(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        pilot = _pilot_eq_denom_manifest()
        clean = _manifest(("M-G7-EQ-DENOM",), provider_mode="live_model", status="draft_live_model")
        node_entry = pilot["nodes"][0]
        clean_entry = clean["nodes"][0]
        for item in node_entry["items"]:
            if not isinstance(item.get("interaction_schema"), dict):
                item["interaction_schema"] = {
                    "schema_version": question_bank.QUESTION_INTERACTION_SCHEMA_VERSION,
                    "type": "short_text",
                    "title": "写出答案和关键依据",
                    "allow_explanation": True,
                    "explanation_label": "补充说明",
                    "fields": [],
                    "choices": [],
                    "formula_label": "",
                    "placeholder": "写出结果，并说明关键依据。",
                }
        repaired_slots: set[int] = set()
        node_set_review_count = {"count": 0}
        node_set_review_counts_by_shard: dict[tuple[int, ...], int] = {}

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            rendered = str(payload.get("instructions") or "")
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                output = _node_set_global_finalizer_response_for_payload(payload)
                repair_slots = {int(item["slot"]) for item in output["repair_plan"]}
                if {10, 16}.issubset(repair_slots):
                    output["duplicate_groups"] = [{
                        "group_id": "pilot-duplicate-equation-core",
                        "slots": [2, 10, 16],
                        "reason": "same equation with wrapper changes",
                        "evidence_refs": ["focal_suspicion:pilot-duplicate-equation-core"],
                    }]
                for directive in output["repair_plan"]:
                    slot = int(directive["slot"])
                    if slot in {10, 16}:
                        directive["repair_scope"] = "global_duplicate"
                        directive["exact_target_delta"] = {
                            "dimension": "mathematical_core",
                            "from_value": "duplicate_equation_core",
                            "to_value": "distinct_node_local_core",
                        }
                    elif slot == 5:
                        directive["exact_target_delta"] = {
                            "dimension": "context_semantics",
                            "from_value": "invalid_or_ambiguous_context",
                            "to_value": "self_contained_valid_context",
                        }
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"node_global_finalizer": sorted(repair_slots)},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                self.assertEqual(question_bank.QUESTION_REVIEWER_AGENT_KEY, route.agent_key)
                reviewed_slots = _reviewed_slots_from_payload(payload)
                shard_key = tuple(reviewed_slots)
                initial_review = node_set_review_counts_by_shard.get(shard_key, 0) == 0
                node_set_review_counts_by_shard[shard_key] = node_set_review_counts_by_shard.get(shard_key, 0) + 1
                node_set_review_count["count"] += 1
                rejected_slots = [
                    slot for slot in (5, 10, 16)
                    if initial_review and slot in reviewed_slots
                ]
                output = _node_set_review_response_for_payload(
                    node_entry["node_id"],
                    pilot["graph_version"],
                    payload,
                    rejected_slots=rejected_slots,
                    confidence=0.93,
                )
                duplicate_slots = [2, 10, 16]
                if initial_review and set(reviewed_slots).intersection(duplicate_slots):
                    output["duplicate_suspicions"] = [{
                        "suspicion_id": "pilot-duplicate-equation-core",
                        "slots": duplicate_slots,
                        "reason": "same equation with wrapper changes",
                        "evidence_refs": [f"slot:{slot}" for slot in duplicate_slots],
                    }]
                    for focal_review in output["focal_slot_reviews"]:
                        if int(focal_review["slot"]) in duplicate_slots:
                            focal_review["duplicate_suspicion_ids"] = ["pilot-duplicate-equation-core"]
                if rejected_slots:
                    output["reasons"] = ["The structured node-set review found duplicate cores or an invalid context."]
                    for directive in output["repair_instructions"]:
                        slot = int(directive["slot"])
                        directive["exact_target_delta"] = {
                            "dimension": "mathematical_core" if slot in {10, 16} else "context_semantics",
                            "from_value": "duplicate_equation_core" if slot in {10, 16} else "invalid_or_ambiguous_context",
                            "to_value": "distinct_node_local_core" if slot in {10, 16} else "self_contained_valid_context",
                        }
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"node_set_rejected": rejected_slots},
                )
            requested_slots = _requested_slots_from_payload(payload)
            if route.agent_key == "question_designer_agent":
                slot = requested_slots[0]
                trusted_context = _json_section_from_payload(payload, "Trusted Context")
                use_repair = bool(trusted_context.get("accepted_repair_directives"))
                source = clean_entry if use_repair else node_entry
                if use_repair:
                    repaired_slots.add(slot)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": pilot["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([source["items"][slot - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["repair" if use_repair else "pilot"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots, "repair": use_repair},
                )
            if route.agent_key == "question_reviewer_agent":
                slot = requested_slots[0]
                return module.model_router.StructuredJSONResult(
                    value=_reviewer_batch_response_for_payload(
                        module,
                        node_entry["node_id"],
                        pilot["graph_version"],
                        payload,
                    ),
                    mode="json_schema",
                    raw_response={"reviewer": requested_slots},
                )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )

        self.assertEqual(1, result["nodes_completed"])
        self.assertGreaterEqual(node_set_review_count["count"], 2)
        self.assertLessEqual({5, 10, 16}, repaired_slots)
        self.assertGreaterEqual(len({2, 10, 16} & repaired_slots), 2)

    def test_v12_node_set_review_shard_failure_resumes_without_regenerating_accepted_slots(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        expected_shards = _v12_runtime_node_set_shards()
        self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE)
        self.assertEqual(10, len(expected_shards))
        failed_shard = expected_shards[-1]
        successful_shards = expected_shards[:-1]
        first_run_reviewed_shards: list[list[int]] = []

        def first_run_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                reviewed_slots = _reviewed_slots_from_payload(payload)
                first_run_reviewed_shards.append(reviewed_slots)
                if reviewed_slots == failed_shard:
                    raise module.model_router.ModelCallError("HTTP 504 gateway timeout")
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": reviewed_slots},
                )
            requested_slots = _requested_slots_from_payload(payload)
            self.assertEqual(1, len(requested_slots))
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][requested_slots[0] - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=first_run_call):
                with self.assertRaises(module.model_router.ModelCallError):
                    module.build_live(
                        output_path=tmp_path / "math_question_bank_v12.json",
                        checkpoint_dir=tmp_path / "checkpoints",
                        project_root=PROJECT_ROOT,
                        node_ids=[node_entry["node_id"]],
                        max_rounds=3,
                        max_concurrency=4,
                        resume=True,
                    )
            checkpoint = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text(encoding="utf-8"))
            partial_artifact = checkpoint["node"]["node_review_artifact"]
            saved_shards = [item["reviewed_slots"] for item in partial_artifact["constituent_reviews"]]
            self.assertEqual(successful_shards, first_run_reviewed_shards[:len(successful_shards)])
            failed_attempts = first_run_reviewed_shards[len(successful_shards):]
            self.assertEqual(module.LIVE_BATCH_NETWORK_ATTEMPTS, len(failed_attempts))
            self.assertTrue(all(shard == failed_shard for shard in failed_attempts))
            self.assertEqual(successful_shards, saved_shards)
            self.assertNotIn(failed_shard, saved_shards)

            resume_calls: list[tuple[str, list[int]]] = []

            def resume_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                    reviewed_slots = _reviewed_slots_from_payload(payload)
                    resume_calls.append(("node_set_review", reviewed_slots))
                    return module.model_router.StructuredJSONResult(
                        value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                        mode="json_schema",
                        raw_response={"node_set_review": reviewed_slots},
                    )
                if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                    resume_calls.append(("node_global_finalizer", []))
                    return module.model_router.StructuredJSONResult(
                        value=_node_set_global_finalizer_response_for_payload(payload),
                        mode="json_schema",
                        raw_response={"node_global_finalizer": "approved"},
                    )
                requested_slots = _requested_slots_from_payload(payload)
                resume_calls.append((route.agent_key, requested_slots))
                self.fail(f"resume should not regenerate or re-review accepted question slots: {route.agent_key}:{requested_slots}")

            with mock.patch.object(module.model_router, "call_structured_json", side_effect=resume_call):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )

            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))
            artifact = built["nodes"][0]["node_review_artifact"]
            self.assertEqual(1, result["nodes_completed"])
            for saved_shard in saved_shards:
                self.assertNotIn(("node_set_review", saved_shard), resume_calls)
            self.assertEqual(
                [("node_set_review", failed_shard)],
                [call for call in resume_calls if call[0] == "node_set_review"],
            )
            self.assertEqual(1, sum(call[0] == "node_global_finalizer" for call in resume_calls))
            self.assertEqual(10, len(artifact["constituent_reviews"]))
            self.assertEqual("v4_focal_evidence_plus_global_finalizer", artifact["aggregation"]["strategy"])

    def test_v12_node_set_review_payload_uses_compact_index_and_focal_full_items_once(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node_entry.pop("node_review_artifact", None)
        node_entry["items"][8]["elicitation_mode"] = "unprompted_process_evidence"
        node_entry["items"][8]["evidence_goal"] = "unprompted process evidence for relation, steps, units, and check"
        _refresh_v3_item_review_commitment(node_entry["items"][8], reset_semantic_evidence=True)
        injection_prefix = "CANDIDATE_INJECTION_DO_NOT_TRUST_"
        node_entry["items"][0]["prompt"] = injection_prefix + node_entry["items"][0]["prompt"]
        _refresh_v3_item_review_commitment(node_entry["items"][0])
        captured_payloads = []
        captured_outputs = []
        captured_schemas = []
        captured_global_payloads = []
        expected_shards = _v12_runtime_node_set_shards()
        self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE)

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                captured_payloads.append(payload)
                captured_schemas.append(json.loads(json.dumps(schema, ensure_ascii=False)))
                reviewed_slots = _reviewed_slots_from_payload(payload)
                output = _node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload)
                captured_outputs.append(output)
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"node_set_review": reviewed_slots},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                captured_global_payloads.append(payload)
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            self.fail(f"unexpected route: {route.agent_key}:{route.task}")

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
            module._node_set_semantic_repair_instructions(
                node_entry=node_entry,
                node=_load_graph()["nodes"][0],
                graph=_load_graph(),
                graph_version=manifest["graph_version"],
                contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                global_finalizer_contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
                global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                accepted_core_summaries=[{
                    "node_id": "M-OTHER",
                    "slot": 9,
                    "math_core_signature": "prior-process-core",
                    "evidence_goal": "prior detailed evidence goal",
                    "elicitation_mode": "unprompted_process_evidence",
                }],
            )

        self.assertEqual(10, len(captured_payloads))
        self.assertEqual(1, len(captured_global_payloads))
        self.assertEqual(expected_shards, [_reviewed_slots_from_payload(payload) for payload in captured_payloads])
        for payload, output, schema in zip(captured_payloads, captured_outputs, captured_schemas, strict=True):
            shard_trusted = _json_section_from_payload(payload, "Trusted Context")
            shard_untrusted = _json_section_from_payload(payload, "Untrusted Focal And Comparison Payload")
            reviewed_slots = _reviewed_slots_from_payload(payload)
            semantic_evidence_schema = schema["properties"]["focal_slot_reviews"]
            self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, shard_trusted["policy"]["node_set_review_shard_size"])
            self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, semantic_evidence_schema["maxItems"])
            self.assertEqual(reviewed_slots, [item["slot"] for item in shard_untrusted["items"]])
            self.assertEqual(reviewed_slots, [entry["slot"] for entry in output["focal_slot_reviews"]])
            self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, len(shard_untrusted["items"]))
        trusted = _json_section_from_payload(captured_payloads[0], "Trusted Context")
        untrusted = _json_section_from_payload(captured_payloads[0], "Untrusted Focal And Comparison Payload")
        rendered = str(captured_payloads[0].get("instructions") or "")
        self.assertLess(len(rendered), 60000)
        self.assertNotIn("whole_node_item_index", trusted)
        self.assertIn("whole_node_item_index", untrusted)
        self.assertNotIn("slot_roles", trusted)
        self.assertEqual("root_readiness_probe", trusted["slot_role_matrix"][12]["slot_role"])
        self.assertNotIn("accepted_cross_node_core_summaries", trusted)
        self.assertEqual("unprompted_process_evidence", untrusted["accepted_cross_node_core_summaries"][0]["elicitation_mode"])
        self.assertEqual("prior detailed evidence goal", untrusted["accepted_cross_node_core_summaries"][0]["evidence_goal"])
        self.assertNotIn("full_node_item_summaries", trusted)
        self.assertNotIn("full_node_item_summaries", untrusted)
        self.assertNotIn(injection_prefix, json.dumps(trusted, ensure_ascii=False))
        self.assertIn(injection_prefix, json.dumps(untrusted, ensure_ascii=False))
        self.assertEqual(20, len(untrusted["whole_node_item_index"]))
        self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, len(untrusted["items"]))
        self.assertNotIn("solution_steps", untrusted["whole_node_item_index"][0])
        self.assertIn("prompt_preview", untrusted["whole_node_item_index"][0])
        self.assertIn("expected_answer_preview", untrusted["whole_node_item_index"][0])
        indexed_slot9 = next(item for item in untrusted["whole_node_item_index"] if item["slot"] == 9)
        self.assertEqual("unprompted_process_evidence", indexed_slot9["elicitation_mode"])
        self.assertEqual("unprompted process evidence for relation, steps, units, and check", indexed_slot9["evidence_goal"])
        slot9_payload = next(
            _json_section_from_payload(payload, "Untrusted Focal And Comparison Payload")
            for payload in captured_payloads
            if 9 in _reviewed_slots_from_payload(payload)
        )
        focal_slot9 = next(item for item in slot9_payload["items"] if item["slot"] == 9)
        self.assertEqual("unprompted_process_evidence", focal_slot9["elicitation_mode"])
        self.assertEqual("unprompted process evidence for relation, steps, units, and check", focal_slot9["evidence_goal"])
        self.assertGreater(len(untrusted["whole_node_item_index"][0]["prompt_preview"]), 32)
        self.assertLessEqual(len(untrusted["whole_node_item_index"][0]["prompt_preview"]), 120)
        self.assertLessEqual(len(untrusted["whole_node_item_index"][0]["expected_answer_preview"]), 96)
        self.assertIn("prompt", untrusted["items"][0]["child_visible"])
        self.assertEqual(
            question_bank.normalize_question_interaction_schema(
                node_entry["items"][0].get("interaction_schema")
            ),
            untrusted["items"][0]["child_visible"]["interaction_schema"],
        )
        for hidden_key in ("answer_format", "expected_answer", "accepted_alternatives", "solution_steps"):
            self.assertNotIn(hidden_key, untrusted["items"][0]["child_visible"])
        self.assertLess(
            rendered.count(str(node_entry["items"][0]["prompt"])),
            2,
        )
        self.assertTrue(captured_payloads)
        self.assertTrue(all(
            payload.get("reasoning") == {"effort": "low"}
            for payload in captured_payloads
        ))
        global_rendered = str(captured_global_payloads[0].get("instructions") or "")
        global_trusted = _json_section_from_payload(
            captured_global_payloads[0],
            "Trusted Context",
        )
        global_untrusted = _json_section_from_payload(
            captured_global_payloads[0],
            "Untrusted Global Evidence Packet",
        )
        self.assertLess(len(global_rendered), 70000)
        self.assertEqual({"effort": "low"}, captured_global_payloads[0].get("reasoning"))
        self.assertIn("deterministic_ux_projection", global_trusted)
        self.assertEqual(20, len(global_untrusted["item_cards"]))
        self.assertIn("interaction_schema", global_untrusted["item_cards"][0]["child_visible"])
        self.assertIn("review_subject", global_untrusted["item_cards"][0])
        self.assertNotIn("item_semantic_summary", global_untrusted["item_cards"][0])

    def test_v12_node_set_review_trusted_slot_matrix_is_node_aware_for_root_and_non_root(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        root_manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        non_root_manifest = _manifest(node_ids=("M-G7-EQ-DENOM",), provider_mode="live_model", status="draft_live_model")
        captures: list[dict] = []

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                captures.append(_json_section_from_payload(payload, "Trusted Context"))
                reviewed_slots = _reviewed_slots_from_payload(payload)
                node_id = captures[-1]["node"]["id"]
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(
                        node_id,
                        root_manifest["graph_version"],
                        payload,
                    ),
                    mode="json_schema",
                    raw_response={"reviewed_slots": reviewed_slots},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                return module.model_router.StructuredJSONResult(
                    value=_node_set_global_finalizer_response_for_payload(payload),
                    mode="json_schema",
                    raw_response={"node_global_finalizer": "approved"},
                )
            self.fail(f"unexpected route: {route.agent_key}:{route.task}")

        with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
            for manifest in (root_manifest, non_root_manifest):
                node_entry = manifest["nodes"][0]
                node_entry.pop("node_review_artifact", None)
                node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
                module._node_set_semantic_repair_instructions(
                    node_entry=node_entry,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                    prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                    global_finalizer_contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
                    global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                    accepted_core_summaries=[],
                )

        root_context = next(item for item in captures if item["node"]["id"] == "M-BRIDGE-SOLUTION-HABIT")
        non_root_context = next(item for item in captures if item["node"]["id"] == "M-G7-EQ-DENOM")
        self.assertNotIn("slot_roles", root_context)
        self.assertNotIn("slot_roles", non_root_context)
        self.assertEqual("root_readiness_probe", root_context["slot_role_matrix"][12]["slot_role"])
        self.assertEqual("prerequisite_probe", non_root_context["slot_role_matrix"][12]["slot_role"])

    def test_v12_node_set_semantic_rejection_oracles_are_single_cause_and_node_aware(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        for item in node_entry["items"]:
            slot = int(item["slot"])
            item["slot_role"] = question_bank.v12_slot_role_for_node(node, slot)
            if slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS:
                item["elicitation_mode"] = question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
        self.assertEqual("root_readiness_probe", node_entry["items"][12]["slot_role"])

        cases = [
            ("prompted_process_compliance", 9, "slot_fit", "process prompt only proves checklist compliance"),
            ("ambiguous_context_semantics", 10, "context_semantics", "target quantity is contextually ambiguous"),
        ]
        for reason, rejected_slot, dimension, guidance in cases:
            with self.subTest(reason=reason):
                shard_reviews = []
                for shard_slots in _v12_runtime_node_set_shards():
                    rejected = [rejected_slot] if rejected_slot in shard_slots else []
                    output = _node_set_review_response(
                        node_entry,
                        manifest["graph_version"],
                        reviewed_slots=shard_slots,
                        rejected_slots=rejected,
                        confidence=0.93,
                    )
                    if rejected:
                        output["reasons"] = [guidance]
                        output["repair_instructions"][0]["exact_target_delta"] = {
                            "dimension": dimension,
                            "from_value": reason,
                            "to_value": "single_cause_semantic_repair",
                        }
                    result = module.model_router.StructuredJSONResult(
                        value=output,
                        mode="json_schema",
                        raw_response={"case": reason, "slots": shard_slots},
                    )
                    shard_reviews.append(module._node_set_review_constituent_artifact(
                        node_entry=node_entry,
                        reviewed_slots=shard_slots,
                        output=output,
                        contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                        prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                        rendered_prompt=f"rendered-{reason}-{shard_slots[0]}",
                        result=result,
                        route=module.model_router.question_node_set_review_route(),
                        stage_attempt=1,
                    ))

                global_output = _node_set_global_finalizer_output(
                    node_entry,
                    shard_reviews,
                    rejected_slots=[rejected_slot],
                )
                global_output["reasons"] = [guidance]
                global_output["repair_plan"][0]["exact_target_delta"] = {
                    "dimension": dimension,
                    "from_value": reason,
                    "to_value": "single_cause_semantic_repair",
                }
                global_result = module.model_router.StructuredJSONResult(
                    value=global_output,
                    mode="json_schema",
                    raw_response={"case": reason, "phase": "node_global_finalizer"},
                )
                global_lineage = module._global_finalizer_expected_lineage(node_entry, shard_reviews)
                global_artifact = module._node_set_global_finalizer_artifact(
                    node_entry=node_entry,
                    constituent_reviews=shard_reviews,
                    output=global_output,
                    contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
                    prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                    rendered_prompt=global_lineage["rendered_prompt"],
                    result=global_result,
                    route=module.model_router.question_node_global_finalizer_route(),
                    stage_attempt=1,
                )
                aggregate = module._aggregate_node_set_review_outputs(
                    node_entry=node_entry,
                    shard_reviews=shard_reviews,
                    global_finalizer_artifact=global_artifact,
                    stage_attempt=1,
                )

                self.assertEqual("needs_repair", aggregate["node_review_artifact"]["verdict"])
                self.assertEqual(1, len(aggregate["repair_instructions"]))
                self.assertEqual(rejected_slot, aggregate["repair_instructions"][0]["slot"])
                self.assertEqual(dimension, aggregate["repair_instructions"][0]["details"])
                self.assertEqual([guidance], aggregate["node_review_artifact"]["reasons"])
                self.assertEqual(
                    len(_v12_runtime_node_set_shards()),
                    len(aggregate["node_review_artifact"]["constituent_reviews"]),
                )

    def test_v12_pipeline_repairs_prompted_process_slot_after_node_set_rejection(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        for item in node_entry["items"]:
            slot = int(item["slot"])
            item["slot_role"] = question_bank.v12_slot_role_for_node(node, slot)
            if slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS:
                item["elicitation_mode"] = question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
        repaired_entry = json.loads(json.dumps(node_entry, ensure_ascii=False))
        repaired_entry["items"][8]["prompt"] = "小林把一段等式变形交给你检查。请判断第一处不成立的变形，并完成正确改写。"
        repaired_entry["items"][8]["math_core_signature"] = "process-slot-09-repaired-unprompted-core"
        designer_calls: list[int] = []
        reviewer_calls: list[int] = []
        node_set_calls = {"count": 0}
        repaired_slots: set[int] = set()
        rejected_once = {"done": False}

        def fake_call_structured_json(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_global_finalizer":
                output = _node_set_global_finalizer_response_for_payload(payload)
                for directive in output["repair_plan"]:
                    if int(directive["slot"]) == 9:
                        directive["exact_target_delta"] = {
                            "dimension": "slot_fit",
                            "from_value": "prompted_process_compliance",
                            "to_value": "unprompted_process_evidence",
                        }
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={
                        "node_global_finalizer": sorted(
                            int(item["slot"])
                            for item in output["repair_plan"]
                        )
                    },
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                node_set_calls["count"] += 1
                reviewed_slots = _reviewed_slots_from_payload(payload)
                rejected = [9] if 9 in reviewed_slots and not rejected_once["done"] else []
                if rejected:
                    rejected_once["done"] = True
                output = _node_set_review_response_for_payload(
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                    rejected_slots=rejected,
                    confidence=0.93,
                )
                if rejected:
                    output["reasons"] = ["slot 9 only proves prompted checklist compliance"]
                    output["repair_instructions"][0]["exact_target_delta"] = {
                        "dimension": "slot_fit",
                        "from_value": "prompted_process_compliance",
                        "to_value": "unprompted_process_evidence",
                    }
                return module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"node_set_review": _reviewed_slots_from_payload(payload), "rejected": rejected},
                )
            requested_slots = _requested_slots_from_payload(payload)
            self.assertEqual(1, len(requested_slots))
            slot = requested_slots[0]
            if route.agent_key == question_bank.QUESTION_DESIGNER_AGENT_KEY:
                designer_calls.append(slot)
                trusted_context = _json_section_from_payload(payload, "Trusted Context")
                use_repair = bool(trusted_context.get("accepted_repair_directives"))
                source = repaired_entry if use_repair else node_entry
                if use_repair:
                    repaired_slots.add(slot)
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([source["items"][slot - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["repair" if use_repair else "initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots, "repair": use_repair},
                )
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY:
                reviewer_calls.append(slot)
                return module.model_router.StructuredJSONResult(
                    value=_reviewer_batch_response_for_payload(
                        module,
                        node_entry["node_id"],
                        manifest["graph_version"],
                        payload,
                    ),
                    mode="json_schema",
                    raw_response={"reviewer": requested_slots},
                )
            self.fail(f"unexpected route {route.agent_key}:{route.task}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call_structured_json):
                result = module.build_live(
                    output_path=tmp_path / "math_question_bank_v12.json",
                    checkpoint_dir=tmp_path / "checkpoints",
                    project_root=PROJECT_ROOT,
                    node_ids=[node_entry["node_id"]],
                    max_rounds=3,
                    max_concurrency=4,
                    resume=True,
                )
            built = json.loads((tmp_path / "math_question_bank_v12.json").read_text(encoding="utf-8"))

        self.assertEqual(1, result["nodes_completed"])
        self.assertGreaterEqual(node_set_calls["count"], 2)
        self.assertGreaterEqual(designer_calls.count(9), 2)
        self.assertGreaterEqual(reviewer_calls.count(9), 2)
        self.assertEqual("process-slot-09-repaired-unprompted-core", built["nodes"][0]["items"][8]["math_core_signature"])

    def test_v12_completed_process_checkpoint_missing_elicitation_mode_is_rejected(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        node_entry["items"][8].pop("elicitation_mode", None)
        _refresh_v3_item_review_commitment(node_entry["items"][8], reset_semantic_evidence=True)
        node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")
        repair_chain_hash = _sha256_json({"repair_chain_events": [], "repair_chain_head_sha256": ""})
        checkpoint = {
            "node_id": node_entry["node_id"],
            "graph_version": manifest["graph_version"],
            "status": "completed",
            "rounds_used": 1,
            "rejected_rounds": 0,
            "issue_count": 0,
            "blocking_issue_types": [],
            "node": node_entry,
            "accepted_slots": {str(item["slot"]): item for item in node_entry["items"]},
            "source_node_candidate_sha256": question_bank.v12_node_candidate_sha256(node_entry),
            "repair_chain_events": [],
            "repair_chain_head_sha256": "",
            "repair_chain_hash": repair_chain_hash,
        }
        _reseal_v12_completed_checkpoint(module, checkpoint)

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.model_router.ModelCallError, "elicitation_mode|policy"):
                module._read_completed_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph=graph,
                    graph_version=manifest["graph_version"],
                )

    def test_v12_sealed_incomplete_process_checkpoint_missing_elicitation_mode_is_rejected_on_resume(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(node_ids=("M-BRIDGE-SOLUTION-HABIT",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        for item in node_entry["items"]:
            slot = int(item["slot"])
            item["slot_role"] = question_bank.v12_slot_role_for_node(node, slot)
            if slot in question_bank.V12_PROCESS_UNPROMPTED_SLOTS:
                item["elicitation_mode"] = question_bank.V12_UNPROMPTED_PROCESS_ELICITATION_MODE
            item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
        node_entry["items"][8].pop("elicitation_mode", None)
        node_entry["items"][8]["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(node_entry["items"][8])
        checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=1)
        checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
        checkpoint["pending_repair_by_slot"] = {}
        checkpoint["stage_counters"] = {"local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)}}
        checkpoint["repair_chain_events"] = []
        checkpoint["repair_chain_head_sha256"] = ""
        checkpoint["repair_chain_hash"] = _sha256_json({"repair_chain_events": [], "repair_chain_head_sha256": ""})
        _seal_v12_incomplete_checkpoint(checkpoint)

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.model_router.ModelCallError, "elicitation_mode|policy"):
                module._read_live_node_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph_version=manifest["graph_version"],
                )

    def test_v12_reviewer_contract_requires_all_v3_semantic_evidence_fields(self):
        module = _load_v12_build_module()
        contract = module._load_json(module.REVIEWER_CONTRACT_PATH)
        review_schema = contract["response_schema"]["properties"]["item_reviews"]["items"]
        score_schema = review_schema["properties"]["scores"]

        self.assertEqual(question_bank.V12_REVIEWER_CONTRACT_VERSION, contract["contract_version"])
        self.assertEqual(question_bank.V12_REVIEWER_PROMPT_VERSION_ID, contract["prompt_version_id"])
        self.assertEqual(question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION, contract["response_schema_version"])
        self.assertEqual(set(question_bank.V12_REVIEW_SCORE_KEYS), set(score_schema["required"]))
        self.assertEqual(set(question_bank.V12_REVIEW_SCORE_KEYS), set(score_schema["properties"]))
        self.assertIn("semantic_evidence", review_schema["required"])
        semantic_schema = review_schema["properties"]["semantic_evidence"]
        self.assertEqual(V12_V3_ITEM_SEMANTIC_FIELDS, set(semantic_schema["required"]))
        self.assertEqual(V12_V3_ITEM_SEMANTIC_FIELDS, set(semantic_schema["properties"]))

    def test_v12_node_set_contract_requires_all_v3_semantic_and_ux_fields(self):
        module = _load_v12_build_module()
        contract = module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH)

        self.assertEqual(question_bank.V12_NODE_SET_FOCAL_REVIEWER_CONTRACT_VERSION, contract["contract_version"])
        self.assertEqual(question_bank.V12_NODE_SET_FOCAL_REVIEWER_PROMPT_VERSION_ID, contract["prompt_version_id"])
        self.assertEqual(question_bank.V12_NODE_SET_FOCAL_REVIEWER_RESPONSE_SCHEMA_VERSION, contract["response_schema_version"])
        self.assertEqual(V12_V4_FOCAL_NODE_SET_OUTPUT_FIELDS, set(contract["response_schema"]["required"]))
        self.assertEqual(V12_V4_FOCAL_NODE_SET_OUTPUT_FIELDS, set(contract["response_schema"]["properties"]))
        focal_schema = contract["response_schema"]["properties"]["focal_slot_reviews"]["items"]
        self.assertEqual(
            {
                "slot",
                "item_id",
                "candidate_sha256",
                "item_review_semantic_evidence_sha256",
                "verdict",
                "slot_fit",
                "mathematical_correctness",
                "context_semantics",
                "prompt_answer_alignment",
                "duplicate_suspicion_ids",
                "evidence",
                "repair_direction",
            },
            set(focal_schema["required"]),
        )

    def test_v12_global_finalizer_model_contract_contains_only_semantic_judgment_delta(self):
        module = _load_v12_build_module()
        contract = module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH)
        model_fields = {
            "schema_version",
            "node_id",
            "graph_version",
            "question_bank_version",
            "semantic_evidence_version",
            "distribution_scores",
            "repetitive_instruction_clusters",
            "duplicate_groups",
            "confidence",
            "reasons",
            "repair_plan",
        }

        self.assertEqual(model_fields, set(contract["response_schema"]["required"]))
        self.assertEqual(model_fields, set(contract["response_schema"]["properties"]))
        self.assertNotIn("slot_evidence_coverage", contract["response_schema"]["properties"])
        self.assertNotIn("instruction_voice_distribution", contract["response_schema"]["properties"])
        self.assertNotIn("unprompted_slot_results", contract["response_schema"]["properties"])

    def test_v12_compact_global_judgment_cannot_forge_runtime_owned_reduction_fields(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node_artifact = node_entry["node_review_artifact"]
        shard_reviews = node_artifact["constituent_reviews"]
        compact = json.loads(json.dumps(
            node_artifact["global_finalizer"]["model_judgment_output"],
            ensure_ascii=False,
        ))
        runtime_owned_fields = {
            "slot_evidence_coverage",
            "instruction_voice_distribution",
            "overloaded_slots",
            "notation_failure_slots",
            "dignity_failure_slots",
            "ux_rejected_slots",
            "rejected_slots",
            "verdict",
            "node_ux_verdict",
        }
        self.assertTrue(runtime_owned_fields.isdisjoint(compact))
        authoritative = question_bank.v12_expand_global_model_judgment(
            node_entry,
            shard_reviews,
            compact,
            graph_version=manifest["graph_version"],
        )
        forged = {
            **compact,
            "slot_evidence_coverage": [{"slot": 99, "item_id": "FORGED"}],
            "instruction_voice_distribution": [{"instruction_voice_family": "forged", "slots": [1]}],
            "overloaded_slots": [1],
            "notation_failure_slots": [2],
            "dignity_failure_slots": [3],
            "ux_rejected_slots": [4],
            "rejected_slots": [5],
            "verdict": "needs_repair",
            "node_ux_verdict": "needs_repair",
        }

        expanded = question_bank.v12_expand_global_model_judgment(
            node_entry,
            shard_reviews,
            forged,
            graph_version=manifest["graph_version"],
        )

        for field in runtime_owned_fields:
            self.assertEqual(authoritative[field], expanded[field], field)
        self.assertEqual("approved", expanded["verdict"])
        self.assertEqual("approved", expanded["node_ux_verdict"])

    def test_v12_global_finalizer_checkpoint_rejects_tampered_or_expanded_model_judgment(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node_artifact = node_entry["node_review_artifact"]
        shard_reviews = node_artifact["constituent_reviews"]
        self.assertIsNotNone(module._trusted_node_set_global_finalizer(
            node_artifact,
            node_entry=node_entry,
            constituent_reviews=shard_reviews,
        ))

        stale_output_hash = json.loads(json.dumps(node_artifact, ensure_ascii=False))
        stale_output_hash["global_finalizer"]["model_judgment_output"]["reasons"].append("tampered")
        forged_hash = json.loads(json.dumps(node_artifact, ensure_ascii=False))
        forged_hash["global_finalizer"]["model_judgment_output_sha256"] = "0" * 64
        expanded_full_output = json.loads(json.dumps(node_artifact, ensure_ascii=False))
        expanded_finalizer = expanded_full_output["global_finalizer"]
        expanded_finalizer["model_judgment_output"] = json.loads(json.dumps(
            expanded_finalizer["global_review_output"],
            ensure_ascii=False,
        ))
        expanded_finalizer["model_judgment_output_sha256"] = _sha256_json(
            expanded_finalizer["model_judgment_output"]
        )

        for scenario, tampered in (
            ("tampered_model_judgment_output", stale_output_hash),
            ("tampered_model_judgment_hash", forged_hash),
            ("expanded_full_output_laundered_as_compact", expanded_full_output),
        ):
            with self.subTest(scenario=scenario):
                self.assertIsNone(module._trusted_node_set_global_finalizer(
                    tampered,
                    node_entry=node_entry,
                    constituent_reviews=shard_reviews,
                ))

    def test_v12_authoritative_node_set_policy_is_ten_exact_two_slot_shards(self):
        module = _load_v12_build_module()
        expected_shards = [list(range(start, start + 2)) for start in range(1, 21, 2)]
        contract = module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH)
        response_properties = contract["response_schema"]["properties"]

        self.assertEqual(V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE, question_bank.V12_NODE_SET_REVIEW_SHARD_SIZE)
        self.assertEqual(expected_shards, question_bank.v12_expected_node_set_review_shards())
        self.assertEqual(
            expected_shards,
            module._node_set_review_shards([{"slot": slot} for slot in range(1, 21)]),
        )
        self.assertEqual(
            V12_AUTHORITATIVE_NODE_SET_SHARD_SIZE,
            response_properties["focal_slot_reviews"]["maxItems"],
        )

    def test_v12_node_set_runtime_rejects_missing_or_nonfocal_shard_evidence(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        reviewed_slots = [1, 2]
        base_output = _node_set_review_response(
            node_entry,
            manifest["graph_version"],
            reviewed_slots=reviewed_slots,
        )
        contract = module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH)
        route = module.model_router.question_node_set_review_route()

        scenarios = {}
        missing = json.loads(json.dumps(base_output, ensure_ascii=False))
        missing["focal_slot_reviews"].pop()
        scenarios["missing_focal_slot"] = missing
        nonfocal = json.loads(json.dumps(base_output, ensure_ascii=False))
        nonfocal["focal_slot_reviews"].append(
            _node_set_review_response(
                node_entry,
                manifest["graph_version"],
                reviewed_slots=[3],
            )["focal_slot_reviews"][0]
        )
        scenarios["extra_nonfocal_slot"] = nonfocal

        for scenario, output in scenarios.items():
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(module.model_router.ModelJSONParseError, "coverage[_ ]mismatch"):
                    module._node_set_review_constituent_artifact(
                        node_entry=node_entry,
                        reviewed_slots=reviewed_slots,
                        output=output,
                        contract=contract,
                        prompt_template="node-set prompt",
                        rendered_prompt="rendered node-set prompt",
                        result=module.model_router.StructuredJSONResult(
                            value=output,
                            mode="json_schema",
                            raw_response={"scenario": scenario},
                        ),
                        route=route,
                    )

    def test_v12_node_set_runtime_accepts_low_scored_dimension_as_grounded_repair_evidence(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        reviewed_slots = [1, 2]
        output = _node_set_review_response(
            node_entry,
            manifest["graph_version"],
            reviewed_slots=reviewed_slots,
            rejected_slots=[2],
        )
        rejected_review = next(
            review for review in output["focal_slot_reviews"]
            if int(review["slot"]) == 2
        )
        rejected_review["prompt_answer_alignment"] = {
            "verdict": "fail",
            "score": 0.55,
            "reason": "The expected answer does not fully answer the child-visible task.",
        }

        artifact = module._node_set_review_constituent_artifact(
            node_entry=node_entry,
            reviewed_slots=reviewed_slots,
            output=output,
            contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
            prompt_template="node-set prompt",
            rendered_prompt="rendered node-set prompt",
            result=module.model_router.StructuredJSONResult(
                value=output,
                mode="json_schema",
                raw_response={"case": "grounded_repair_evidence"},
            ),
            route=module.model_router.question_node_set_review_route(),
        )

        self.assertEqual("needs_repair", artifact["review_output"]["verdict"])
        self.assertEqual([2], artifact["review_output"]["rejected_slots"])

        approved_output = _node_set_review_response(
            node_entry,
            manifest["graph_version"],
            reviewed_slots=reviewed_slots,
        )
        approved_review = next(
            review for review in approved_output["focal_slot_reviews"]
            if int(review["slot"]) == 2
        )
        approved_review["prompt_answer_alignment"]["score"] = 0.55
        with self.assertRaisesRegex(
            module.model_router.ModelJSONParseError,
            "prompt_answer_alignment:score_below_gate",
        ):
            module._node_set_review_constituent_artifact(
                node_entry=node_entry,
                reviewed_slots=reviewed_slots,
                output=approved_output,
                contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                prompt_template="node-set prompt",
                rendered_prompt="rendered node-set prompt",
                result=module.model_router.StructuredJSONResult(
                    value=approved_output,
                    mode="json_schema",
                    raw_response={"case": "approved_low_score"},
                ),
                route=module.model_router.question_node_set_review_route(),
            )

    def test_v12_live_slot_runtime_rejects_structured_semantic_failures_despite_high_math_scores(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest, node = _v3_process_manifest()
        base_item = manifest["nodes"][0]["items"][8]
        reviewer_contract = _reviewer_v3_contract(module)
        scenarios = [
            (
                "explicitly_coached_process",
                base_item["prompt"],
                {"process_target_disclosed": True},
            ),
            (
                "raw_latex_child_surface",
                r"已知 \frac{3}{5}x=12，求x并给出数学上正确的答案。",
                {"rendered_notation_readiness": {"child_visible_risks": ["unrendered authoring notation"]}},
            ),
            (
                "excessive_response_burden",
                "完成这道题，并提交所有中间推导、两种方法、逐步解释、反例、估算、代回和总结。",
                {"response_moves": ["solve", "explain", "compare", "validate"]},
            ),
        ]

        for scenario, prompt, semantic_override in scenarios:
            with self.subTest(scenario=scenario):
                candidate = json.loads(json.dumps(base_item, ensure_ascii=False))
                candidate["prompt"] = prompt

                def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                    if route.agent_key == question_bank.QUESTION_DESIGNER_AGENT_KEY:
                        return module.model_router.StructuredJSONResult(
                            value={
                                "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                                "node_id": candidate["node_id"],
                                "graph_version": manifest["graph_version"],
                                "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                                "items": _designer_batch_items([candidate]),
                                "batch_confidence": 0.95,
                                "design_notes": [scenario],
                            },
                            mode="json_schema",
                            raw_response={"designer": scenario},
                        )
                    reviewed_items = _untrusted_candidate_batch_from_payload(payload).get("items") or []
                    response = _reviewer_batch_response(
                        module,
                        candidate["node_id"],
                        manifest["graph_version"],
                        reviewed_items,
                    )
                    response["schema_version"] = question_bank.V12_REVIEWER_RESPONSE_SCHEMA_VERSION
                    review = response["item_reviews"][0]
                    review["semantic_evidence"] = _semantic_evidence_for_item(
                        reviewed_items[0],
                        version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
                        overrides=semantic_override,
                    )
                    return module.model_router.StructuredJSONResult(
                        value=response,
                        mode="json_schema",
                        raw_response={"reviewer": scenario},
                    )

                with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
                    result = module._process_live_slot_chunk(
                        node=node,
                        graph=graph,
                        graph_version=manifest["graph_version"],
                        requested_slots=[9],
                        round_number=1,
                        designer_contract=_designer_v3_contract(module),
                        reviewer_contract=reviewer_contract,
                        designer_prompt_template=module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
                        reviewer_prompt_template=module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                        accepted_core_summaries=[],
                        accepted_items=[],
                        repair_instructions=[],
                    )

                self.assertEqual({}, result["accepted_by_slot"])
                self.assertEqual([9], result["rejected_slots"])

    def test_v12_live_slot_runtime_rejects_any_false_required_reviewer_evidence_flag(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest, node = _v3_process_manifest()
        candidate = manifest["nodes"][0]["items"][8]
        required_flags = (
            "process_evidence_required",
            "graph_bound",
            "incoming_grade_7_ready",
            "diagnostic_structure",
            "not_mechanical_drill",
            "child_prompt_self_contained",
            "specific_expected_answer",
        )

        for false_flag in required_flags:
            with self.subTest(false_flag=false_flag):
                def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                    if route.agent_key == question_bank.QUESTION_DESIGNER_AGENT_KEY:
                        return module.model_router.StructuredJSONResult(
                            value={
                                "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                                "node_id": candidate["node_id"],
                                "graph_version": manifest["graph_version"],
                                "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                                "items": _designer_batch_items([candidate]),
                                "batch_confidence": 0.95,
                                "design_notes": [f"false reviewer evidence flag: {false_flag}"],
                            },
                            mode="json_schema",
                            raw_response={"designer": false_flag},
                        )
                    reviewed_items = _untrusted_candidate_batch_from_payload(payload).get("items") or []
                    response = _reviewer_batch_response(
                        module,
                        candidate["node_id"],
                        manifest["graph_version"],
                        reviewed_items,
                    )
                    review = response["item_reviews"][0]
                    review["reviewer_evidence"][false_flag] = False
                    return module.model_router.StructuredJSONResult(
                        value=response,
                        mode="json_schema",
                        raw_response={"reviewer": false_flag},
                    )

                with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
                    result = module._process_live_slot_chunk(
                        node=node,
                        graph=graph,
                        graph_version=manifest["graph_version"],
                        requested_slots=[9],
                        round_number=1,
                        designer_contract=_designer_v3_contract(module),
                        reviewer_contract=_reviewer_v3_contract(module),
                        designer_prompt_template=module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
                        reviewer_prompt_template=module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                        accepted_core_summaries=[],
                        accepted_items=[],
                        repair_instructions=[],
                    )

                self.assertEqual({}, result["accepted_by_slot"])
                self.assertEqual([9], result["rejected_slots"])
                self.assertEqual(1, len(result["repair_instructions"]))
                self.assertIn(
                    {
                        "flag": false_flag,
                        "code": "required_flag_must_be_true",
                        "actual": False,
                    },
                    result["repair_instructions"][0]["reviewer_evidence_errors"],
                )

    def test_v12_live_slot_runtime_rejects_wrong_reviewer_evidence_agent_key(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest, node = _v3_process_manifest()
        candidate = manifest["nodes"][0]["items"][8]

        def fake_batch_call(**kwargs):
            route = kwargs["route"]
            if route.agent_key == question_bank.QUESTION_DESIGNER_AGENT_KEY:
                output = {
                    "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                    "node_id": candidate["node_id"],
                    "graph_version": manifest["graph_version"],
                    "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                    "items": _designer_batch_items([candidate]),
                    "batch_confidence": 0.95,
                    "design_notes": ["wrong reviewer evidence agent regression"],
                }
            else:
                reviewed_items = kwargs["untrusted_payload"].get("items") or []
                output = _reviewer_batch_response(
                    module,
                    candidate["node_id"],
                    manifest["graph_version"],
                    reviewed_items,
                )
                output["item_reviews"][0]["reviewer_evidence"]["agent_key"] = "answer_analysis_agent"
            return (
                module.model_router.StructuredJSONResult(
                    value=output,
                    mode="json_schema",
                    raw_response={"test": "wrong_reviewer_evidence_agent"},
                ),
                "rendered-test-prompt",
            )

        with mock.patch.object(module, "_call_v12_batch_agent", side_effect=fake_batch_call):
            result = module._process_live_slot_chunk(
                node=node,
                graph=graph,
                graph_version=manifest["graph_version"],
                requested_slots=[9],
                round_number=1,
                designer_contract=_designer_v3_contract(module),
                reviewer_contract=_reviewer_v3_contract(module),
                designer_prompt_template=module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
                reviewer_prompt_template=module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                accepted_core_summaries=[],
                accepted_items=[],
                repair_instructions=[],
            )

        self.assertEqual({}, result["accepted_by_slot"])
        self.assertEqual([9], result["rejected_slots"])
        repair = result["repair_instructions"][0]
        self.assertEqual("reviewer_evidence_gate_failed", repair["reason"])
        self.assertIn(
            {
                "code": "reviewer_agent_key_mismatch",
                "field": "agent_key",
                "expected": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                "actual": "answer_analysis_agent",
            },
            repair["reviewer_evidence_errors"],
        )

    def test_v12_resume_revalidates_eq_denom_checkpoint_and_only_rebuilds_failed_evidence_slots(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        graph_version = _graph_version()
        node_id = "M-G7-EQ-DENOM"
        node = next(item for item in graph["nodes"] if item["id"] == node_id)
        fixture_manifest = _manifest(
            (node_id,),
            provider_mode="live_model",
            status="draft_live_model",
        )
        fixture_node = fixture_manifest["nodes"][0]
        expected_rebuilt_slots = {1, 2, 3, 5, 10, 11, 13, 16}
        for item in fixture_node["items"]:
            if int(item["slot"]) in expected_rebuilt_slots:
                item["review_artifact"]["reviewer_evidence"]["process_evidence_required"] = False
        # Evidence-contract migrations must have their own repair budget even
        # when the legacy item-generation budget was already exhausted.
        source_checkpoint = _incomplete_live_checkpoint(fixture_node, graph_version, local_round=3)
        _seal_v12_incomplete_checkpoint(source_checkpoint)
        source_items = {
            int(slot): json.loads(json.dumps(item, ensure_ascii=False))
            for slot, item in source_checkpoint["accepted_slots"].items()
        }
        unaffected_sha256 = {
            slot: _sha256_json(item)
            for slot, item in source_items.items()
            if slot not in expected_rebuilt_slots
        }
        rebuilt_calls: list[list[int]] = []

        def fake_rebuild_chunk(**kwargs):
            requested_slots = [int(slot) for slot in kwargs["requested_slots"]]
            rebuilt_calls.append(requested_slots)
            accepted = {}
            for slot in requested_slots:
                repaired = json.loads(json.dumps(source_items[slot], ensure_ascii=False))
                repaired["review_artifact"]["reviewer_evidence"]["process_evidence_required"] = True
                accepted[slot] = repaired
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": requested_slots,
                "accepted_by_slot": accepted,
                "rejected_slots": [],
                "repair_instructions": [],
            }

        def approve_node_set(**kwargs):
            return {
                "repair_instructions": [],
                "node_review_artifact": _node_review_artifact(
                    kwargs["node_entry"],
                    provider_mode="live_model",
                ),
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            copied_checkpoint_path = checkpoint_dir / f"{node_id}.json"
            copied_checkpoint_path.write_text(
                json.dumps(source_checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module, "_process_live_slot_chunk", side_effect=fake_rebuild_chunk), \
                 mock.patch.object(module, "_node_set_semantic_repair_instructions", side_effect=approve_node_set):
                result = module._build_live_node(**_build_live_node_test_kwargs(
                    module,
                    node=node,
                    graph=graph,
                    graph_version=graph_version,
                    checkpoint_dir=checkpoint_dir,
                    max_rounds=3,
                ))
            saved = json.loads(copied_checkpoint_path.read_text(encoding="utf-8"))

        self.assertEqual(expected_rebuilt_slots, {slot for call in rebuilt_calls for slot in call})
        self.assertTrue(all(len(call) == 1 for call in rebuilt_calls))
        self.assertEqual("completed", saved["status"])
        self.assertTrue(all(int(round_number) == 3 for round_number in saved["slot_rounds"].values()))
        self.assertEqual(
            {str(slot): 1 for slot in sorted(expected_rebuilt_slots)},
            saved["stage_counters"]["evidence_contract_repair_rounds_by_slot"],
        )
        result_by_slot = {int(item["slot"]): item for item in result["items"]}
        self.assertEqual(20, len(result_by_slot))
        for slot, item_sha256 in unaffected_sha256.items():
            self.assertEqual(item_sha256, _sha256_json(result_by_slot[slot]))
        for slot in expected_rebuilt_slots:
            self.assertTrue(
                result_by_slot[slot]["review_artifact"]["reviewer_evidence"]["process_evidence_required"]
            )

    def test_v12_evidence_contract_repair_budget_is_independent_and_bounded(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        graph_version = _graph_version()
        node_id = "M-G7-EQ-DENOM"
        node = next(item for item in graph["nodes"] if item["id"] == node_id)
        manifest = _manifest((node_id,), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node_entry["items"][0]["review_artifact"]["reviewer_evidence"]["process_evidence_required"] = False
        checkpoint = _incomplete_live_checkpoint(node_entry, graph_version, local_round=3)
        _seal_v12_incomplete_checkpoint(checkpoint)
        attempts: list[dict] = []
        evidence_repair = {
            "slot": 1,
            "slots": [1],
            "reason": "reviewer_evidence_gate_failed",
            "reviewer_evidence_errors": [{
                "flag": "process_evidence_required",
                "code": "required_flag_must_be_true",
                "actual": False,
            }],
            "repair_instructions": ["Regenerate with a complete independent reviewer evidence contract."],
        }

        def reject_evidence_repair(**kwargs):
            attempts.append(kwargs)
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [1],
                "accepted_by_slot": {},
                "rejected_slots": [1],
                "repair_instructions": [evidence_repair],
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint_path = checkpoint_dir / f"{node_id}.json"
            checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(module, "_process_live_slot_chunk", side_effect=reject_evidence_repair):
                with self.assertRaisesRegex(ValueError, "exhausted repair rounds"):
                    module._build_live_node(**_build_live_node_test_kwargs(
                        module,
                        node=node,
                        graph=graph,
                        graph_version=graph_version,
                        checkpoint_dir=checkpoint_dir,
                        max_rounds=2,
                    ))
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        self.assertEqual(2, len(attempts))
        self.assertEqual(["evidence_contract_repair", "evidence_contract_repair"], [
            attempt["pipeline_stage"] for attempt in attempts
        ])
        self.assertEqual([1, 2], [attempt["stage_attempt"] for attempt in attempts])
        self.assertEqual(3, saved["slot_rounds"]["1"])
        self.assertEqual(2, saved["stage_counters"]["evidence_contract_repair_rounds_by_slot"]["1"])

    def test_v12_completed_eq_denom_manifest_has_twenty_unique_cores_and_no_blocking_issues(self):
        manifest = _manifest(
            ("M-G7-EQ-DENOM",),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = manifest["nodes"][0]
        cores = [str(item.get("math_core_signature") or "") for item in node_entry["items"]]
        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        blocking = [issue for issue in report["issues"] if issue.get("severity") in {"P0", "P1"}]

        self.assertEqual(20, len(node_entry["items"]))
        self.assertTrue(all(cores))
        self.assertEqual(20, len(set(cores)))
        self.assertEqual("approved", node_entry["node_review_artifact"]["verdict"])
        self.assertEqual(10, len(node_entry["node_review_artifact"]["constituent_reviews"]))
        self.assertEqual([], blocking, blocking[:5])

    def test_v12_asset_validator_rejects_structured_item_semantic_failures(self):
        scenarios = [
            (
                "explicitly_coached_process",
                {"process_target_disclosed": True},
                None,
                "semantic_evidence.process_target_disclosed:must_be_false_for_unprompted",
            ),
            (
                "raw_latex_child_surface",
                {"rendered_notation_readiness": {"child_visible_risks": ["unrendered authoring notation"]}},
                r"已知 \frac{3}{5}x=12，求x并给出数学上正确的答案。",
                "semantic_evidence.rendered_notation_readiness:child_visible_risks_present",
            ),
            (
                "excessive_response_burden",
                {"response_moves": ["solve", "explain", "compare", "validate"]},
                None,
                "semantic_evidence.response_moves:overloaded",
            ),
            (
                "unnatural_chinese",
                {"natural_chinese": {"score": question_bank.V12_NATURAL_CHINESE_MIN_SCORE - 0.01}},
                None,
                "semantic_evidence.natural_chinese:score_below_gate",
            ),
            (
                "notation_score_not_perfect",
                {"rendered_notation_readiness": {"score": 0.99}},
                None,
                "semantic_evidence.rendered_notation_readiness:score_not_perfect",
            ),
            (
                "age_dignity_below_gate",
                {"age_dignity": {"score": question_bank.V12_AGE_DIGNITY_MIN_SCORE - 0.01}},
                None,
                "semantic_evidence.age_dignity:score_below_gate",
            ),
            (
                "unprompted_process_score_below_gate",
                {"unprompted_process_evidence": {"score": question_bank.V12_UNPROMPTED_PROCESS_MIN_SCORE - 0.01}},
                None,
                "semantic_evidence.unprompted_process_evidence:score_below_gate",
            ),
        ]

        for scenario, semantic_override, prompt, expected_error in scenarios:
            with self.subTest(scenario=scenario):
                manifest, _ = _v3_process_manifest()
                node_entry = manifest["nodes"][0]
                item = node_entry["items"][8]
                if prompt is not None:
                    item["prompt"] = prompt
                    item["review_artifact"]["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
                review = item["review_artifact"]
                review["semantic_evidence"] = _semantic_evidence_for_item(
                    item,
                    version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
                    overrides=semantic_override,
                )
                review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)
                node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")
                _refresh_v3_node_set_review(node_entry)

                report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
                matching = [
                    issue
                    for issue in report["issues"]
                    if issue["type"] == "v12_item_semantic_evidence_failed"
                    and issue["detail"] == f"{item['id']}:{expected_error}"
                ]

                self.assertEqual(1, len(matching))

    def test_v12_asset_validator_fails_closed_when_v3_item_semantic_fields_are_missing(self):
        fields = tuple(sorted(V12_V3_ITEM_SEMANTIC_FIELDS))
        for field in fields:
            with self.subTest(field=field):
                manifest, _ = _v3_process_manifest()
                item = manifest["nodes"][0]["items"][8]
                review = item["review_artifact"]
                review["semantic_evidence"].pop(field)
                review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)

                report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
                matching = [
                    issue
                    for issue in report["issues"]
                    if issue["type"] == "v12_item_semantic_evidence_failed"
                    and issue["detail"] == f"{item['id']}:semantic_evidence:unexpected_or_missing_fields"
                ]

                self.assertEqual(1, len(matching))

    def test_v12_node_set_v3_distribution_and_ux_gates_fail_closed(self):
        low_score = question_bank.V12_REVIEW_MIN_SCORE - 0.01
        for field in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS:
            for mode in ("missing", "low"):
                with self.subTest(field=field, mode=mode):
                    manifest, _ = _v3_process_manifest()
                    node_entry = manifest["nodes"][0]
                    if mode == "missing":
                        _refresh_v3_node_set_review(node_entry, omitted={field})
                    else:
                        _refresh_v3_node_set_review(node_entry, overrides={field: low_score})

                    report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
                    matching = [
                        issue
                        for issue in report["issues"]
                        if issue["type"] == "v12_node_set_review_score_below_gate"
                        and issue["detail"] == field
                    ]

                    self.assertEqual(1, len(matching))

        def outputs(node_entry: dict) -> list[dict]:
            return [
                review["review_output"]
                for review in node_entry["node_review_artifact"]["constituent_reviews"]
            ]

        def item_for_slot(node_entry: dict, slot: int) -> dict:
            return node_entry["items"][slot - 1]

        def update_item_semantic(node_entry: dict, slot: int, overrides: dict) -> None:
            item = item_for_slot(node_entry, slot)
            review = item["review_artifact"]
            review["semantic_evidence"] = _semantic_evidence_for_item(
                item,
                version=question_bank.V12_ITEM_REVIEW_SEMANTIC_EVIDENCE_VERSION,
                overrides=overrides,
            )
            review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(
                item,
                review,
            )
            node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        def missing_coverage(node_entry: dict) -> None:
            outputs(node_entry)[0]["focal_slot_reviews"].pop()

        def insufficient_voice_families(node_entry: dict) -> None:
            for item in node_entry["items"]:
                review = item["review_artifact"]
                review["semantic_evidence"]["instruction_voice_family"] = question_bank.V12_INSTRUCTION_VOICE_FAMILIES[0]
                review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)
            node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        def consecutive_voice_run(node_entry: dict) -> None:
            for slot in (1, 2, 3):
                item = item_for_slot(node_entry, slot)
                review = item["review_artifact"]
                review["semantic_evidence"]["instruction_voice_family"] = question_bank.V12_INSTRUCTION_VOICE_FAMILIES[0]
                review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(item, review)
            node_entry["node_review_artifact"] = _node_review_artifact(node_entry, provider_mode="live_model")

        def repetitive_cluster(node_entry: dict) -> None:
            output = node_entry["node_review_artifact"]["global_finalizer"]["global_review_output"]
            output["repetitive_instruction_clusters"] = [{
                "slots": [1, 2, 3, 4, 5],
                "cluster_summary": "same model-reported instruction skeleton",
                "reason": "five slots exceed the v3 repetitive-cluster limit",
            }]

        def overloaded_slot(node_entry: dict) -> None:
            update_item_semantic(node_entry, 1, {"response_moves": ["solve", "explain", "compare", "validate"]})

        def notation_failure(node_entry: dict) -> None:
            update_item_semantic(node_entry, 1, {"rendered_notation_readiness": {"score": 0.99}})

        def dignity_failure(node_entry: dict) -> None:
            update_item_semantic(
                node_entry,
                1,
                {"age_dignity": {"score": question_bank.V12_AGE_DIGNITY_MIN_SCORE - 0.01}},
            )

        def ux_rejected_slot(node_entry: dict) -> None:
            update_item_semantic(
                node_entry,
                1,
                {"natural_chinese": {"score": question_bank.V12_NATURAL_CHINESE_MIN_SCORE - 0.01}},
            )

        ux_cases = [
            ("exact_slot_coverage", missing_coverage, "global.slot_evidence_coverage:mismatch"),
            ("minimum_voice_families", insufficient_voice_families, "instruction_voice_family_minimum"),
            ("consecutive_voice_limit", consecutive_voice_run, "consecutive_instruction_voice_limit"),
            ("repetitive_cluster_limit", repetitive_cluster, "repetitive_instruction_cluster_limit"),
            ("overloaded_slots_empty", overloaded_slot, "overloaded_slots"),
            ("notation_failure_slots_empty", notation_failure, "notation_failure_slots"),
            ("dignity_failure_slots_empty", dignity_failure, "dignity_failure_slots"),
            ("ux_rejected_slots_empty", ux_rejected_slot, "ux_rejected_slots"),
        ]
        for scenario, mutate, expected_gate in ux_cases:
            with self.subTest(scenario=scenario):
                manifest, _ = _v3_process_manifest()
                node_entry = manifest["nodes"][0]
                mutate(node_entry)
                _recompute_v3_node_set_review(node_entry)

                report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
                issue_type = (
                    "v12_node_set_global_finalizer_output_failed"
                    if scenario == "exact_slot_coverage"
                    else "v12_node_set_ux_gate_failed"
                )
                matching = [
                    issue
                    for issue in report["issues"]
                    if issue["type"] == issue_type
                    and issue["detail"] == expected_gate
                ]

                self.assertEqual(1, len(matching))

    def test_v12_pre_v3_process_pilot_evidence_is_not_activation_eligible(self):
        manifest = json.loads(
            (
                PROJECT_ROOT
                / "data/question_banks/math/math_question_bank_v12_pilot_solution_habit_v2.json"
            ).read_text(encoding="utf-8")
        )

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        blocking = [issue for issue in report["issues"] if issue["severity"] in {"P0", "P1"}]
        item_failure_details = {
            issue["detail"]
            for issue in blocking
            if issue["type"] == "v12_item_semantic_evidence_failed"
        }
        node_score_details = {
            issue["detail"]
            for issue in blocking
            if issue["type"] == "v12_node_set_review_score_below_gate"
        }

        self.assertTrue(blocking)
        self.assertTrue(any("semantic_evidence:missing_or_not_object" in detail for detail in item_failure_details))
        self.assertIn("instruction_voice_variety", node_score_details)

    def test_v12_node_set_review_shards_persist_successes_when_later_concurrent_shard_fails(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        expected_shards = _v12_runtime_node_set_shards()
        failed_shard = expected_shards[-1]
        reviewed_shards = []

        def fake_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
            if route.agent_key == question_bank.QUESTION_REVIEWER_AGENT_KEY and route.task == "node_set_review":
                reviewed_slots = _reviewed_slots_from_payload(payload)
                reviewed_shards.append(reviewed_slots)
                if reviewed_slots == failed_shard:
                    raise module.model_router.ModelCallError("HTTP 504 gateway timeout")
                return module.model_router.StructuredJSONResult(
                    value=_node_set_review_response_for_payload(node_entry["node_id"], manifest["graph_version"], payload),
                    mode="json_schema",
                    raw_response={"node_set_review": reviewed_slots},
                )
            requested_slots = _requested_slots_from_payload(payload)
            if route.agent_key == "question_designer_agent":
                return module.model_router.StructuredJSONResult(
                    value={
                        "schema_version": question_bank.V12_DESIGNER_RESPONSE_SCHEMA_VERSION,
                        "node_id": node_entry["node_id"],
                        "graph_version": manifest["graph_version"],
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "items": _designer_batch_items([node_entry["items"][requested_slots[0] - 1]]),
                        "batch_confidence": 0.93,
                        "design_notes": ["initial"],
                    },
                    mode="json_schema",
                    raw_response={"designer": requested_slots},
                )
            return module.model_router.StructuredJSONResult(
                value=_reviewer_batch_response_for_payload(
                    module,
                    node_entry["node_id"],
                    manifest["graph_version"],
                    payload,
                ),
                mode="json_schema",
                raw_response={"reviewer": requested_slots},
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(module.model_router, "call_structured_json", side_effect=fake_call):
                with self.assertRaises(module.model_router.ModelCallError):
                    module.build_live(
                        output_path=tmp_path / "math_question_bank_v12.json",
                        checkpoint_dir=tmp_path / "checkpoints",
                        project_root=PROJECT_ROOT,
                        node_ids=[node_entry["node_id"]],
                        max_rounds=3,
                        max_concurrency=4,
                        resume=True,
                    )
            checkpoint = json.loads(next((tmp_path / "checkpoints").glob("*.json")).read_text(encoding="utf-8"))
            saved_slots = [review["reviewed_slots"] for review in checkpoint["node"]["node_review_artifact"]["constituent_reviews"]]
            self.assertEqual(expected_shards[:-1], saved_slots)
            self.assertEqual(expected_shards[:-1], reviewed_shards[:len(expected_shards) - 1])
            self.assertEqual(
                [failed_shard] * module.LIVE_BATCH_NETWORK_ATTEMPTS,
                reviewed_shards[len(expected_shards) - 1:],
            )

    def test_v12_legacy_five_slot_constituent_cannot_mix_into_checkpoint_or_active_seed(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        artifact = node_entry["node_review_artifact"]
        legacy_slots = [1, 2, 3, 4, 5]
        legacy_review = json.loads(json.dumps(artifact["constituent_reviews"][0], ensure_ascii=False))
        legacy_output = _node_set_review_response(
            node_entry,
            manifest["graph_version"],
            reviewed_slots=legacy_slots,
        )
        legacy_review.update({
            "shard_id": "slots-01-05",
            "reviewed_slots": legacy_slots,
            "review_output": legacy_output,
            "review_output_sha256": _sha256_json(legacy_output),
        })
        legacy_review["semantic_evidence_sha256"] = question_bank.v12_node_set_constituent_semantic_evidence_sha256(
            node_entry,
            legacy_review,
        )
        artifact["constituent_reviews"] = [legacy_review, *artifact["constituent_reviews"][1:]]
        recomputed = question_bank._v12_recompute_node_set_review_from_constituents(
            node_entry,
            artifact["constituent_reviews"],
            artifact["global_finalizer"],
        )
        aggregate = question_bank.v12_node_set_review_aggregate_payload(
            node_entry=node_entry,
            shard_reviews=artifact["constituent_reviews"],
            global_finalizer_artifact=artifact["global_finalizer"],
            reduced=recomputed,
        )
        artifact.update({
            **recomputed,
            "canonical_repair_plan": recomputed["repair_instructions"],
            "aggregation": aggregate["aggregation"],
            "semantic_evidence_sha256": aggregate["semantic_evidence_sha256"],
            "semantic_evidence_coverage": aggregate["semantic_evidence_coverage"],
        })

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] in {"P0", "P1"}}
        self.assertIn("v12_node_set_review_bad_shard_coverage", issue_types)

        checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=1)
        checkpoint["node"]["node_review_artifact"] = json.loads(json.dumps(artifact, ensure_ascii=False))
        checkpoint["accepted_slots"] = {
            str(item["slot"]): item
            for item in checkpoint["node"]["items"]
        }
        _seal_v12_incomplete_checkpoint(checkpoint)
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                "node_set_review.constituent_reviews:untrusted_or_v1",
            ):
                module._read_live_node_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph_version=manifest["graph_version"],
                )

        receipt = _runner_receipt_for_manifest(manifest)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            db.init_schema(conn)
            with self.assertRaisesRegex(ValueError, "v12_node_set_review_bad_shard_coverage"):
                db.seed_external_question_bank_v12(
                    conn,
                    manifest,
                    project_root=PROJECT_ROOT,
                    runner_receipt=receipt,
                    commit=False,
                )
        finally:
            conn.close()

    def test_v12_validator_rejects_bad_node_set_shard_coverage_and_self_edited_aggregate(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        artifact = manifest["nodes"][0]["node_review_artifact"]
        artifact["constituent_reviews"] = [json.loads(json.dumps(artifact["constituent_reviews"][0])) for _ in range(4)]
        artifact["distribution_scores"]["semantic_diversity"] = 0.99
        artifact["confidence"] = 0.99
        artifact["aggregation"] = {
            "strategy": "deterministic_shard_aggregate",
            "aggregate_sha256": "forged",
            "constituent_count": 4,
            "constituent_hashes": [review["review_output_sha256"] for review in artifact["constituent_reviews"]],
            "reviewed_slots": list(range(1, 21)),
        }

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}

        self.assertIn("v12_node_set_review_bad_shard_coverage", issue_types)
        self.assertIn("v12_node_set_review_aggregation_mismatch", issue_types)

    def test_v12_validator_rejects_non_live_constituent_inside_live_node_review(self):
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        artifact = manifest["nodes"][0]["node_review_artifact"]
        artifact["constituent_reviews"][0]["provider_mode"] = "recorded_model"

        report = question_bank.validate_external_question_bank_v12(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}

        self.assertIn("v12_node_set_review_bad_constituent_review", issue_types)

    def test_v12_forged_complete_checkpoint_with_self_edited_aggregate_is_not_laundered(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        checkpoint = _v12_completed_checkpoint_with_repair_chain(module, node_entry, manifest["graph_version"])
        forged_node = json.loads(json.dumps(checkpoint["node"]))
        forged_node["node_review_artifact"]["aggregation"]["aggregate_sha256"] = "forged"
        forged_node["node_review_artifact"]["constituent_reviews"][0]["reviewed_slots"] = [1, 2, 3, 4, 5]
        forged_node["node_review_artifact"]["constituent_reviews"][1]["reviewed_slots"] = [1, 2, 3, 4, 5]
        checkpoint["node"] = forged_node
        checkpoint["accepted_slots"] = {str(item["slot"]): item for item in forged_node["items"]}
        checkpoint["semantic_evidence_commitment"] = question_bank.v12_node_semantic_evidence_commitment(forged_node)
        _reseal_v12_completed_checkpoint(module, checkpoint)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_dir = tmp_path / "checkpoints"
            checkpoint_dir.mkdir()
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(
                    checkpoint,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def no_launder_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                raise module.model_router.ModelCallError("model unavailable; forged checkpoint must not be treated as live")

            with mock.patch.object(module.model_router, "call_structured_json", side_effect=no_launder_call):
                with self.assertRaisesRegex(
                    module.model_router.ModelCallError,
                    "checkpoint policy rejected.*node_set_review.constituent_reviews:untrusted_or_v1",
                ):
                    module.build_live(
                        output_path=tmp_path / "math_question_bank_v12.json",
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=[node_entry["node_id"]],
                        max_rounds=3,
                        max_concurrency=4,
                        resume=True,
                    )

    def test_v12_completed_checkpoint_missing_v3_node_ux_evidence_cannot_be_laundered(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        checkpoint = _v12_completed_checkpoint_with_repair_chain(module, node_entry, manifest["graph_version"])
        forged_node = json.loads(json.dumps(checkpoint["node"]))
        forged_node["node_review_artifact"].pop("node_ux_verdict", None)
        checkpoint["node"] = forged_node
        checkpoint["accepted_slots"] = {str(item["slot"]): item for item in forged_node["items"]}
        _reseal_v12_completed_checkpoint(module, checkpoint)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_dir = tmp_path / "checkpoints"
            checkpoint_dir.mkdir()
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(
                    checkpoint,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def no_launder_call(route, payload, *, schema, plain_json_instruction="", retryable_errors_fallback=True):
                raise module.model_router.ModelCallError("model unavailable; forged checkpoint must not be treated as live")

            with mock.patch.object(module.model_router, "call_structured_json", side_effect=no_launder_call):
                with self.assertRaisesRegex(
                    module.model_router.ModelCallError,
                    "forged checkpoint rejected.*v12_node_set_ux_not_approved",
                ):
                    module.build_live(
                        output_path=tmp_path / "math_question_bank_v12.json",
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=[node_entry["node_id"]],
                        max_rounds=3,
                        max_concurrency=4,
                        resume=True,
                    )

    def test_v12_node_set_review_aggregate_detects_cross_shard_duplicate_slots(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-EQ-DENOM",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        aggregate = _v4_duplicate_node_set_aggregate(
            module,
            node_entry,
            manifest["graph_version"],
            duplicate_slots=[2, 10, 16],
            rejected_slots=[10, 16],
            reason="same equation across focal shards",
        )

        self.assertEqual("needs_repair", aggregate["node_review_artifact"]["verdict"])
        self.assertEqual(
            len(_v12_runtime_node_set_shards()),
            len(aggregate["node_review_artifact"]["constituent_reviews"]),
        )
        duplicate_group_repairs = [
            item
            for item in aggregate["repair_instructions"]
            if item.get("repair_scope") == "global_duplicate"
        ]
        duplicate_repair_slots = {
            slot
            for item in duplicate_group_repairs
            for slot in item["slots"]
        }
        self.assertEqual({10, 16}, duplicate_repair_slots)
        self.assertNotIn(2, duplicate_repair_slots)

    def test_v12_node_set_review_duplicate_group_honors_explicit_minimal_rejected_slots(self):
        script_path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
        spec = importlib.util.spec_from_file_location("build_math_question_bank_v12", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-EQ-DENOM",), provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        aggregate = _v4_duplicate_node_set_aggregate(
            module,
            node_entry,
            manifest["graph_version"],
            duplicate_slots=[2, 10, 16],
            rejected_slots=[10, 16],
            reason="same equation; keep slot 2",
        )

        repair_slots = {
            slot
            for instruction in aggregate["repair_instructions"]
            for slot in instruction.get("slots", [])
        }
        self.assertEqual({10, 16}, repair_slots)
        self.assertNotIn(2, repair_slots)

    def test_v12_node_set_repair_budget_is_separate_from_exhausted_local_item_rounds(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        repair_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "local reviewer accepted the item, but the node set repeats the same mathematical core",
            "repair_instructions": ["Replace the mathematical core, not only the story decoration."],
        }
        node_set_calls = []
        repair_calls = []

        def fake_node_set_review(**kwargs):
            node_set_calls.append(kwargs)
            if len(node_set_calls) == 1:
                return {"repair_instructions": [repair_instruction], "node_review_artifact": None}
            return {
                "repair_instructions": [],
                "node_review_artifact": {
                    "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                    "phase": "node_set_review",
                    "pipeline_stage": "node_set_review",
                    "stage_attempt": len(node_set_calls),
                },
            }

        def fake_repair_chunk(**kwargs):
            repair_calls.append(kwargs)
            repaired = json.loads(json.dumps(node_entry["items"][6], ensure_ascii=False))
            repaired["math_core_signature"] = "node-set-repaired-core-slot-07"
            repaired["prompt"] = "集合级返修后的第7题：使用不同数学核心并说明检验。"
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [7],
                "accepted_by_slot": {7: repaired},
                "rejected_slots": [],
                "repair_instructions": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=3)
            _seal_v12_incomplete_checkpoint(checkpoint)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(module, "_node_set_semantic_repair_instructions", side_effect=fake_node_set_review), \
                 mock.patch.object(module, "_process_live_slot_chunk", side_effect=fake_repair_chunk):
                try:
                    result = module._build_live_node(**_build_live_node_test_kwargs(
                        module,
                        node=node,
                        graph=graph,
                        graph_version=manifest["graph_version"],
                        checkpoint_dir=checkpoint_dir,
                        max_rounds=3,
                    ))
                except Exception as exc:
                    self.fail(
                        "local item round 3 must not consume the node-set semantic repair budget; "
                        f"got {type(exc).__name__}: {exc}"
                    )

        self.assertEqual(2, len(node_set_calls))
        self.assertEqual(1, len(repair_calls))
        self.assertEqual([7], repair_calls[0]["requested_slots"])
        self.assertEqual([repair_instruction], repair_calls[0]["repair_instructions"])
        self.assertEqual("node-set-repaired-core-slot-07", result["items"][6]["math_core_signature"])

    def test_v12_node_set_semantic_repair_budget_is_bounded(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        repair_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "the set remains semantically repetitive",
            "repair_instructions": ["Use another mathematical core."],
        }
        node_set_calls = []
        repair_calls = []

        def always_reject_node_set(**kwargs):
            node_set_calls.append(kwargs)
            if len(node_set_calls) > 3:
                self.fail("node-set semantic repair loop exceeded its bounded budget")
            return {"repair_instructions": [repair_instruction], "node_review_artifact": None}

        def accept_repair_but_keep_set_rejected(**kwargs):
            repair_calls.append(kwargs)
            repaired = json.loads(json.dumps(node_entry["items"][6], ensure_ascii=False))
            repaired["math_core_signature"] = f"bounded-node-set-repair-{len(repair_calls)}"
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [7],
                "accepted_by_slot": {7: repaired},
                "rejected_slots": [],
                "repair_instructions": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=0)
            _seal_v12_incomplete_checkpoint(checkpoint)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(module, "_node_set_semantic_repair_instructions", side_effect=always_reject_node_set), \
                 mock.patch.object(module, "_process_live_slot_chunk", side_effect=accept_repair_but_keep_set_rejected):
                with self.assertRaisesRegex(ValueError, "exhausted"):
                    module._build_live_node(**_build_live_node_test_kwargs(
                        module,
                        node=node,
                        graph=graph,
                        graph_version=manifest["graph_version"],
                        checkpoint_dir=checkpoint_dir,
                        max_rounds=2,
                    ))

        self.assertEqual(3, len(node_set_calls), "initial review plus two bounded repair reviews")
        self.assertEqual(2, len(repair_calls))

    def test_v12_failed_node_set_repair_checkpoint_persists_feedback_and_stage_counters(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        repair_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "replace the repeated equation core found only by node-set review",
            "repair_instructions": ["Use a genuinely different mathematical structure."],
        }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint_path = checkpoint_dir / f"{node_entry['node_id']}.json"
            checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=2)
            _seal_v12_incomplete_checkpoint(checkpoint)
            checkpoint_path.write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(
                     module,
                     "_node_set_semantic_repair_instructions",
                     return_value={"repair_instructions": [repair_instruction], "node_review_artifact": None},
                 ), mock.patch.object(
                     module,
                     "_process_live_slot_chunk",
                     side_effect=RuntimeError("simulated crash after node-set rejection checkpoint"),
                 ):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    module._build_live_node(**_build_live_node_test_kwargs(
                        module,
                        node=node,
                        graph=graph,
                        graph_version=manifest["graph_version"],
                        checkpoint_dir=checkpoint_dir,
                        max_rounds=3,
                    ))
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        self.assertEqual([7], saved.get("node_set_rejected_slots"))
        pending = saved.get("pending_repair_by_slot")
        self.assertIsInstance(pending, dict)
        self.assertEqual([repair_instruction], pending.get("7"))
        counters = saved.get("stage_counters")
        self.assertIsInstance(counters, dict)
        self.assertEqual(2, counters.get("local_item_rounds_by_slot", {}).get("7"))
        self.assertEqual(1, counters.get("node_set_review_round"))
        self.assertEqual(1, counters.get("node_set_repair_rounds_by_slot", {}).get("7"))

    def test_v12_canonical_pilot_six_requires_exact_six_nodes_and_120_unique_questions(self):
        module = _load_v12_build_module()
        self.assertEqual(6, len(module.PILOT_SIX_NODE_IDS))
        manifest = _manifest(
            tuple(module.PILOT_SIX_NODE_IDS),
            provider_mode="live_model",
            status="draft_live_model",
        )

        validated = module._validate_canonical_pilot_six_manifest(manifest)

        self.assertEqual(6, validated["node_count"])
        self.assertEqual(120, validated["item_count"])
        self.assertEqual(120, validated["unique_question_count"])

        one_node = copy.deepcopy(manifest)
        one_node["nodes"] = one_node["nodes"][:1]
        with self.assertRaisesRegex(ValueError, "exactly six"):
            module._validate_canonical_pilot_six_manifest(one_node)

        duplicate = copy.deepcopy(manifest)
        duplicate["nodes"][1]["items"][0]["id"] = duplicate["nodes"][0]["items"][0]["id"]
        with self.assertRaisesRegex(ValueError, "120 unique"):
            module._validate_canonical_pilot_six_manifest(duplicate)

    def test_v12_canonical_full_output_rejects_partial_and_recorded_builds(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_output = root / "math_question_bank_v12.json"
            checkpoint_dir = root / "checkpoints"
            with mock.patch.object(module, "DEFAULT_OUTPUT", canonical_output):
                with self.assertRaisesRegex(
                    ValueError,
                    "exact ordered 56-node inventory",
                ):
                    module.build_live(
                        output_path=canonical_output,
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=["M-G7-NUMBER-LINE"],
                        max_concurrency=1,
                    )
                with self.assertRaisesRegex(
                    ValueError,
                    "recorded fixture cannot overwrite",
                ):
                    module.build_from_recorded_fixture(
                        fixture_path=root / "unused-recorded-fixture.json",
                        output_path=canonical_output,
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                    )
            self.assertFalse(canonical_output.exists())
            self.assertFalse(checkpoint_dir.exists())

    def test_v12_multi_node_failure_marks_only_the_failing_node_budget(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            with mock.patch.object(
                module,
                "_build_live_node",
                side_effect=RuntimeError("failing-node-only"),
            ):
                with self.assertRaisesRegex(RuntimeError, "failing-node-only"):
                    module.build_live(
                        output_path=root / "subset.json",
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=["M-G7-NUMBER-LINE", "M-G7-OPPOSITE"],
                        max_concurrency=1,
                    )
            state_dir = checkpoint_dir / ".run-state"
            failed = json.loads(
                (state_dir / "M-G7-NUMBER-LINE.model-budget.json").read_text(
                    encoding="utf-8"
                )
            )
            untouched = json.loads(
                (state_dir / "M-G7-OPPOSITE.model-budget.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("interrupted", failed["status"])
            self.assertEqual("RuntimeError", failed["last_error_class"])
            self.assertEqual("active", untouched["status"])
            self.assertEqual("", untouched["last_error_class"])
            self.assertEqual([], untouched["interruptions"])

        with self.assertRaisesRegex(ValueError, "single-node.*canonical pilot-six"):
            module._assert_canonical_pilot_output_request(
                module.CANONICAL_PILOT_SIX_OUTPUT,
                [module.PILOT_SIX_NODE_IDS[0]],
            )

    def test_v12_partial_pilot_stages_only_and_conflicting_stage_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "pilot-stage.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                db.init_schema(conn)
                db.seed_from_assets(conn, PROJECT_ROOT)
                active_before = db.get_active_question_bank_version(conn)
                staged = db.stage_question_bank_version(
                    conn,
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    graph_version=_graph_version(),
                    manifest_id="pilot-six",
                    manifest_sha256="a" * 64,
                    node_count=6,
                    item_count=120,
                    commit=False,
                )
                canonical_retry = db.stage_question_bank_version(
                    conn,
                    question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                    graph_version=_graph_version(),
                    manifest_id="pilot-six",
                    manifest_sha256="a" * 64,
                    node_count=6,
                    item_count=120,
                    commit=False,
                )
                self.assertEqual(staged["id"], canonical_retry["id"])

                for override in (
                    {"manifest_sha256": "b" * 64},
                    {"node_count": 5},
                    {"item_count": 100},
                ):
                    kwargs = {
                        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
                        "graph_version": _graph_version(),
                        "manifest_id": "pilot-six",
                        "manifest_sha256": "a" * 64,
                        "node_count": 6,
                        "item_count": 120,
                        "commit": False,
                        **override,
                    }
                    with self.assertRaisesRegex(ValueError, "staged question bank identity conflict"):
                        db.stage_question_bank_version(conn, **kwargs)

                with self.assertRaisesRegex(ValueError, "full-bank coverage"):
                    db.activate_question_bank_version(
                        conn,
                        question_bank_version=question_bank.QUESTION_BANK_V12_VERSION,
                        expected_current_version=active_before,
                        reason="must not activate partial pilot",
                        commit=False,
                    )
                self.assertEqual(active_before, db.get_active_question_bank_version(conn))
            finally:
                conn.close()

    def test_v12_live_run_lock_precedes_model_work_and_releases_in_finally(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            output_path = root / "single-node.json"
            observed = {}

            def stop_after_lock(**_kwargs):
                lock_files = sorted((checkpoint_dir / ".run-locks").glob("*.lock.json"))
                observed["locks"] = [json.loads(path.read_text(encoding="utf-8")) for path in lock_files]
                raise RuntimeError("stop after lock observation")

            with mock.patch.object(module, "_build_live_node", side_effect=stop_after_lock):
                with self.assertRaisesRegex(RuntimeError, "stop after lock observation"):
                    module.build_live(
                        output_path=output_path,
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=["M-G7-NUMBER-LINE"],
                        max_rounds=3,
                        max_concurrency=1,
                        resume=True,
                    )

            self.assertGreaterEqual(len(observed["locks"]), 2)
            for record in observed["locks"]:
                self.assertTrue(record["run_id"])
                self.assertEqual(os.getpid(), record["pid"])
            released_lock_files = sorted((checkpoint_dir / ".run-locks").glob("*.lock.json"))
            self.assertGreaterEqual(len(released_lock_files), 2)
            for path in released_lock_files:
                descriptor = module._open_checkpoint_lock(path)
                module.fcntl.flock(descriptor, module.fcntl.LOCK_UN)
                os.close(descriptor)
            budget_path = checkpoint_dir / ".run-state" / "M-G7-NUMBER-LINE.model-budget.json"
            interrupted = json.loads(budget_path.read_text(encoding="utf-8"))
            self.assertEqual("interrupted", interrupted["status"])
            self.assertEqual("RuntimeError", interrupted["last_error_class"])
            self.assertTrue(interrupted["last_error_at"])
            self.assertIn("stop after lock observation", interrupted["reason"])

            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id="M-G7-NUMBER-LINE",
                run_id="RUN-AFTER-INTERRUPTION",
                max_semantic_calls=module.DEFAULT_MAX_SEMANTIC_CALLS,
                max_provider_attempts=module.DEFAULT_MAX_PROVIDER_ATTEMPTS,
            ).snapshot()
            self.assertEqual("active", resumed["status"])
            self.assertEqual(interrupted["semantic_calls"], resumed["semantic_calls"])
            self.assertEqual(interrupted["provider_attempts"], resumed["provider_attempts"])
            self.assertEqual("RuntimeError", resumed["interruptions"][-1]["error_class"])

    def test_v12_live_run_lock_recovers_only_when_recorded_owner_pid_is_dead(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            output_path = root / "single-node.json"
            lock_dir = checkpoint_dir / ".run-locks"
            lock_dir.mkdir(parents=True)
            output_digest = hashlib.sha256(str(output_path.resolve()).encode("utf-8")).hexdigest()[:20]
            lock_paths = [
                lock_dir / "node-M-G7-NUMBER-LINE.lock.json",
                lock_dir / f"output-{output_digest}.lock.json",
            ]
            stale_owner = {
                "schema_version": "2026-07-15.v12-checkpoint-run-lock.v1",
                "run_id": "STALE-RUN",
                "pid": 999_999_999,
            }
            for path in lock_paths:
                path.write_text(json.dumps(stale_owner), encoding="utf-8")

            with module._checkpoint_run_lock(
                checkpoint_dir=checkpoint_dir,
                output_path=output_path,
                node_ids=["M-G7-NUMBER-LINE"],
                run_id="RECOVERED-RUN",
            ):
                for path in lock_paths:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual("RECOVERED-RUN", current["run_id"])
                    self.assertEqual(os.getpid(), current["pid"])

            self.assertEqual(sorted(lock_paths), sorted(lock_dir.glob("*.lock.json")))
            live_lock = lock_paths[0]
            live_descriptor = module._open_checkpoint_lock(live_lock)
            try:
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    "checkpoint run lock is already held",
                ):
                    module._open_checkpoint_lock(live_lock)
                self.assertTrue(live_lock.exists())
            finally:
                module.fcntl.flock(live_descriptor, module.fcntl.LOCK_UN)
                os.close(live_descriptor)

    def test_v12_live_run_lock_recovers_long_stale_owner_record(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "long-owner.lock.json"
            stale_owner = {
                "schema_version": "2026-07-15.v12-checkpoint-run-lock.v1",
                "run_id": "STALE-LONG-RUN",
                "pid": 999_999_999,
                "node_ids": [f"M-LONG-NODE-{index:03d}" for index in range(200)],
            }
            serialized = json.dumps(stale_owner, sort_keys=True)
            self.assertGreater(len(serialized), 1000)
            lock_path.write_text(serialized, encoding="utf-8")

            descriptor = module._open_checkpoint_lock(lock_path)
            module.fcntl.flock(descriptor, module.fcntl.LOCK_UN)
            os.close(descriptor)

            self.assertTrue(lock_path.exists())
            self.assertEqual(serialized, lock_path.read_text(encoding="utf-8"))

    def test_v12_live_run_lock_never_unlinks_a_competing_owner(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "contended.lock.json"
            lock_path.write_text(json.dumps({"run_id": "OLD"}), encoding="utf-8")

            first = module._open_checkpoint_lock(lock_path)
            try:
                lock_path.write_text(json.dumps({"run_id": "CURRENT"}), encoding="utf-8")
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    "checkpoint run lock is already held",
                ):
                    module._open_checkpoint_lock(lock_path)
                self.assertEqual(
                    {"run_id": "CURRENT"},
                    json.loads(lock_path.read_text(encoding="utf-8")),
                )
            finally:
                module.fcntl.flock(first, module.fcntl.LOCK_UN)
                os.close(first)

            second = module._open_checkpoint_lock(lock_path)
            module.fcntl.flock(second, module.fcntl.LOCK_UN)
            os.close(second)

    def test_v12_live_run_lock_bounds_contended_owner_diagnostics(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "oversized.lock.json"
            lock_path.write_bytes(b"x" * (module.CHECKPOINT_LOCK_OWNER_MAX_BYTES + 1))
            held = os.open(lock_path, os.O_RDWR)
            module.fcntl.flock(held, module.fcntl.LOCK_EX | module.fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    "owner record exceeds",
                ):
                    module._open_checkpoint_lock(lock_path)
                self.assertEqual(
                    module.CHECKPOINT_LOCK_OWNER_MAX_BYTES + 1,
                    lock_path.stat().st_size,
                )
            finally:
                module.fcntl.flock(held, module.fcntl.LOCK_UN)
                os.close(held)

    def test_v12_live_run_lock_release_failure_still_closes_every_descriptor(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            output_path = root / "out.json"
            original_write = module._write_checkpoint_lock_owner
            release_writes = 0

            def fail_first_release(descriptor, owner):
                nonlocal release_writes
                if owner.get("state") == "released":
                    release_writes += 1
                    if release_writes == 1:
                        raise RuntimeError("injected release owner write failure")
                return original_write(descriptor, owner)

            with mock.patch.object(
                module,
                "_write_checkpoint_lock_owner",
                side_effect=fail_first_release,
            ):
                with self.assertRaisesRegex(RuntimeError, "injected release owner write failure"):
                    with module._checkpoint_run_lock(
                        checkpoint_dir=checkpoint_dir,
                        output_path=output_path,
                        node_ids=["NODE-A", "NODE-B"],
                        run_id="RELEASE-FAILURE",
                    ):
                        pass

            for path in sorted((checkpoint_dir / ".run-locks").glob("*.lock.json")):
                descriptor = module._open_checkpoint_lock(path)
                module.fcntl.flock(descriptor, module.fcntl.LOCK_UN)
                os.close(descriptor)

    def test_v12_live_run_lock_cleanup_failure_preserves_body_error(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            output_path = root / "out.json"
            original_write = module._write_checkpoint_lock_owner

            def fail_release(descriptor, owner):
                if owner.get("state") == "released":
                    raise RuntimeError("cleanup failure must not win")
                return original_write(descriptor, owner)

            with mock.patch.object(
                module,
                "_write_checkpoint_lock_owner",
                side_effect=fail_release,
            ):
                with self.assertRaisesRegex(ValueError, "original body failure"):
                    with module._checkpoint_run_lock(
                        checkpoint_dir=checkpoint_dir,
                        output_path=output_path,
                        node_ids=["NODE-A", "NODE-B"],
                        run_id="BODY-FAILURE",
                    ):
                        raise ValueError("original body failure")

            for path in sorted((checkpoint_dir / ".run-locks").glob("*.lock.json")):
                descriptor = module._open_checkpoint_lock(path)
                module.fcntl.flock(descriptor, module.fcntl.LOCK_UN)
                os.close(descriptor)

    def test_v12_open_checkpoint_lock_closes_descriptor_on_flock_error(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "flock-error.lock.json"
            with (
                mock.patch.object(module.fcntl, "flock", side_effect=OSError("flock failed")),
                mock.patch.object(module.os, "close", wraps=os.close) as close_spy,
            ):
                with self.assertRaisesRegex(OSError, "flock failed"):
                    module._open_checkpoint_lock(lock_path)
                close_spy.assert_called_once()

    def test_v12_live_run_lock_unlock_failure_still_closes_descriptors(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            output_path = root / "out.json"
            original_flock = module.fcntl.flock

            def fail_unlock(descriptor, operation):
                if operation == module.fcntl.LOCK_UN:
                    raise OSError("unlock failed")
                return original_flock(descriptor, operation)

            with (
                mock.patch.object(module.fcntl, "flock", side_effect=fail_unlock),
                mock.patch.object(module.os, "close", wraps=os.close) as close_spy,
            ):
                with self.assertRaisesRegex(OSError, "unlock failed"):
                    with module._checkpoint_run_lock(
                        checkpoint_dir=checkpoint_dir,
                        output_path=output_path,
                        node_ids=["NODE-A", "NODE-B"],
                        run_id="UNLOCK-FAILURE",
                    ):
                        pass
                self.assertGreaterEqual(close_spy.call_count, 3)

    def test_v12_model_budget_persists_attempts_and_terminal_receipt_across_resume(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id="M-G7-NUMBER-LINE",
                run_id="RUN-BUDGET-1",
                max_semantic_calls=1,
                max_provider_attempts=2,
            )
            contract = {
                "contract_key": "budget-test",
                "response_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                },
            }
            route = module.model_router.question_designer_route()

            with mock.patch.object(
                module.model_router,
                "call_structured_json",
                side_effect=module.model_router.ModelCallError("HTTP 503 unavailable"),
            ), mock.patch.object(module, "_LIVE_RETRY_SLEEPER", return_value=None), mock.patch.object(
                module,
                "_LIVE_RETRY_JITTER",
                return_value=0.0,
            ):
                with self.assertRaisesRegex(module.ModelBudgetExceeded, "provider_attempts"):
                    module._call_v12_batch_agent(
                        contract=contract,
                        prompt_template="budget test",
                        route=route,
                        trusted_context={},
                        untrusted_payload={},
                        model_budget_tracker=tracker,
                    )

            terminal = tracker.snapshot()
            self.assertEqual(1, terminal["semantic_calls"])
            self.assertEqual(2, terminal["provider_attempts"])
            self.assertEqual("terminal_budget_exceeded", terminal["status"])
            self.assertTrue(Path(terminal["terminal_receipt_path"]).is_file())

            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id="M-G7-NUMBER-LINE",
                run_id="RUN-BUDGET-2",
                max_semantic_calls=1,
                max_provider_attempts=2,
            )
            self.assertEqual(terminal["semantic_calls"], resumed.snapshot()["semantic_calls"])
            self.assertEqual(terminal["provider_attempts"], resumed.snapshot()["provider_attempts"])
            with self.assertRaisesRegex(module.ModelBudgetExceeded, "terminal"):
                resumed.reserve_semantic_call("question_candidate")
            module._write_checkpoint(
                checkpoint_dir,
                node_id="M-G7-NUMBER-LINE",
                graph_version="test-graph-version",
                rounds_used=0,
                rejected_rounds=0,
                report={"issues": []},
                model_budget_tracker=resumed,
            )
            checkpoint = json.loads(
                (checkpoint_dir / "M-G7-NUMBER-LINE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(terminal["semantic_calls"], checkpoint["model_budget"]["semantic_calls"])
            self.assertEqual(terminal["provider_attempts"], checkpoint["model_budget"]["provider_attempts"])
            self.assertEqual("terminal_budget_exceeded", checkpoint["model_budget"]["status"])

    def test_v12_budget_resume_records_unclean_prior_active_run_without_resetting_counts(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            state_dir = checkpoint_dir / ".run-state"
            state_dir.mkdir(parents=True)
            state_path = state_dir / "M-BRIDGE-MOTION-CHASE.model-budget.json"
            state_path.write_text(
                json.dumps({
                    "schema_version": "2026-07-15.v12-model-budget.v1",
                    "node_id": "M-BRIDGE-MOTION-CHASE",
                    "run_ids": ["RUN-ENDED-WITHOUT-FINAL-STATE"],
                    "pid": 999999,
                    "semantic_calls": 9,
                    "provider_attempts": 12,
                    "max_semantic_calls": 512,
                    "max_provider_attempts": 1536,
                    "status": "active",
                    "reason": "",
                }),
                encoding="utf-8",
            )

            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id="M-BRIDGE-MOTION-CHASE",
                run_id="RUN-RESUME-AFTER-UNCLEAN-EXIT",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            ).snapshot()

        self.assertEqual("active", resumed["status"])
        self.assertEqual(9, resumed["semantic_calls"])
        self.assertEqual(12, resumed["provider_attempts"])
        self.assertEqual("UncleanPreviousRun", resumed["last_error_class"])
        self.assertTrue(resumed["last_error_at"])
        self.assertEqual("UncleanPreviousRun", resumed["interruptions"][-1]["error_class"])
        self.assertEqual("RUN-ENDED-WITHOUT-FINAL-STATE", resumed["interruptions"][-1]["run_id"])

    def test_v12_cli_forwards_positive_hard_caps_and_rejects_nonpositive_caps(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = [
                str(module.__file__),
                "--live",
                "--node",
                "M-G7-NUMBER-LINE",
                "--output",
                str(root / "node.json"),
                "--checkpoint-dir",
                str(root / "checkpoints"),
                "--max-semantic-calls",
                "7",
                "--max-provider-attempts",
                "13",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                module,
                "build_live",
                return_value={"mode": "live"},
            ) as build_live_mock, mock.patch("builtins.print"):
                module.main()
            self.assertEqual(7, build_live_mock.call_args.kwargs["max_semantic_calls"])
            self.assertEqual(13, build_live_mock.call_args.kwargs["max_provider_attempts"])

            invalid_argv = [*argv[:-2], "--max-provider-attempts", "0"]
            with mock.patch.object(sys, "argv", invalid_argv):
                with self.assertRaisesRegex(SystemExit, "max-provider-attempts"):
                    module.main()

    def test_v12_node_set_repair_resume_reuses_feedback_without_regenerating_accepted_slots(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        repair_instruction = {
            "reason": "v12_node_set_semantic_review",
            "slot": 7,
            "slots": [7],
            "details": "resume must retain the node-set mathematical-core rejection",
            "repair_instructions": ["Replace the mathematical core before another node-set review."],
        }
        process_calls = []

        def resume_repair_chunk(**kwargs):
            process_calls.append(kwargs)
            repaired = json.loads(json.dumps(node_entry["items"][6], ensure_ascii=False))
            repaired["math_core_signature"] = "resume-node-set-repaired-core-slot-07"
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [7],
                "accepted_by_slot": {7: repaired},
                "rejected_slots": [],
                "repair_instructions": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint = _incomplete_live_checkpoint(node_entry, manifest["graph_version"], local_round=1)
            checkpoint["accepted_slots"].pop("7")
            checkpoint["node"]["items"] = [item for item in checkpoint["node"]["items"] if item["slot"] != 7]
            checkpoint["pending_repair_by_slot"] = {"7": [repair_instruction]}
            checkpoint["node_set_rejected_slots"] = [7]
            checkpoint["stage_counters"] = {
                "local_item_rounds_by_slot": {str(slot): 3 for slot in range(1, 21)},
                "node_set_review_round": 1,
                "node_set_repair_rounds_by_slot": {"7": 0},
            }
            checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(checkpoint["node"])
            checkpoint["repair_chain_events"] = []
            checkpoint["repair_chain_head_sha256"] = ""
            _seal_v12_incomplete_checkpoint(checkpoint)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(module.question_bank, "validate_external_question_bank_v12", return_value={"issues": []}), \
                 mock.patch.object(module, "_node_level_repair_instructions", return_value=[]), \
                 mock.patch.object(
                     module,
                     "_node_set_semantic_repair_instructions",
                     return_value={
                         "repair_instructions": [],
                         "node_review_artifact": {
                             "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                             "phase": "node_set_review",
                             "pipeline_stage": "node_set_review",
                             "stage_attempt": 2,
                         },
                     },
                 ), mock.patch.object(module, "_process_live_slot_chunk", side_effect=resume_repair_chunk):
                result = module._build_live_node(**_build_live_node_test_kwargs(
                    module,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    checkpoint_dir=checkpoint_dir,
                    max_rounds=3,
                ))

        self.assertEqual([[7]], [call["requested_slots"] for call in process_calls])
        self.assertEqual([repair_instruction], process_calls[0]["repair_instructions"])
        self.assertEqual(20, len(result["items"]))

    def test_v12_runner_receipt_preserves_pipeline_stage_and_stage_attempt(self):
        module = _load_v12_build_module()
        manifest = _manifest(provider_mode="live_model", status="draft_live_model")
        node_entry = manifest["nodes"][0]
        first_item = node_entry["items"][0]
        first_item["designer_artifact"].update({
            "pipeline_stage": "node_set_semantic_repair",
            "stage_attempt": 1,
        })
        first_item["review_artifact"].update({
            "pipeline_stage": "node_set_semantic_repair",
            "stage_attempt": 1,
        })
        node_artifact = node_entry["node_review_artifact"]
        node_artifact.update({"pipeline_stage": "node_set_review", "stage_attempt": 2})
        for shard in node_artifact["constituent_reviews"]:
            shard.update({"pipeline_stage": "node_set_review", "stage_attempt": 2})

        receipt = module._runner_receipt_for_manifest(manifest)
        completed_receipt = module._completed_checkpoint_node_receipt(
            node_entry=node_entry,
            graph_version=manifest["graph_version"],
        )

        self.assertEqual("node_set_semantic_repair", receipt["items"][0]["designer"].get("pipeline_stage"))
        self.assertEqual(1, receipt["items"][0]["designer"].get("stage_attempt"))
        self.assertEqual("node_set_semantic_repair", receipt["items"][0]["reviewer"].get("pipeline_stage"))
        self.assertEqual(1, receipt["items"][0]["reviewer"].get("stage_attempt"))
        self.assertEqual("node_set_review", receipt["nodes"][0]["node_set_review"].get("pipeline_stage"))
        self.assertEqual(2, receipt["nodes"][0]["node_set_review"].get("stage_attempt"))
        self.assertTrue(all(
            shard.get("pipeline_stage") == "node_set_review" and shard.get("stage_attempt") == 2
            for shard in receipt["nodes"][0]["node_set_review"]["constituent_reviews"]
        ))
        self.assertEqual("node_set_review", completed_receipt["node_set_review"].get("pipeline_stage"))
        self.assertEqual(2, completed_receipt["node_set_review"].get("stage_attempt"))

    def test_v12_audit_external_asset_lane_flags_declared_node_overuse_without_legacy_false_pass(self):
        audit_path = PROJECT_ROOT / "scripts/audit_question_bank_grade_level.py"
        spec = importlib.util.spec_from_file_location("audit_question_bank_grade_level", audit_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-POS-NEG", "M-G7-COMPARE"), duplicate_core=True, missing_review=True)

        report = module.audit_external_asset(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"]}

        self.assertIn("v12_core_reused_too_often", issue_types)
        self.assertIn("v12_missing_independent_review_artifact", issue_types)
        self.assertNotIn("v12_cross_node_math_core_reuse", issue_types)
        self.assertEqual("legacy_10_task_round", report["legacy_active_round"]["lane"])

    def test_v12_audit_external_asset_reports_structured_node_set_duplicate_evidence(self):
        audit_path = PROJECT_ROOT / "scripts/audit_question_bank_grade_level.py"
        spec = importlib.util.spec_from_file_location("audit_question_bank_grade_level", audit_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        manifest = _manifest(("M-G7-EQ-DENOM",), provider_mode="recorded_model")
        node_entry = manifest["nodes"][0]
        duplicate_group = {
            "slots": [2, 10, 16],
            "reason": "recorded node-set reviewer found one semantic equation core across three slots",
        }
        node_entry["node_review_artifact"] = _node_review_artifact(
            node_entry,
            provider_mode="recorded_model",
            duplicate_groups=[duplicate_group],
            rejected_slots={10, 16},
        )

        report = module.audit_external_asset(manifest, _load_graph())
        issue_types = {issue["type"] for issue in report["issues"] if issue["severity"] == "P1"}
        duplicate_issues = [
            issue
            for issue in report["issues"]
            if issue["type"] == "v12_node_set_reviewer_duplicate_group"
        ]
        node_summary = report["node_summaries"][0]

        self.assertIn("v12_node_set_reviewer_duplicate_group", issue_types)
        self.assertEqual([[2, 10, 16]], [issue.get("slots") for issue in duplicate_issues])
        self.assertNotIn("v12_semantic_core_reuse_by_independent_fingerprint", issue_types)
        self.assertIn("declared_core_signatures", node_summary)
        self.assertEqual(1, node_summary["model_semantic_duplicate_group_count"])
        self.assertNotIn("unique_core_signatures", node_summary)


class QuestionBankV12CrossNodeLineageIndependentQATests(unittest.TestCase):
    def _capture_cross_node_selector_payload(
        self,
        module,
        *,
        summaries: list[dict],
    ) -> list[dict]:
        graph = _load_graph()
        node = next(item for item in graph["nodes"] if item["id"] == "M-G7-RATIONAL-MIXED")
        captured: dict[str, object] = {}

        def stop_after_selector(**kwargs):
            captured.update(kwargs["untrusted_payload"])
            raise RuntimeError("qa stop after cross-node selector capture")

        with mock.patch.object(module, "_call_v12_batch_agent", side_effect=stop_after_selector):
            with self.assertRaisesRegex(RuntimeError, "selector capture"):
                module._process_live_slot_chunk(
                    node=node,
                    graph=graph,
                    graph_version=_graph_version(),
                    requested_slots=[1],
                    round_number=1,
                    designer_contract=module._load_json(module.DESIGNER_CONTRACT_PATH),
                    reviewer_contract=module._load_json(module.REVIEWER_CONTRACT_PATH),
                    designer_prompt_template=module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
                    reviewer_prompt_template=module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                    accepted_core_summaries=summaries,
                    accepted_items=[],
                    repair_instructions=[],
                )
        return list(captured["accepted_cross_node_core_summaries"])

    def _new_budget_state(self, module, checkpoint_dir: Path) -> Path:
        tracker = module._ModelBudgetTracker(
            checkpoint_dir=checkpoint_dir,
            node_id="M-G7-RATIONAL-MIXED",
            run_id="QA-BUDGET-BASELINE",
            max_semantic_calls=20,
            max_provider_attempts=40,
        )
        tracker.reserve_semantic_call("question_candidate")
        tracker.reserve_semantic_call("question_review")
        tracker.reserve_provider_attempt("question_candidate")
        tracker.reserve_provider_attempt("question_candidate")
        tracker.reserve_provider_attempt("question_review")
        return checkpoint_dir / ".run-state" / "M-G7-RATIONAL-MIXED.model-budget.json"

    def _write_legacy_cap_divergence_fixture(
        self,
        module,
        checkpoint_dir: Path,
        *,
        node_id: str = "M-G7-RATIONAL-MIXED",
        checkpoint_caps: tuple[int, int] = (120, 300),
        state_caps: tuple[int, int] = (512, 1536),
        state_semantic_delta: int = 0,
        tamper_checkpoint_seal: bool = False,
        tamper_completed_receipt: bool = False,
        receipt_commits_budget: bool = False,
        tamper_committed_budget: bool = False,
        remove_checkpoint_seal: bool = False,
        state_extra_authority: dict | None = None,
        write_existing_marker: bool = False,
    ) -> tuple[str, Path, Path]:
        manifest = _manifest(
            (node_id,),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = copy.deepcopy(manifest["nodes"][0])
        node_id = node_entry["node_id"]
        checkpoint_budget = {
            "schema_version": module.V12_MODEL_BUDGET_LEGACY_SCHEMA_VERSION,
            "node_id": node_id,
            "semantic_calls": 11,
            "provider_attempts": 13,
            "max_semantic_calls": checkpoint_caps[0],
            "max_provider_attempts": checkpoint_caps[1],
            "status": "completed",
            "run_ids": ["QA-SEALED-CHECKPOINT"],
            "interruptions": [],
        }
        checkpoint = _v12_completed_checkpoint_with_repair_chain(
            module,
            node_entry,
            manifest["graph_version"],
        )
        checkpoint["model_budget"] = checkpoint_budget
        receipt_budget_commitment = (
            module._model_budget_receipt_commitment(checkpoint_budget)
            if receipt_commits_budget
            else None
        )
        checkpoint["completed_node_receipt"] = module._completed_checkpoint_node_receipt(
            node_entry=node_entry,
            graph_version=manifest["graph_version"],
            repair_chain_hash=checkpoint["repair_chain_hash"],
            model_budget_commitment=receipt_budget_commitment,
        )
        if tamper_committed_budget:
            checkpoint["completed_node_receipt"]["model_budget_commitment"][
                "max_semantic_calls"
            ] += 1
        checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(
            checkpoint
        )
        if tamper_checkpoint_seal:
            checkpoint["stage_counters"] = {"tampered_after_seal": 1}
        if tamper_completed_receipt:
            checkpoint["completed_node_receipt"]["receipt_sha256"] = "0" * 64
        if remove_checkpoint_seal:
            checkpoint.pop("checkpoint_integrity_sha256", None)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{node_id}.json"
        checkpoint_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False),
            encoding="utf-8",
        )
        state_dir = checkpoint_dir / ".run-state"
        state_dir.mkdir(exist_ok=True)
        state_path = state_dir / f"{node_id}.model-budget.json"
        state_payload = {
                **checkpoint_budget,
                "semantic_calls": checkpoint_budget["semantic_calls"] + state_semantic_delta,
                "max_semantic_calls": state_caps[0],
                "max_provider_attempts": state_caps[1],
                "status": "interrupted",
                "run_ids": ["QA-SEALED-CHECKPOINT", "QA-LATER-FULL-GRAPH-INIT"],
                "interruptions": [{
                    "run_id": "QA-LATER-FULL-GRAPH-INIT",
                    "error_class": "KeyboardInterrupt",
                }],
            }
        state_payload.update(state_extra_authority or {})
        state_path.write_text(
            json.dumps(state_payload),
            encoding="utf-8",
        )
        if write_existing_marker:
            marker_path = state_dir / f"{node_id}.model-budget-upgrade.json"
            marker = {
                "schema_version": module.V12_MODEL_BUDGET_MARKER_SCHEMA_VERSION,
                "node_id": node_id,
                "max_semantic_calls": 120,
                "max_provider_attempts": 300,
                "minimum_semantic_calls": 11,
                "minimum_provider_attempts": 13,
                "counter_chain_head_sha256": "",
                "budget_integrity_sha256": "0" * 64,
                "legacy_source_digests": [],
                "updated_at": "2026-07-16T00:00:00Z",
            }
            marker["integrity_sha256"] = module._model_budget_marker_integrity_sha256(
                marker
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
        return node_id, state_path, checkpoint_path

    def _seal_completed_checkpoint_budget(
        self,
        module,
        checkpoint_path: Path,
        budget: dict,
    ) -> None:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["model_budget"] = copy.deepcopy(budget)
        checkpoint["completed_node_receipt"] = module._completed_checkpoint_node_receipt(
            node_entry=checkpoint["node"],
            graph_version=checkpoint["graph_version"],
            repair_chain_hash=checkpoint["repair_chain_hash"],
            model_budget_commitment=module._model_budget_receipt_commitment(budget),
        )
        checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(
            checkpoint
        )
        checkpoint_path.write_text(
            json.dumps(checkpoint, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_cross_node_selector_keeps_relevant_summary_beyond_80_and_is_order_invariant(self):
        module = _load_v12_build_module()
        summaries = [
            {
                "node_id": "M-BRIDGE-CLOCK-ANGLE",
                "slot": (index % 20) + 1,
                "slot_role": "near_transfer",
                "evidence_goal": f"unrelated evidence {index}",
                "elicitation_mode": "standard",
                "math_core_signature": f"unrelated-core-{index:03d}",
                "problem_family_id": f"unrelated-family-{index:03d}",
                "core_stem_id": f"unrelated-stem-{index:03d}",
                "prompt_preview": f"unrelated prompt {index}",
                "expected_answer_preview": f"unrelated answer {index}",
            }
            for index in range(100)
        ]
        relevant = {
            "node_id": "M-G7-RATIONAL-MUL-DIV",
            "slot": 19,
            "slot_role": "stretch_readiness_check",
            "evidence_goal": "direct prerequisite evidence for rational mixed operations",
            "elicitation_mode": "standard",
            "math_core_signature": "recent-direct-prerequisite-core",
            "problem_family_id": "recent-direct-prerequisite-family",
            "core_stem_id": "recent-direct-prerequisite-stem",
            "prompt_preview": "direct prerequisite summary placed after the legacy cutoff",
            "expected_answer_preview": "must remain visible to cross-node review",
        }
        summaries[95] = relevant

        forward = self._capture_cross_node_selector_payload(module, summaries=summaries)
        reversed_selection = self._capture_cross_node_selector_payload(
            module,
            summaries=list(reversed(summaries)),
        )

        self.assertLessEqual(len(forward), 80)
        self.assertIn(relevant, forward)
        self.assertIn(relevant, reversed_selection)
        self.assertEqual(forward, reversed_selection)

    def test_out_of_order_completed_checkpoints_require_full_set_rereview_before_reuse(self):
        module = _load_v12_build_module()
        manifest = _manifest(
            ("M-G7-POS-NEG", "M-G7-COMPARE"),
            provider_mode="live_model",
            status="draft_live_model",
        )
        first_node, second_node = manifest["nodes"]
        observed_full_set_review: list[dict] = []

        class FullSetReviewObserved(RuntimeError):
            pass

        def stop_on_full_set_review(route, payload, **_kwargs):
            rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if all(node["node_id"] in rendered for node in (first_node, second_node)):
                observed_full_set_review.append({"agent_key": route.agent_key, "task": route.task})
                raise FullSetReviewObserved("qa observed full-set cross-node re-review")
            self.fail(
                "resume issued model work before presenting the complete checkpoint set to cross-node re-review"
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            checkpoint_dir.mkdir()
            for node_entry in (second_node, first_node):
                checkpoint = _v12_completed_checkpoint_with_repair_chain(
                    module,
                    node_entry,
                    manifest["graph_version"],
                )
                (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                    json.dumps(checkpoint, ensure_ascii=False),
                    encoding="utf-8",
                )

            with mock.patch.object(
                module.model_router,
                "call_structured_json",
                side_effect=stop_on_full_set_review,
            ):
                try:
                    module.build_live(
                        output_path=root / "two-node.json",
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=[first_node["node_id"], second_node["node_id"]],
                        max_rounds=3,
                        max_concurrency=2,
                        resume=True,
                    )
                except FullSetReviewObserved:
                    pass

        self.assertTrue(
            observed_full_set_review,
            "completed checkpoints were silently reused without a full-set cross-node re-review",
        )

    def test_cross_node_rejection_withdraws_only_exact_slot_and_uses_cross_node_stage(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        manifest = _manifest(
            ("M-G7-RATIONAL-MIXED",),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = manifest["nodes"][0]
        node = next(item for item in graph["nodes"] if item["id"] == node_entry["node_id"])
        target_slot = 17
        repair_instruction = {
            "reason": "v12_cross_node_semantic_conflict",
            "slots": [target_slot],
            "source_node_id": "M-G7-RATIONAL-MUL-DIV",
            "source_slot": 19,
            "conflict_commitment_sha256": "c" * 64,
            "repair_instructions": ["Replace only the conflicting mathematical core."],
        }
        untouched_before = {
            int(item["slot"]): question_bank.v12_external_candidate_sha256(item)
            for item in node_entry["items"]
            if int(item["slot"]) != target_slot
        }
        process_calls: list[dict] = []

        def repair_exact_slot(**kwargs):
            process_calls.append(kwargs)
            repaired = copy.deepcopy(node_entry["items"][target_slot - 1])
            repaired["math_core_signature"] = "qa-cross-node-repaired-core"
            repaired["core_stem_id"] = "qa-cross-node-repaired-stem"
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [target_slot],
                "accepted_by_slot": {target_slot: repaired},
                "rejected_slots": [],
                "repair_instructions": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            checkpoint = _incomplete_live_checkpoint(
                node_entry,
                manifest["graph_version"],
                local_round=1,
            )
            checkpoint["accepted_slots"].pop(str(target_slot))
            checkpoint["node"]["items"] = [
                item for item in checkpoint["node"]["items"]
                if int(item["slot"]) != target_slot
            ]
            checkpoint["pending_repair_by_slot"] = {
                str(target_slot): [repair_instruction],
            }
            checkpoint["stage_counters"] = {
                "local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)},
                "node_set_review_round": 1,
                "node_set_repair_rounds_by_slot": {},
                "cross_node_repair_rounds_by_slot": {str(target_slot): 0},
            }
            checkpoint["source_node_candidate_sha256"] = question_bank.v12_node_candidate_sha256(
                checkpoint["node"]
            )
            checkpoint["repair_chain_events"] = []
            checkpoint["repair_chain_head_sha256"] = ""
            _seal_v12_incomplete_checkpoint(checkpoint)
            (checkpoint_dir / f"{node_entry['node_id']}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(
                module.question_bank,
                "validate_external_question_bank_v12",
                return_value={"issues": []},
            ), mock.patch.object(
                module,
                "_node_level_repair_instructions",
                return_value=[],
            ), mock.patch.object(
                module,
                "_node_set_semantic_repair_instructions",
                return_value={
                    "repair_instructions": [],
                    "node_review_artifact": {
                        "agent_key": question_bank.QUESTION_REVIEWER_AGENT_KEY,
                        "phase": "node_set_review",
                        "pipeline_stage": "node_set_review",
                        "stage_attempt": 2,
                    },
                },
            ), mock.patch.object(
                module,
                "_process_live_slot_chunk",
                side_effect=repair_exact_slot,
            ):
                result = module._build_live_node(**_build_live_node_test_kwargs(
                    module,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    checkpoint_dir=checkpoint_dir,
                    max_rounds=3,
                ))

        self.assertEqual([[target_slot]], [call["requested_slots"] for call in process_calls])
        self.assertEqual("cross_node_repair", process_calls[0]["pipeline_stage"])
        self.assertEqual([repair_instruction], process_calls[0]["repair_instructions"])
        untouched_after = {
            int(item["slot"]): question_bank.v12_external_candidate_sha256(item)
            for item in result["items"]
            if int(item["slot"]) != target_slot
        }
        self.assertEqual(untouched_before, untouched_after)

    def test_completed_checkpoint_and_runner_receipt_share_cross_node_context_commitment(self):
        module = _load_v12_build_module()
        manifest = _manifest(
            ("M-G7-POS-NEG",),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = manifest["nodes"][0]
        checkpoint = _v12_completed_checkpoint_with_repair_chain(
            module,
            node_entry,
            manifest["graph_version"],
        )
        runner_receipt = module._runner_receipt_for_manifest(manifest)

        def cross_node_commitments(value, path=""):
            found = {}
            if isinstance(value, dict):
                for key, item in value.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    lowered = child_path.lower()
                    if (
                        "cross_node" in lowered
                        and ("commit" in lowered or "sha256" in lowered)
                        and isinstance(item, str)
                        and len(item) == 64
                    ):
                        found[child_path] = item
                    found.update(cross_node_commitments(item, child_path))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    found.update(cross_node_commitments(item, f"{path}[{index}]"))
            return found

        checkpoint_commitments = cross_node_commitments(checkpoint)
        receipt_commitments = cross_node_commitments(runner_receipt)
        self.assertTrue(
            checkpoint_commitments,
            "completed checkpoint does not commit the cross-node review context",
        )
        self.assertTrue(
            receipt_commitments,
            "runner receipt does not commit the cross-node review context",
        )
        self.assertTrue(
            set(checkpoint_commitments.values()) & set(receipt_commitments.values()),
            "checkpoint and runner receipt do not bind the same cross-node context digest",
        )

    def test_full_bank_runner_receipt_commits_exact_cross_node_rereview_coverage(self):
        module = _load_v12_build_module()
        graph_node_ids = tuple(node["id"] for node in _load_graph()["nodes"])
        manifest = _manifest(
            graph_node_ids,
            provider_mode="live_model",
            status="draft_live_model",
        )
        runner_receipt = module._runner_receipt_for_manifest(manifest)

        candidates: list[dict] = []

        def collect_cross_node_artifacts(value, path=""):
            if isinstance(value, dict):
                lowered_path = path.lower()
                if "cross_node" in lowered_path or any(
                    "cross_node" in str(key).lower() for key in value
                ):
                    candidates.append(value)
                for key, item in value.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    collect_cross_node_artifacts(item, child_path)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    collect_cross_node_artifacts(item, f"{path}[{index}]")

        collect_cross_node_artifacts(runner_receipt)
        exact_coverage = [
            artifact for artifact in candidates
            if int(artifact.get("node_count") or 0) == 56
            and int(artifact.get("item_count") or 0) == 1120
            and any(
                isinstance(value, str) and len(value) == 64
                for key, value in artifact.items()
                if "commit" in str(key).lower() or "sha256" in str(key).lower()
            )
        ]
        self.assertTrue(
            exact_coverage,
            "runner receipt has no committed cross-node re-review artifact covering exact 56/1120 authority",
        )

    def test_model_budget_count_rollback_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            state_path = self._new_budget_state(module, checkpoint_dir)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["semantic_calls"] = 1
            state["provider_attempts"] = 1
            commitment_keys = [
                key for key, value in state.items()
                if isinstance(value, str)
                and len(value) == 64
                and ("commit" in key.lower() or "sha256" in key.lower())
            ]
            if commitment_keys:
                resign_payload = {
                    key: value for key, value in state.items()
                    if key not in commitment_keys
                }
                resigned = module._sha256_json(resign_payload)
                for key in commitment_keys:
                    state[key] = resigned
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*(integrity|commitment|tamper|lineage)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                    run_id="QA-BUDGET-ROLLBACK",
                    max_semantic_calls=20,
                    max_provider_attempts=40,
                )

    def test_model_budget_schema_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            state_path = self._new_budget_state(module, checkpoint_dir)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["schema_version"] = "forged-budget-schema"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(module.model_router.ModelCallError, r"budget.*schema"):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                    run_id="QA-BUDGET-SCHEMA",
                    max_semantic_calls=20,
                    max_provider_attempts=40,
                )

    def test_model_budget_node_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            state_path = self._new_budget_state(module, checkpoint_dir)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["node_id"] = "M-G7-OTHER-NODE"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(module.model_router.ModelCallError, r"budget.*node"):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                    run_id="QA-BUDGET-NODE",
                    max_semantic_calls=20,
                    max_provider_attempts=40,
                )

    def test_model_budget_commitment_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            state_path = self._new_budget_state(module, checkpoint_dir)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            commitment_keys = [
                key for key, value in state.items()
                if isinstance(value, str)
                and len(value) == 64
                and ("commit" in key.lower() or "sha256" in key.lower())
            ]
            self.assertTrue(
                commitment_keys,
                "model budget receipt has no integrity commitment to tamper-test",
            )
            state[commitment_keys[0]] = "0" * 64
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*(integrity|commitment|tamper)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                    run_id="QA-BUDGET-COMMITMENT",
                    max_semantic_calls=20,
                    max_provider_attempts=40,
                )

    def test_generation_full_audit_normal_resume_round_trip_reuses_without_calls(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        node_id = graph["nodes"][0]["id"]
        manifest = _manifest(
            (node_id,),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = manifest["nodes"][0]
        generation_context = module._generation_cross_node_summary_bundle(
            focal_node_id=node_id,
            completed_nodes=[],
            graph=graph,
        )["context"]
        audit_context = module._full_bank_cross_node_summary_bundle(
            focal_node_id=node_id,
            completed_nodes=[node_entry],
            graph=graph,
        )["context"]
        contexts = {
            "generation": generation_context,
            "full_bank_audit": audit_context,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-ROUND-TRIP-BASELINE",
                max_semantic_calls=module.DEFAULT_MAX_SEMANTIC_CALLS,
                max_provider_attempts=module.DEFAULT_MAX_PROVIDER_ATTEMPTS,
            )
            tracker.mark_completed()
            budget = tracker.snapshot()
            checkpoint = _v12_completed_checkpoint_with_repair_chain(
                module,
                node_entry,
                manifest["graph_version"],
            )
            checkpoint["cross_node_summary_contexts"] = contexts
            checkpoint["model_budget"] = budget
            checkpoint["completed_node_receipt"] = module._completed_checkpoint_node_receipt(
                node_entry=node_entry,
                graph_version=manifest["graph_version"],
                repair_chain_hash=checkpoint["repair_chain_hash"],
                cross_node_summary_contexts=contexts,
                model_budget_commitment=module._model_budget_receipt_commitment(budget),
            )
            checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(
                checkpoint
            )
            (checkpoint_dir / f"{node_id}.json").write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )

            with mock.patch.object(
                module.model_router,
                "call_structured_json",
                side_effect=AssertionError("normal resume must not call a model"),
            ):
                result = module.build_live(
                    output_path=root / "round-trip.json",
                    checkpoint_dir=checkpoint_dir,
                    project_root=PROJECT_ROOT,
                    node_ids=[node_id],
                    resume=True,
                )

            receipt = json.loads(Path(result["runner_receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(contexts, receipt["nodes"][0]["cross_node_summary_contexts"])
            self.assertTrue(receipt["nodes"][0]["reused_from_checkpoint"])
            self.assertEqual([], result["automatic_context_rereview_node_ids"])

    def test_related_slot_20_survives_bounded_selection_and_full_registry_candidate_audit(self):
        graph = _load_graph()
        focal_node_id = "M-G7-RATIONAL-MIXED"
        source_node_id = "M-G7-RATIONAL-MUL-DIV"
        source_entries = []
        source_graph_node = next(
            node for node in graph["nodes"] if node["id"] == source_node_id
        )
        selected_graph_nodes = [source_graph_node] + [
            node
            for node in graph["nodes"]
            if node["id"] not in {source_node_id, focal_node_id}
        ][:5]
        for graph_node in selected_graph_nodes:
            node_id = graph_node["id"]
            items = []
            for slot in range(1, 21):
                signature = f"{node_id}-core-{slot}"
                stem = f"{node_id}-stem-{slot}"
                if node_id == source_node_id and slot == 20:
                    signature = "qa-relevant-slot-20-core"
                    stem = "qa-relevant-slot-20-stem"
                items.append({
                    "id": f"{node_id}-{slot}",
                    "slot": slot,
                    "slot_role": "near_transfer",
                    "math_core_signature": signature,
                    "core_stem_id": stem,
                    "problem_family_id": f"{node_id}-family-{slot}",
                    "prompt": f"prompt {node_id} {slot}",
                    "expected_answer": f"answer {node_id} {slot}",
                })
            source_entries.append({"node_id": node_id, "items": items})
        self.assertGreater(
            len(question_bank.v12_cross_node_summary_registry(source_entries, graph)),
            80,
        )
        bundle = question_bank.v12_cross_node_summary_bundle(
            focal_node_id=focal_node_id,
            source_node_entries=source_entries,
            graph=graph,
            registry_scope="qa_full_registry",
        )
        focal_entry = {
            "node_id": focal_node_id,
            "items": [{
                "slot": 17,
                "math_core_signature": "qa-relevant-slot-20-core",
                "core_stem_id": "qa-relevant-slot-20-stem",
            }],
        }
        candidates = question_bank.v12_cross_node_structured_duplicate_candidates(
            focal_node_entry=focal_entry,
            registry=bundle["full_registry"],
        )
        self.assertIn(
            (source_node_id, 20),
            {
                (summary["node_id"], int(summary["slot"]))
                for summary in bundle["selected_summaries"]
            },
        )
        self.assertIn(
            (source_node_id, 20),
            {
                (candidate["source_node_id"], int(candidate["source_slot"]))
                for candidate in candidates
            },
        )

    def test_full_registry_duplicate_outside_selected_80_reaches_matching_focal_shard(self):
        module = _load_v12_build_module()
        graph = _load_graph()
        focal_node_id = "M-G7-RATIONAL-MIXED"
        source_entries = []
        for graph_node in graph["nodes"]:
            node_id = graph_node["id"]
            if node_id == focal_node_id:
                continue
            source_entries.append({
                "node_id": node_id,
                "items": [
                    {
                        "id": f"{node_id}-{slot}",
                        "slot": slot,
                        "slot_role": "near_transfer",
                        "math_core_signature": f"{node_id}-core-{slot}",
                        "core_stem_id": f"{node_id}-stem-{slot}",
                        "problem_family_id": f"{node_id}-family-{slot}",
                        "prompt": f"prompt {node_id} {slot}",
                        "expected_answer": f"answer {node_id} {slot}",
                    }
                    for slot in range(1, 21)
                ],
            })
        bundle = question_bank.v12_cross_node_summary_bundle(
            focal_node_id=focal_node_id,
            source_node_entries=source_entries,
            graph=graph,
            registry_scope="qa_full_registry_outside_selected",
        )
        selected_keys = {
            (summary["node_id"], int(summary["slot"]))
            for summary in bundle["selected_summaries"]
        }
        outside = next(
            summary
            for summary in bundle["full_registry"]
            if (summary["node_id"], int(summary["slot"])) not in selected_keys
        )
        manifest = _manifest(
            (focal_node_id,),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = copy.deepcopy(manifest["nodes"][0])
        node_entry.pop("node_review_artifact", None)
        node_entry["items"][0]["math_core_signature"] = outside["math_core_signature"]
        node_entry["items"][0]["core_stem_id"] = outside["core_stem_id"]
        node = next(item for item in graph["nodes"] if item["id"] == focal_node_id)
        captured: dict[str, object] = {}

        def capture_first_focal_shard(**kwargs):
            captured.update(kwargs["untrusted_payload"])
            raise RuntimeError("qa captured full-registry duplicate candidate")

        with mock.patch.object(
            module,
            "_call_v12_batch_agent",
            side_effect=capture_first_focal_shard,
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate candidate"):
                module._node_set_semantic_repair_instructions(
                    node_entry=node_entry,
                    node=node,
                    graph=graph,
                    graph_version=manifest["graph_version"],
                    contract=module._load_json(module.NODE_SET_REVIEWER_CONTRACT_PATH),
                    prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
                    global_finalizer_contract=module._load_json(module.GLOBAL_FINALIZER_CONTRACT_PATH),
                    global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8"),
                    accepted_core_summaries=bundle["selected_summaries"],
                    cross_node_summary_registry=bundle["full_registry"],
                )

        self.assertNotIn(
            (outside["node_id"], int(outside["slot"])),
            selected_keys,
        )
        self.assertIn(
            (outside["node_id"], int(outside["slot"])),
            {
                (candidate["source_node_id"], int(candidate["source_slot"]))
                for candidate in captured["cross_node_structured_duplicate_candidates"]
            },
        )

    def test_budget_v2_dual_copy_downgrade_to_legacy_zero_fails_closed(self):
        module = _load_v12_build_module()
        node_id = "M-G7-RATIONAL-MIXED"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-DOWNGRADE-BASELINE",
                max_semantic_calls=20,
                max_provider_attempts=40,
            )
            tracker.reserve_semantic_call("candidate")
            tracker.reserve_semantic_call("review")
            tracker.reserve_provider_attempt("candidate")
            tracker.reserve_provider_attempt("candidate_retry")
            tracker.reserve_provider_attempt("review")
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = checkpoint_dir / f"{node_id}.json"
            checkpoint_path.write_text(
                json.dumps({"node_id": node_id, "model_budget": tracker.snapshot()}),
                encoding="utf-8",
            )
            downgraded = {
                "schema_version": module.V12_MODEL_BUDGET_LEGACY_SCHEMA_VERSION,
                "node_id": node_id,
                "semantic_calls": 0,
                "provider_attempts": 0,
                "max_semantic_calls": 20,
                "max_provider_attempts": 40,
                "status": "active",
                "run_ids": ["QA-DOWNGRADE-FORGED"],
            }
            tracker.path.write_text(json.dumps(downgraded), encoding="utf-8")
            checkpoint_path.write_text(
                json.dumps({"node_id": node_id, "model_budget": downgraded}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*(downgrade|rollback|migration|authority)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-DOWNGRADE-ATTEMPT",
                    max_semantic_calls=20,
                    max_provider_attempts=40,
                )

    def test_full_resume_inherits_heterogeneous_historical_budget_caps_per_node(self):
        module = _load_v12_build_module()
        historical_caps = {
            "M-G7-NUMBER-LINE": (512, 1536),
            "M-G7-RATIONAL-MIXED": (120, 300),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            for node_id, (semantic_cap, provider_cap) in historical_caps.items():
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id=f"QA-HISTORICAL-{node_id}",
                    max_semantic_calls=semantic_cap,
                    max_provider_attempts=provider_cap,
                )

            observed = {}

            def capture_locked_build(**kwargs):
                observed.update({
                    node_id: (
                        tracker.max_semantic_calls,
                        tracker.max_provider_attempts,
                    )
                    for node_id, tracker in kwargs["model_budget_by_node"].items()
                })
                return {"mode": "captured"}

            with mock.patch.object(
                module,
                "_build_live_locked",
                side_effect=capture_locked_build,
            ):
                result = module.build_live(
                    output_path=root / "heterogeneous-resume.json",
                    checkpoint_dir=checkpoint_dir,
                    project_root=PROJECT_ROOT,
                    node_ids=list(historical_caps),
                    max_semantic_calls=33,
                    max_provider_attempts=99,
                    resume=True,
                )

            self.assertEqual({"mode": "captured"}, result)
            self.assertEqual(historical_caps, observed)

    def test_budget_state_checkpoint_cap_divergence_fails_closed(self):
        module = _load_v12_build_module()
        node_id = "M-G7-RATIONAL-MIXED"
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-CAP-DIVERGENCE-BASELINE",
                max_semantic_calls=120,
                max_provider_attempts=300,
            )
            checkpoint_budget = tracker.snapshot()
            checkpoint_budget["max_semantic_calls"] = 512
            checkpoint_budget["max_provider_attempts"] = 1536
            checkpoint_budget["integrity_sha256"] = module._model_budget_integrity_sha256(
                checkpoint_budget
            )
            (checkpoint_dir / f"{node_id}.json").write_text(
                json.dumps({"node_id": node_id, "model_budget": checkpoint_budget}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*cap.*(diverg|mismatch)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-CAP-DIVERGENCE-RESUME",
                    max_semantic_calls=33,
                    max_provider_attempts=99,
                )

    def test_new_node_budget_uses_cli_caps_as_initial_authority(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id="M-G7-NUMBER-LINE",
                run_id="QA-NEW-NODE-CLI-CAPS",
                max_semantic_calls=7,
                max_provider_attempts=13,
            )
            snapshot = tracker.snapshot()
            self.assertEqual(7, snapshot["max_semantic_calls"])
            self.assertEqual(13, snapshot["max_provider_attempts"])
            self.assertFalse(
                module._model_budget_migration_transaction_root(
                    checkpoint_dir
                ).exists()
            )

    def test_legacy_state_cap_pollution_reconciles_to_sealed_completed_checkpoint(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            raw_state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            raw_state_sha256 = module._sha256_json(raw_state_payload)
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-RECONCILIATION",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            snapshot = tracker.snapshot()
            self.assertEqual((120, 300), (
                snapshot["max_semantic_calls"],
                snapshot["max_provider_attempts"],
            ))
            migration = next(
                item for item in snapshot["migrations"]
                if item.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            self.assertEqual(raw_state_sha256, migration["state_payload_sha256"])
            self.assertEqual(
                {"semantic_calls": 11, "provider_attempts": 13},
                migration["equal_counts"],
            )
            self.assertEqual(
                "schema_v4_uncommitted",
                migration["completed_receipt_budget_commitment_mode"],
            )
            self.assertEqual(
                raw_state_payload,
                migration["source_state_payload"],
            )
            self.assertEqual(
                {
                    "state_payload_sha256",
                    "checkpoint_payload_sha256",
                    "checkpoint_budget_sha256",
                    "completed_node_receipt_sha256",
                    "completed_model_budget_commitment_sha256",
                    "checkpoint_integrity_sha256",
                    "semantic_evidence_commitment_sha256",
                },
                set(migration["source_evidence"]),
            )
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            self.assertEqual(migration, marker["legacy_cap_reconciliation"])
            transaction_dirs = list(
                module._model_budget_migration_transaction_root(
                    checkpoint_dir
                ).iterdir()
            )
            self.assertEqual(1, len(transaction_dirs))
            transaction_manifest = json.loads(
                (transaction_dirs[0] / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("completed", transaction_manifest["phase"])
            self.assertTrue(
                (transaction_dirs[0] / "completion-receipt.json").is_file()
            )
            state_transaction_entry = next(
                entry
                for entry in transaction_manifest["files"]
                if entry["node_id"] == node_id and entry["role"] == "state"
            )
            original_state_bytes = (
                transaction_dirs[0] / state_transaction_entry["backup_path"]
            ).read_bytes()
            self.assertEqual(
                hashlib.sha256(original_state_bytes).hexdigest(),
                state_transaction_entry["original_bytes_sha256"],
            )
            self.assertEqual(
                raw_state_payload,
                json.loads(original_state_bytes.decode("utf-8")),
            )
            recovered = module._read_completed_checkpoint(
                checkpoint_dir,
                node_id=node_id,
                graph=_load_graph(),
                graph_version=_graph_version(),
            )
            self.assertIsNotNone(recovered)
            tracker.reserve_semantic_call("qa_post_reconciliation_call")
            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-RECONCILIATION-RESUME",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            ).snapshot()
            self.assertEqual(12, resumed["semantic_calls"])
            self.assertEqual(120, resumed["max_semantic_calls"])

    def test_reconciled_budget_allows_completed_checkpoint_to_advance_and_resume(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-ADVANCE-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            tracker.reserve_semantic_call("qa_post_migration_semantic")
            tracker.reserve_provider_attempt("qa_post_migration_provider")
            tracker.mark_completed()
            advanced_budget = tracker.snapshot()
            migration = next(
                item
                for item in advanced_budget["migrations"]
                if item.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            self.assertEqual(
                {"semantic_calls": 11, "provider_attempts": 13},
                migration["equal_counts"],
            )
            self.assertEqual(
                (11, 13),
                (
                    advanced_budget["counter_events"][0]["semantic_calls"],
                    advanced_budget["counter_events"][0]["provider_attempts"],
                ),
            )
            self.assertEqual(
                [
                    "legacy_baseline_import",
                    "semantic_call_reserved",
                    "provider_attempt_reserved",
                ],
                [event["event_type"] for event in advanced_budget["counter_events"]],
            )
            self._seal_completed_checkpoint_budget(
                module,
                checkpoint_path,
                advanced_budget,
            )

            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-ADVANCE-RESUME",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            ).snapshot()
            self.assertEqual(12, resumed["semantic_calls"])
            self.assertEqual(14, resumed["provider_attempts"])
            self.assertEqual(120, resumed["max_semantic_calls"])
            self.assertEqual(300, resumed["max_provider_attempts"])

    def test_reconciled_budget_rejects_advanced_checkpoint_count_without_counter_event(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-MISSING-EVENT-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            forged_budget = tracker.snapshot()
            forged_budget["semantic_calls"] += 1
            forged_budget["integrity_sha256"] = module._model_budget_integrity_sha256(
                forged_budget
            )
            self._seal_completed_checkpoint_budget(
                module,
                checkpoint_path,
                forged_budget,
            )

            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"checkpoint counter commitment mismatch",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-MISSING-EVENT-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_reconciled_budget_rejects_forked_post_migration_ledger(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-FORK-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            checkpoint_branch = tracker.snapshot()
            tracker.reserve_semantic_call("qa_state_branch")

            checkpoint_branch["provider_attempts"] += 1
            fork_event = {
                "sequence": 2,
                "event_type": "provider_attempt_reserved",
                "phase": "qa_checkpoint_branch",
                "semantic_calls": checkpoint_branch["semantic_calls"],
                "provider_attempts": checkpoint_branch["provider_attempts"],
                "previous_event_sha256": checkpoint_branch[
                    "counter_chain_head_sha256"
                ],
            }
            fork_event["event_sha256"] = module._model_budget_event_sha256(fork_event)
            checkpoint_branch["counter_events"].append(fork_event)
            checkpoint_branch["counter_chain_head_sha256"] = fork_event["event_sha256"]
            checkpoint_branch["integrity_sha256"] = module._model_budget_integrity_sha256(
                checkpoint_branch
            )
            self._seal_completed_checkpoint_budget(
                module,
                checkpoint_path,
                checkpoint_branch,
            )

            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"state/checkpoint chain diverged",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-FORK-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_reconciled_budget_rejects_rebased_migration_after_ledger_extension(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-REBASE-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            tracker.reserve_semantic_call("qa_post_migration_semantic")
            tracker.reserve_provider_attempt("qa_post_migration_provider")
            tracker.mark_completed()

            state = json.loads(tracker.path.read_text(encoding="utf-8"))
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            reconciliation = next(
                migration
                for migration in state["migrations"]
                if migration.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            reconciliation["equal_counts"]["semantic_calls"] += 1
            reconciliation["migration_commitment_sha256"] = module._sha256_json({
                key: value
                for key, value in reconciliation.items()
                if key != "migration_commitment_sha256"
            })
            previous = ""
            for event in state["counter_events"]:
                event["semantic_calls"] += 1
                event["previous_event_sha256"] = previous
                if event["event_type"] == "legacy_baseline_import":
                    event["legacy_cap_reconciliation_commitment_sha256"] = (
                        reconciliation["migration_commitment_sha256"]
                    )
                event["event_sha256"] = module._model_budget_event_sha256(event)
                previous = event["event_sha256"]
            state["semantic_calls"] += 1
            state["counter_chain_head_sha256"] = previous
            state["integrity_sha256"] = module._model_budget_integrity_sha256(state)

            marker["legacy_cap_reconciliation"] = copy.deepcopy(reconciliation)
            marker["minimum_semantic_calls"] += 1
            marker["counter_chain_head_sha256"] = previous
            marker["budget_integrity_sha256"] = state["integrity_sha256"]
            marker["integrity_sha256"] = module._model_budget_marker_integrity_sha256(
                marker
            )
            tracker.path.write_text(json.dumps(state), encoding="utf-8")
            tracker.marker_path.write_text(json.dumps(marker), encoding="utf-8")
            self._seal_completed_checkpoint_budget(module, checkpoint_path, state)

            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"no unique completed migration transaction authority",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-REBASE-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_v2_advanced_checkpoint_requires_current_budget_receipt_commitment(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-UNCOMMITTED-V2-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            tracker.reserve_semantic_call("qa_post_migration_semantic")
            tracker.reserve_provider_attempt("qa_post_migration_provider")
            tracker.mark_completed()

            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["model_budget"] = tracker.snapshot()
            self.assertNotIn(
                "model_budget_commitment",
                checkpoint["completed_node_receipt"],
            )
            checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(
                checkpoint
            )
            checkpoint_path.write_text(
                json.dumps(checkpoint, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"v2.*receipt.*commit",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-UNCOMMITTED-V2-TRACKER",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"v2.*receipt.*commit",
            ):
                module._read_completed_checkpoint(
                    checkpoint_dir,
                    node_id=node_id,
                    graph=_load_graph(),
                    graph_version=_graph_version(),
                )

    def test_uncommitted_receipt_requires_explicit_legacy_v1_budget(self):
        module = _load_v12_build_module()
        for case in ("missing", "unknown_schema"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                checkpoint_dir = Path(tmp) / "checkpoints"
                node_id, _state_path, checkpoint_path = self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                )
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if case == "missing":
                    checkpoint.pop("model_budget", None)
                else:
                    checkpoint["model_budget"]["schema_version"] = "unknown-budget-schema"
                checkpoint["checkpoint_integrity_sha256"] = module._checkpoint_integrity_sha256(
                    checkpoint
                )
                checkpoint_path.write_text(
                    json.dumps(checkpoint, ensure_ascii=False),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    module.model_router.ModelCallError,
                    r"completed checkpoint.*budget.*schema",
                ):
                    module._ModelBudgetTracker(
                        checkpoint_dir=checkpoint_dir,
                        node_id=node_id,
                        run_id=f"QA-STRICT-CAP-{case}-TRACKER",
                        max_semantic_calls=512,
                        max_provider_attempts=1536,
                    )
                with self.assertRaisesRegex(
                    module.model_router.ModelCallError,
                    r"completed checkpoint.*budget.*schema",
                ):
                    module._read_completed_checkpoint(
                        checkpoint_dir,
                        node_id=node_id,
                        graph=_load_graph(),
                        graph_version=_graph_version(),
                    )

    def test_legacy_state_cap_reconciliation_rejects_state_count_increment(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                state_semantic_delta=1,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*(count|reconcil|diverg)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-COUNT-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_checkpoint_seal_tamper(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                tamper_checkpoint_seal=True,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"checkpoint.*(seal|integrity)",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-SEAL-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_unsealed_completed_checkpoint(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                remove_checkpoint_seal=True,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"reconciliation.*sealed checkpoint integrity",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-UNSEALED-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_completed_receipt_tamper(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                tamper_completed_receipt=True,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"completed checkpoint receipt integrity",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-RECEIPT-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_declared_budget_commitment_mismatch(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                receipt_commits_budget=True,
                tamper_committed_budget=True,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"completed receipt (?:cap authority|commitment) mismatch",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-COMMITTED-RECEIPT-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_reverse_cap_expansion(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                checkpoint_caps=(512, 1536),
                state_caps=(120, 300),
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"cannot expand polluted state caps",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-REVERSE-EXPANSION-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_mixed_cap_direction(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                checkpoint_caps=(600, 300),
                state_caps=(512, 1536),
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"cannot expand polluted state caps",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-MIXED-DIRECTION-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_build_live_budget_preflight_failure_leaves_earlier_node_unchanged(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            first_node_id, first_state_path, _first_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                )
            )
            second_node_id, _second_state_path, _second_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-NUMBER-LINE",
                    state_semantic_delta=1,
                )
            )
            first_state_before = first_state_path.read_bytes()
            first_marker_path = (
                checkpoint_dir
                / ".run-state"
                / f"{first_node_id}.model-budget-upgrade.json"
            )
            self.assertFalse(first_marker_path.exists())
            with mock.patch.object(
                module,
                "_build_live_locked",
                side_effect=AssertionError("preflight failure must stop before live build"),
            ), self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*count mismatch",
            ):
                module.build_live(
                    output_path=root / "preflight-no-write.json",
                    checkpoint_dir=checkpoint_dir,
                    project_root=PROJECT_ROOT,
                    node_ids=[first_node_id, second_node_id],
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )
            self.assertEqual(first_state_before, first_state_path.read_bytes())
            self.assertFalse(first_marker_path.exists())

    def _assert_batch_migration_write_failure_rolls_back(self, *, failed_role: str):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            first_node_id, first_state_path, _first_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-NUMBER-LINE",
                )
            )
            second_node_id, second_state_path, _second_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                )
            )
            original_state_bytes = {
                first_node_id: first_state_path.read_bytes(),
                second_node_id: second_state_path.read_bytes(),
            }
            original_install = module._install_model_budget_transaction_target

            def fail_second_node_target(**kwargs):
                entry = kwargs["entry"]
                if (
                    entry["node_id"] == second_node_id
                    and entry["role"] == failed_role
                ):
                    raise OSError(f"injected second-node {failed_role} write failure")
                return original_install(**kwargs)

            with mock.patch.object(
                module,
                "_install_model_budget_transaction_target",
                side_effect=fail_second_node_target,
            ), mock.patch.object(
                module,
                "_build_live_locked",
                side_effect=AssertionError("transaction failure must stop before live build"),
            ), self.assertRaisesRegex(
                OSError,
                rf"second-node {failed_role} write failure",
            ):
                module.build_live(
                    output_path=root / f"batch-{failed_role}-failure.json",
                    checkpoint_dir=checkpoint_dir,
                    project_root=PROJECT_ROOT,
                    node_ids=[first_node_id, second_node_id],
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

            for node_id, state_path in (
                (first_node_id, first_state_path),
                (second_node_id, second_state_path),
            ):
                self.assertEqual(original_state_bytes[node_id], state_path.read_bytes())
                self.assertFalse(
                    (
                        checkpoint_dir
                        / ".run-state"
                        / f"{node_id}.model-budget-upgrade.json"
                    ).exists()
                )
            transaction_dirs = list(
                module._model_budget_migration_transaction_root(
                    checkpoint_dir
                ).iterdir()
            )
            self.assertEqual(1, len(transaction_dirs))
            manifest = json.loads(
                (transaction_dirs[0] / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("rolled_back", manifest["phase"])
            self.assertTrue(
                (transaction_dirs[0] / "rollback-receipt.json").is_file()
            )
            self.assertFalse(
                (transaction_dirs[0] / "completion-receipt.json").exists()
            )

    def test_batch_migration_second_node_state_write_failure_rolls_back_all_nodes(self):
        self._assert_batch_migration_write_failure_rolls_back(failed_role="state")

    def test_batch_migration_second_node_marker_write_failure_rolls_back_all_nodes(self):
        self._assert_batch_migration_write_failure_rolls_back(failed_role="marker")

    def test_interrupted_batch_migration_is_rolled_back_on_next_tracker_initialization(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            first_node_id, first_state_path, _first_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-NUMBER-LINE",
                )
            )
            second_node_id, second_state_path, _second_checkpoint_path = (
                self._write_legacy_cap_divergence_fixture(
                    module,
                    checkpoint_dir,
                    node_id="M-G7-RATIONAL-MIXED",
                )
            )
            original_state_bytes = {
                first_node_id: first_state_path.read_bytes(),
                second_node_id: second_state_path.read_bytes(),
            }
            original_install = module._install_model_budget_transaction_target

            def interrupt_second_state(**kwargs):
                entry = kwargs["entry"]
                if entry["node_id"] == second_node_id and entry["role"] == "state":
                    raise KeyboardInterrupt("injected process interruption")
                return original_install(**kwargs)

            with mock.patch.object(
                module,
                "_install_model_budget_transaction_target",
                side_effect=interrupt_second_state,
            ), self.assertRaisesRegex(
                KeyboardInterrupt,
                "injected process interruption",
            ):
                module.build_live(
                    output_path=root / "batch-interrupted.json",
                    checkpoint_dir=checkpoint_dir,
                    project_root=PROJECT_ROOT,
                    node_ids=[first_node_id, second_node_id],
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

            self.assertNotEqual(
                original_state_bytes[first_node_id],
                first_state_path.read_bytes(),
            )
            transaction_dir = next(
                module._model_budget_migration_transaction_root(
                    checkpoint_dir
                ).iterdir()
            )
            interrupted_manifest = json.loads(
                (transaction_dir / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("committing", interrupted_manifest["phase"])
            self.assertFalse((transaction_dir / "completion-receipt.json").exists())

            module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=first_node_id,
                run_id="QA-TRANSACTION-RECOVERY-PREFLIGHT",
                max_semantic_calls=512,
                max_provider_attempts=1536,
                persist_on_init=False,
            )

            for node_id, state_path in (
                (first_node_id, first_state_path),
                (second_node_id, second_state_path),
            ):
                self.assertEqual(original_state_bytes[node_id], state_path.read_bytes())
                self.assertFalse(
                    (
                        checkpoint_dir
                        / ".run-state"
                        / f"{node_id}.model-budget-upgrade.json"
                    ).exists()
                )
            recovered_manifest = json.loads(
                (transaction_dir / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("rolled_back", recovered_manifest["phase"])
            self.assertTrue((transaction_dir / "rollback-receipt.json").is_file())

    def test_completed_targets_without_receipt_are_completed_on_next_initialization(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            original_atomic_write = module._atomic_write_checkpoint

            def interrupt_before_completion_receipt(path, payload):
                if path.name == "completion-receipt.json":
                    raise KeyboardInterrupt("injected receipt interruption")
                return original_atomic_write(path, payload)

            with mock.patch.object(
                module,
                "_atomic_write_checkpoint",
                side_effect=interrupt_before_completion_receipt,
            ), self.assertRaisesRegex(
                KeyboardInterrupt,
                "injected receipt interruption",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-TRANSACTION-RECEIPT-INTERRUPTION",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

            transaction_dir = next(
                module._model_budget_migration_transaction_root(
                    checkpoint_dir
                ).iterdir()
            )
            manifest = json.loads(
                (transaction_dir / "transaction.json").read_text(encoding="utf-8")
            )
            self.assertEqual("completed", manifest["phase"])
            self.assertFalse((transaction_dir / "completion-receipt.json").exists())

            resumed = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-TRANSACTION-RECEIPT-RECOVERY",
                max_semantic_calls=512,
                max_provider_attempts=1536,
                persist_on_init=False,
            )
            self.assertEqual(120, resumed.max_semantic_calls)
            self.assertTrue((transaction_dir / "completion-receipt.json").is_file())
            module._validate_model_budget_migration_completion(
                transaction_dir,
                module._read_model_budget_transaction_manifest(transaction_dir),
            )

    def test_legacy_state_cap_reconciliation_rejects_existing_upgrade_marker(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                write_existing_marker=True,
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"cannot reconcile across existing upgrade authority",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-EXISTING-MARKER-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_extra_legacy_ledger_authority(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
                state_extra_authority={"counter_events": []},
            )
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"legacy state contains additional call authority",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-LEDGER-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_state_cap_reconciliation_rejects_v2_state(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["schema_version"] = module.V12_MODEL_BUDGET_SCHEMA_VERSION
            state["counter_events"] = []
            state["counter_chain_head_sha256"] = ""
            state["migrations"] = []
            state["integrity_sha256"] = module._model_budget_integrity_sha256(state)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"requires legacy v1 state and checkpoint",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-V2-STATE-REJECT",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_cap_reconciliation_marker_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-MARKER-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            marker["legacy_cap_reconciliation"]["target_checkpoint_caps"][
                "max_semantic_calls"
            ] = 121
            tracker.marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"budget.*marker.*integrity",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-MARKER-TAMPER",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_cap_reconciliation_rehashed_marker_source_tamper_fails_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-REHASHED-MARKER-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            reconciliation = marker["legacy_cap_reconciliation"]
            forged_digest = "f" * 64
            reconciliation["source_evidence"]["checkpoint_payload_sha256"] = forged_digest
            reconciliation["checkpoint_payload_sha256"] = forged_digest
            reconciliation["migration_commitment_sha256"] = module._sha256_json({
                key: value
                for key, value in reconciliation.items()
                if key != "migration_commitment_sha256"
            })
            marker["integrity_sha256"] = module._model_budget_marker_integrity_sha256(
                marker
            )
            tracker.marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"marker reconciliation diverges from state migration authority",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-REHASHED-MARKER-TAMPER",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_cap_reconciliation_resigned_state_marker_and_migration_still_fail_closed(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _legacy_state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-CROSS-AUTHORITY-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            state = json.loads(tracker.path.read_text(encoding="utf-8"))
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            state_reconciliation = next(
                migration
                for migration in state["migrations"]
                if migration.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            marker_reconciliation = marker["legacy_cap_reconciliation"]
            for reconciliation in (state_reconciliation, marker_reconciliation):
                reconciliation["equal_counts"]["semantic_calls"] += 1
                reconciliation["migration_commitment_sha256"] = module._sha256_json({
                    key: value
                    for key, value in reconciliation.items()
                    if key != "migration_commitment_sha256"
                })
            baseline = state["counter_events"][0]
            baseline["semantic_calls"] += 1
            baseline["legacy_cap_reconciliation_commitment_sha256"] = (
                state_reconciliation["migration_commitment_sha256"]
            )
            baseline["event_sha256"] = module._model_budget_event_sha256(baseline)
            state["semantic_calls"] += 1
            state["counter_chain_head_sha256"] = baseline["event_sha256"]
            state["integrity_sha256"] = module._model_budget_integrity_sha256(state)
            marker["minimum_semantic_calls"] += 1
            marker["counter_chain_head_sha256"] = baseline["event_sha256"]
            marker["budget_integrity_sha256"] = state["integrity_sha256"]
            marker["integrity_sha256"] = module._model_budget_marker_integrity_sha256(
                marker
            )
            tracker.path.write_text(json.dumps(state), encoding="utf-8")
            tracker.marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"reconciliation cross-authority commitment mismatch",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-CROSS-AUTHORITY-TAMPER",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_legacy_cap_reconciliation_resigned_source_caps_still_require_original_transaction_bytes(self):
        module = _load_v12_build_module()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            node_id, _legacy_state_path, _checkpoint_path = self._write_legacy_cap_divergence_fixture(
                module,
                checkpoint_dir,
            )
            tracker = module._ModelBudgetTracker(
                checkpoint_dir=checkpoint_dir,
                node_id=node_id,
                run_id="QA-STRICT-CAP-TRANSACTION-AUTHORITY-BASELINE",
                max_semantic_calls=512,
                max_provider_attempts=1536,
            )
            state = json.loads(tracker.path.read_text(encoding="utf-8"))
            marker = json.loads(tracker.marker_path.read_text(encoding="utf-8"))
            state_reconciliation = next(
                migration
                for migration in state["migrations"]
                if migration.get("migration_reason")
                == "legacy_state_cap_pollution_reconciled_to_sealed_checkpoint"
            )
            marker_reconciliation = marker["legacy_cap_reconciliation"]
            for reconciliation in (state_reconciliation, marker_reconciliation):
                source_state = reconciliation["source_state_payload"]
                source_state["max_semantic_calls"] = 1024
                source_state["max_provider_attempts"] = 3072
                reconciliation["original_state_caps"] = {
                    "max_semantic_calls": 1024,
                    "max_provider_attempts": 3072,
                }
                forged_source_sha256 = module._sha256_json(source_state)
                reconciliation["state_payload_sha256"] = forged_source_sha256
                reconciliation["source_evidence"][
                    "state_payload_sha256"
                ] = forged_source_sha256
                reconciliation["migration_commitment_sha256"] = module._sha256_json({
                    key: value
                    for key, value in reconciliation.items()
                    if key != "migration_commitment_sha256"
                })
            baseline = state["counter_events"][0]
            baseline["legacy_cap_reconciliation_commitment_sha256"] = (
                state_reconciliation["migration_commitment_sha256"]
            )
            baseline["legacy_cap_source_state_payload_sha256"] = (
                state_reconciliation["state_payload_sha256"]
            )
            baseline["event_sha256"] = module._model_budget_event_sha256(baseline)
            state["counter_chain_head_sha256"] = baseline["event_sha256"]
            state["integrity_sha256"] = module._model_budget_integrity_sha256(state)
            marker["counter_chain_head_sha256"] = baseline["event_sha256"]
            marker["budget_integrity_sha256"] = state["integrity_sha256"]
            marker["integrity_sha256"] = module._model_budget_marker_integrity_sha256(
                marker
            )
            tracker.path.write_text(json.dumps(state), encoding="utf-8")
            tracker.marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"no unique completed migration transaction authority",
            ):
                module._ModelBudgetTracker(
                    checkpoint_dir=checkpoint_dir,
                    node_id=node_id,
                    run_id="QA-STRICT-CAP-TRANSACTION-AUTHORITY-TAMPER",
                    max_semantic_calls=512,
                    max_provider_attempts=1536,
                )

    def test_partial_node_review_checkpoint_requires_atomic_cross_node_context(self):
        module = _load_v12_build_module()
        manifest = _manifest(
            ("M-G7-RATIONAL-MIXED",),
            provider_mode="live_model",
            status="draft_live_model",
        )
        node_entry = copy.deepcopy(manifest["nodes"][0])
        partial_artifact = copy.deepcopy(node_entry["node_review_artifact"])
        partial_artifact["verdict"] = "pending"
        partial_artifact["constituent_reviews"] = partial_artifact["constituent_reviews"][:1]
        partial_artifact.pop("global_finalizer", None)
        node_entry["node_review_artifact"] = partial_artifact
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp) / "checkpoints"
            checkpoint_dir.mkdir()
            with self.assertRaisesRegex(
                module.model_router.ModelCallError,
                r"checkpoint.*review.*context",
            ):
                module._write_checkpoint(
                    checkpoint_dir,
                    node_id=node_entry["node_id"],
                    graph_version=manifest["graph_version"],
                    rounds_used=1,
                    rejected_rounds=0,
                    report={"issues": []},
                    node_entry=node_entry,
                    status="incomplete",
                    slot_rounds={slot: 1 for slot in range(1, 21)},
                    pending_repair_by_slot={},
                    stage_counters={
                        "local_item_rounds_by_slot": {str(slot): 1 for slot in range(1, 21)},
                        "node_set_review_round": 1,
                    },
                    repair_chain_events=[],
                    cross_node_context_required=True,
                )


if __name__ == "__main__":
    unittest.main()
