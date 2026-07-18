from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from learning_system import model_router, question_bank


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "data/knowledge_graphs/math/math_knowledge_graph_v2.json"
FIXTURE_ROOT = PROJECT_ROOT / "tests/fixtures/v12_force_v6_sources"
NUMBER_LINE_SOURCE = FIXTURE_ROOT / "M-G7-NUMBER-LINE.v5-source.json.gz"
PROCESS_SOURCE = FIXTURE_ROOT / "M-BRIDGE-SOLUTION-HABIT.pilot-source.json.gz"
PROCESS_LEGACY_SUPERSESSION_BACKUP = (
    FIXTURE_ROOT / "M-BRIDGE-SOLUTION-HABIT.legacy-supersession-source.json.gz"
)
PINNED_SOURCE_SHA256 = {
    NUMBER_LINE_SOURCE.name: "21777ba981cf765ec1463c91f4cbb81ccbccf6427e6730fb7652367fbed47e47",
    PROCESS_SOURCE.name: "8b1634b712800807ef704e4251299c1a5287e3fc671d62646f76de8e4615d9ef",
    PROCESS_LEGACY_SUPERSESSION_BACKUP.name: "91640d52c775dd8f11feb9b6571fd6c56e7d2010d5ddbcf9c2efee276b9cca19",
}
FORCE_OPERATION_TOKEN = "number-line-slot20-standard-op1"
NEXT_FORCE_OPERATION_TOKEN = "number-line-slot20-standard-op2"
TERMINAL_PROCESS_OPERATION_TOKEN = "solution-habit-slot20-terminal-op1"


def _load_builder():
    path = PROJECT_ROOT / "scripts/build_math_question_bank_v12.py"
    spec = importlib.util.spec_from_file_location(
        "build_math_question_bank_v12_force_slot_mode_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _graph() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _pinned_source_bytes(path: Path) -> bytes:
    with gzip.open(path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != PINNED_SOURCE_SHA256[path.name]:
        raise AssertionError(f"force fixture source hash mismatch: {path.name}")
    return raw


def _approved_global_judgment(node_entry: dict, graph_version: str) -> dict:
    evidence_moves = list(question_bank.V12_PRIMARY_EVIDENCE_MOVES)
    answer_paths = list(question_bank.V12_ANSWER_PATH_FAMILIES)
    representations = list(question_bank.V12_REPRESENTATION_FAMILIES)
    classifications = []
    for index, item in enumerate(sorted(node_entry["items"], key=lambda value: int(value["slot"]))):
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
            "reason": "version-pinned v6 force fixture semantic classification",
        })
    return {
        "schema_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_RESPONSE_SCHEMA_VERSION,
        "node_id": node_entry["node_id"],
        "graph_version": graph_version,
        "question_bank_version": question_bank.QUESTION_BANK_V12_VERSION,
        "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_FINALIZER_MODEL_EVIDENCE_VERSION,
        "item_classifications": classifications,
        "homogeneous_clusters": [],
        "distribution_scores": {
            key: 0.95 for key in question_bank.V12_NODE_SET_DISTRIBUTION_SCORE_KEYS
        },
        "repetitive_instruction_clusters": [],
        "duplicate_groups": [],
        "confidence": 0.95,
        "reasons": ["version-pinned v6 force fixture approved"],
        "repair_plan": [],
    }


def _upgrade_node_to_v6(module, source: dict) -> dict:
    node_entry = copy.deepcopy(source["node"])
    for item in node_entry["items"]:
        child_surface = question_bank.canonical_child_surface_projection(item)
        item["prompt_format"] = child_surface["prompt_format"]
        item["prompt"] = child_surface["prompt"]
        item["interaction_schema"] = child_surface["interaction_schema"]
        review = item["review_artifact"]
        review["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
        review["child_surface_sha256"] = question_bank.canonical_child_surface_projection(item)["projection_sha256"]
        review["item_review_request_sha256"] = question_bank.v12_item_review_request_sha256(item)
        review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(
            item,
            review,
        )
    artifact = node_entry["node_review_artifact"]
    reviews = artifact["constituent_reviews"]
    item_by_slot = {int(item["slot"]): item for item in node_entry["items"]}
    node_candidate_sha256 = question_bank.v12_node_candidate_sha256(node_entry)
    for review in reviews:
        review["node_candidate_sha256"] = node_candidate_sha256
        output = review["review_output"]
        for entry in output["focal_slot_reviews"]:
            item = item_by_slot[int(entry["slot"])]
            subject = question_bank.v12_item_review_subject_binding(item)
            entry["item_id"] = item["id"]
            entry["candidate_sha256"] = question_bank.v12_external_candidate_sha256(item)
            entry["child_surface_sha256"] = subject["child_surface_sha256"]
            entry["item_review_request_sha256"] = subject["item_review_request_sha256"]
            entry["item_review_semantic_evidence_sha256"] = item["review_artifact"][
                "semantic_evidence_sha256"
            ]
        review["review_output_sha256"] = module._sha256_json(output)
        review["semantic_evidence_sha256"] = question_bank.v12_node_set_constituent_semantic_evidence_sha256(
            node_entry,
            review,
        )
    judgment = _approved_global_judgment(node_entry, source["graph_version"])
    verifier_contract = module._load_global_verifier_contract()
    verifier_prompt = module.GLOBAL_VERIFIER_PROMPT_PATH.read_text(encoding="utf-8")
    finalizer_contract = json.loads(module.GLOBAL_FINALIZER_CONTRACT_PATH.read_text(encoding="utf-8"))
    finalizer_prompt = module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(encoding="utf-8")
    request = module._global_finalizer_request_payloads(node_entry, reviews)
    finalizer_rendered = module._render_prompt(
        finalizer_prompt,
        trusted_context=request["trusted_context"],
        untrusted_payload=request["untrusted_payload"],
    )
    verifier_route = model_router.ModelRoute(
        agent_key=question_bank.QUESTION_REVIEWER_AGENT_KEY,
        task="node_global_verifier",
        provider="recorded_fixture",
        model="v6-fixture",
        model_alias="v6-fixture",
        base_url="",
        api_key="",
        timeout_seconds=1.0,
        model_params={},
    )
    finalizer_route = copy.copy(verifier_route)
    finalizer_route = model_router.ModelRoute(
        **{**finalizer_route.__dict__, "task": "node_global_finalizer"}
    )
    finalizer_result = model_router.StructuredJSONResult(
        value=judgment,
        mode="json_schema",
        raw_response={"fixture": "global_finalizer_v6"},
    )
    verifier_shards = []
    for reviewed_slots in question_bank.v12_expected_global_verifier_shards():
        shard_judgment = {
            **judgment,
            "schema_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_RESPONSE_SCHEMA_VERSION,
            "semantic_evidence_version": question_bank.V12_NODE_SET_GLOBAL_VERIFIER_SHARD_MODEL_EVIDENCE_VERSION,
            "reviewed_slots": reviewed_slots,
            "item_classifications": [
                copy.deepcopy(entry)
                for entry in judgment["item_classifications"]
                if int(entry.get("slot") or 0) in reviewed_slots
            ],
        }
        shard_judgment = module._bind_global_verifier_shard_judgment(
            node_entry,
            shard_judgment,
            graph_version=source["graph_version"],
            reviewed_slots=reviewed_slots,
        )
        lineage = module._global_verifier_shard_expected_lineage(
            node_entry,
            reviews,
            reviewed_slots,
        )
        verifier_shards.append(module._node_set_global_verifier_shard_artifact(
            node_entry=node_entry,
            constituent_reviews=reviews,
            reviewed_slots=reviewed_slots,
            model_judgment=shard_judgment,
            contract=verifier_contract,
            prompt_template=verifier_prompt,
            rendered_prompt=lineage["rendered_prompt"],
            result=model_router.StructuredJSONResult(
                value=shard_judgment,
                mode="json_schema",
                raw_response={"fixture": reviewed_slots},
            ),
            route=verifier_route,
            stage_attempt=1,
        ))
    verifier = module._node_set_global_verifier_artifact(
        node_entry=node_entry,
        constituent_reviews=reviews,
        shard_artifacts=verifier_shards,
        route=verifier_route,
        stage_attempt=1,
    )
    output = question_bank.v12_expand_global_model_judgment(
        node_entry,
        reviews,
        judgment,
        graph_version=source["graph_version"],
    )
    finalizer = module._node_set_global_finalizer_artifact(
        node_entry=node_entry,
        constituent_reviews=reviews,
        output=output,
        contract=finalizer_contract,
        prompt_template=finalizer_prompt,
        rendered_prompt=finalizer_rendered,
        result=finalizer_result,
        route=finalizer_route,
        stage_attempt=1,
        model_judgment=judgment,
        source_model_judgment=judgment,
    )
    aggregate = module._aggregate_node_set_review_outputs(
        node_entry=node_entry,
        shard_reviews=reviews,
        global_verifier_artifact=verifier,
        global_finalizer_artifact=finalizer,
        node_review_concurrency=1,
        stage_attempt=1,
    )
    node_entry["node_review_artifact"] = aggregate["node_review_artifact"]
    return node_entry


def _v6_checkpoint_bytes(module, source_path: Path) -> bytes:
    source = json.loads(_pinned_source_bytes(source_path))
    node_entry = _upgrade_node_to_v6(module, source)
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint_dir = Path(tmp)
        module._write_checkpoint(
            checkpoint_dir,
            node_id=source["node_id"],
            graph_version=source["graph_version"],
            rounds_used=int(source.get("rounds_used") or 0),
            rejected_rounds=int(source.get("rejected_rounds") or 0),
            report={"issues": []},
            node_entry=node_entry,
            status="completed",
            slot_rounds={
                slot: int((source.get("slot_rounds") or {}).get(str(slot), 0) or 0)
                for slot in range(1, 21)
            },
            pending_repair_by_slot={},
            stage_counters=module._stage_counters_from_checkpoint(source, slot_rounds={
                slot: int((source.get("slot_rounds") or {}).get(str(slot), 0) or 0)
                for slot in range(1, 21)
            }),
            repair_chain_events=module._repair_chain_events_from_checkpoint(source),
            checkpoint_migrations=source.get("checkpoint_migrations"),
        )
        return (checkpoint_dir / f"{source['node_id']}.json").read_bytes()


def _number_line_checkpoint_bytes(module) -> bytes:
    raw = _v6_checkpoint_bytes(module, NUMBER_LINE_SOURCE)
    checkpoint = json.loads(raw)
    accepted = checkpoint.get("accepted_slots") or {}
    if set(accepted) != {str(slot) for slot in range(1, 21)}:
        raise AssertionError("NUMBER-LINE checkpoint must expose an exact 20-slot force fixture")
    return raw


def _items_by_slot(checkpoint: dict) -> dict[int, dict]:
    return {
        int(item["slot"]): copy.deepcopy(item)
        for item in checkpoint["node"]["items"]
    }


def _build_node_from_checkpoint(
    module,
    *,
    checkpoint_dir: Path,
    graph: dict,
    force_slot_modes: dict[int, str],
    checkpoint_node_id: str = "M-G7-NUMBER-LINE",
    operation_token: str = FORCE_OPERATION_TOKEN,
    max_rounds: int = 3,
):
    checkpoint = json.loads((checkpoint_dir / f"{checkpoint_node_id}.json").read_text(encoding="utf-8"))
    node = next(item for item in graph["nodes"] if item["id"] == checkpoint["node_id"])
    return module._build_live_node(
        node=node,
        graph=graph,
        graph_version=checkpoint["graph_version"],
        checkpoint_dir=checkpoint_dir,
        max_rounds=max_rounds,
        chunk_concurrency=1,
        node_review_concurrency=1,
        resume=True,
        designer_contract=json.loads(module.DESIGNER_CONTRACT_PATH.read_text(encoding="utf-8")),
        reviewer_contract=json.loads(module.REVIEWER_CONTRACT_PATH.read_text(encoding="utf-8")),
        node_set_reviewer_contract=json.loads(
            module.NODE_SET_REVIEWER_CONTRACT_PATH.read_text(encoding="utf-8")
        ),
        global_finalizer_contract=json.loads(
            module.GLOBAL_FINALIZER_CONTRACT_PATH.read_text(encoding="utf-8")
        ),
        designer_prompt_template=module.DESIGNER_PROMPT_PATH.read_text(encoding="utf-8"),
        reviewer_prompt_template=module.REVIEWER_PROMPT_PATH.read_text(encoding="utf-8"),
        node_set_reviewer_prompt_template=module.NODE_SET_REVIEWER_PROMPT_PATH.read_text(
            encoding="utf-8"
        ),
        global_finalizer_prompt_template=module.GLOBAL_FINALIZER_PROMPT_PATH.read_text(
            encoding="utf-8"
        ),
        accepted_core_summaries=[],
        force_slots=set(force_slot_modes),
        force_slot_modes=force_slot_modes,
        force_slot_operation_tokens={
            slot: operation_token
            for slot in force_slot_modes
        },
    )


def _state_only_replacement(item: dict) -> dict:
    replacement = copy.deepcopy(item)
    replacement["elicitation_mode"] = "standard"
    designer = replacement["designer_artifact"]
    designer["designer_run_id"] = f"{designer['designer_run_id']}-state-fixture"
    designer["pipeline_stage"] = "local_item_repair"
    designer["stage_attempt"] = 1
    designer["operator_elicitation_mode_override"] = {
        "from": item.get("elicitation_mode"),
        "to": "standard",
        "reason": "explicit_operator_force_slot_mode",
    }
    review = replacement["review_artifact"]
    review["pipeline_stage"] = "local_item_repair"
    review["stage_attempt"] = 1
    review["candidate_sha256"] = question_bank.v12_external_candidate_sha256(replacement)
    review["semantic_evidence_sha256"] = question_bank.v12_item_review_semantic_evidence_sha256(
        replacement,
        review,
    )
    return replacement


def _write_completed_force_operation_checkpoint(module, checkpoint_dir: Path) -> tuple[dict, dict]:
    source = json.loads(_number_line_checkpoint_bytes(module))
    accepted = _items_by_slot(source)
    completed_candidate = copy.deepcopy(accepted[20])
    pending = module._pending_repair_from_checkpoint(source)
    slot_rounds = {
        slot: int((source.get("slot_rounds") or {}).get(str(slot), 0) or 0)
        for slot in range(1, 21)
    }
    original_slot_round = slot_rounds[20]
    counters = module._stage_counters_from_checkpoint(source, slot_rounds=slot_rounds)
    original_node_review_round = counters["node_set_review_round"]
    events = module._repair_chain_events_from_checkpoint(source)
    events = module._apply_forced_slot_regeneration(
        node=next(item for item in _graph()["nodes"] if item["id"] == source["node_id"]),
        graph_version=source["graph_version"],
        force_slots={20},
        force_slot_modes={20: "standard"},
        force_slot_operation_tokens={20: FORCE_OPERATION_TOKEN},
        accepted_by_slot=accepted,
        pending_repair_by_slot=pending,
        slot_rounds=slot_rounds,
        stage_counters=counters,
        repair_chain_events=events,
    )
    receipt = copy.deepcopy(events[-1]["operator_operation_receipt"])
    accepted[20] = completed_candidate
    pending.pop(20, None)
    slot_rounds[20] = original_slot_round
    counters["node_set_review_round"] = original_node_review_round
    counters["local_item_rounds_by_slot"]["20"] = original_slot_round
    events = module._append_repair_chain_event(
        events,
        node_id=source["node_id"],
        graph_version=source["graph_version"],
        stage="local_item_repair",
        stage_attempt=1,
        slot=20,
        reason="operator_force_slot_regeneration_completed",
        instruction={"operator_operation_receipt": receipt},
        old_candidate=None,
        new_candidate=completed_candidate,
        source_review_artifact=completed_candidate["review_artifact"],
    )
    module._write_checkpoint(
        checkpoint_dir,
        node_id=source["node_id"],
        graph_version=source["graph_version"],
        rounds_used=int(source.get("rounds_used") or 0),
        rejected_rounds=int(source.get("rejected_rounds") or 0),
        report={"issues": []},
        node_entry=copy.deepcopy(source["node"]),
        status="completed",
        slot_rounds=slot_rounds,
        pending_repair_by_slot=pending,
        stage_counters=counters,
        repair_chain_events=events,
        checkpoint_migrations=source.get("checkpoint_migrations"),
    )
    completed = json.loads(
        (checkpoint_dir / "M-G7-NUMBER-LINE.json").read_text(encoding="utf-8")
    )
    return completed, receipt


def _write_terminal_failed_process_operation_checkpoint(
    module,
    checkpoint_dir: Path,
) -> tuple[dict, dict]:
    source = json.loads(_v6_checkpoint_bytes(module, PROCESS_SOURCE))
    accepted = _items_by_slot(source)
    pending: dict[int, list[dict]] = {}
    slot_rounds = {
        slot: int((source.get("slot_rounds") or {}).get(str(slot), 0) or 0)
        for slot in range(1, 21)
    }
    counters = module._stage_counters_from_checkpoint(None, slot_rounds=slot_rounds)
    events = module._apply_forced_slot_regeneration(
        node=next(item for item in _graph()["nodes"] if item["id"] == source["node_id"]),
        graph_version=source["graph_version"],
        force_slots={20},
        force_slot_modes={20: "unprompted_process_evidence"},
        force_slot_operation_tokens={20: TERMINAL_PROCESS_OPERATION_TOKEN},
        accepted_by_slot=accepted,
        pending_repair_by_slot=pending,
        slot_rounds=slot_rounds,
        stage_counters=counters,
        repair_chain_events=[],
        max_semantic_rounds=3,
    )
    receipt = copy.deepcopy(events[-1]["operator_operation_receipt"])
    for attempt in range(1, 4):
        failure_instruction = {
            "slot": 20,
            "slots": [20],
            "item_id": "QB12-M-BRIDGE-SOLUTION-HABIT-20",
            "reason": "reviewer_evidence_gate_failed",
            "verdict": "rejected",
            "scores": {"node_alignment": 4.0},
            "confidence": 0.91,
            "semantic_evidence_errors": [],
            "reviewer_evidence_errors": [{
                "flag": "process_evidence_required",
                "code": "required_flag_must_be_true",
                "attempt": attempt,
            }],
            "repair_instructions": [
                "Regenerate the slot and obtain complete independent reviewer evidence."
            ],
            "candidate_sha256": module._sha256_text(f"candidate-{attempt}"),
            "review_artifact_sha256": module._sha256_text(f"review-{attempt}"),
            "operator_operation_receipt": copy.deepcopy(receipt),
        }
        pending.setdefault(20, []).append(copy.deepcopy(failure_instruction))
        events = module._append_repair_chain_event(
            events,
            node_id=source["node_id"],
            graph_version=source["graph_version"],
            stage="evidence_contract_repair",
            stage_attempt=attempt,
            slot=20,
            reason="reviewer_evidence_gate_failed",
            instruction=failure_instruction,
            old_candidate=None,
            new_candidate=None,
            source_review_artifact=None,
        )
    counters.setdefault("evidence_contract_repair_rounds_by_slot", {})["20"] = 3
    module._write_checkpoint(
        checkpoint_dir,
        node_id=source["node_id"],
        graph_version=source["graph_version"],
        rounds_used=max(slot_rounds.values() or [0]),
        rejected_rounds=int(source.get("rejected_rounds") or 0) + 3,
        report={"issues": []},
        node_entry=module._node_entry_from_accepted(
            node=next(item for item in _graph()["nodes"] if item["id"] == source["node_id"]),
            accepted_by_slot=accepted,
        ),
        status="incomplete",
        slot_rounds=slot_rounds,
        pending_repair_by_slot=pending,
        stage_counters=counters,
        repair_chain_events=events,
        checkpoint_migrations=[],
    )
    checkpoint = json.loads(
        (checkpoint_dir / "M-BRIDGE-SOLUTION-HABIT.json").read_text(encoding="utf-8")
    )
    return checkpoint, receipt


def _terminal_supersession_events(module) -> tuple[dict, list[dict]]:
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint, _receipt = _write_terminal_failed_process_operation_checkpoint(
            module,
            Path(tmp),
        )
    accepted = _items_by_slot(checkpoint)
    pending = module._pending_repair_from_checkpoint(checkpoint)
    slot_rounds = {
        slot: int((checkpoint.get("slot_rounds") or {}).get(str(slot), 0) or 0)
        for slot in range(1, 21)
    }
    counters = module._stage_counters_from_checkpoint(checkpoint, slot_rounds=slot_rounds)
    events = module._apply_forced_slot_regeneration(
        node=next(
            node for node in _graph()["nodes"] if node["id"] == checkpoint["node_id"]
        ),
        graph_version=checkpoint["graph_version"],
        force_slots={20},
        force_slot_modes={20: "unprompted_process_evidence"},
        force_slot_operation_tokens={20: NEXT_FORCE_OPERATION_TOKEN},
        accepted_by_slot=accepted,
        pending_repair_by_slot=pending,
        slot_rounds=slot_rounds,
        stage_counters=counters,
        repair_chain_events=module._repair_chain_events_from_checkpoint(checkpoint),
        max_semantic_rounds=3,
    )
    return checkpoint, events


def _reseal_operation_receipt(module, receipt: dict) -> None:
    receipt["operation_id"] = module._sha256_json(
        module._operator_operation_receipt_identity_payload(receipt)
    )
    receipt["receipt_integrity_sha256"] = (
        module._operator_operation_receipt_integrity_sha256(receipt)
    )


def _reseal_repair_chain(module, events: list[dict]) -> None:
    previous = ""
    for index, event in enumerate(events, start=1):
        event["event_index"] = index
        event["previous_event_sha256"] = previous
        payload = {key: value for key, value in event.items() if key != "event_sha256"}
        event["event_sha256"] = module._sha256_json(payload)
        previous = event["event_sha256"]


class QuestionBankV12ForceSlotModeTests(unittest.TestCase):
    def test_normal_reviewer_evidence_repair_does_not_require_operator_terminal_evidence(self):
        module = _load_builder()
        events = module._append_reviewer_evidence_failure_events(
            [],
            node_id="M-G7-EQ-DENOM",
            graph_version="2026-07-04.v2+sha256:test",
            chunk_result={
                "round_number": 4,
                "requested_slots": [1],
                "accepted_by_slot": {},
                "rejected_slots": [1],
                "repair_instructions": [{
                    "slot": 1,
                    "slots": [1],
                    "reason": "reviewer_evidence_gate_failed",
                    "reviewer_evidence_errors": [{
                        "flag": "process_evidence_required",
                        "code": "required_flag_must_be_true",
                        "actual": False,
                    }],
                    "repair_instructions": [
                        "Regenerate with a complete independent reviewer evidence contract."
                    ],
                }],
            },
        )

        self.assertEqual([], events)

    def test_crash_after_completed_force_checkpoint_resumes_without_replaying_operation(self):
        module = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            completed, receipt = _write_completed_force_operation_checkpoint(module, checkpoint_dir)
            before_candidate = copy.deepcopy(_items_by_slot(completed)[20])
            before_candidate_sha256 = question_bank.v12_external_candidate_sha256(before_candidate)
            before_events = copy.deepcopy(completed["repair_chain_events"])
            self.assertEqual(
                receipt["operation_id"],
                before_events[-1]["operator_operation_receipt"]["operation_id"],
            )
            self.assertEqual(
                "operator_force_slot_regeneration_completed",
                before_events[-1]["reason"],
            )
            self.assertEqual(before_candidate_sha256, before_events[-1]["new_candidate_sha256"])

            with mock.patch.object(
                module,
                "_process_live_slot_chunk",
                side_effect=AssertionError("completed operation called designer/reviewer chunk"),
            ) as slot_call, mock.patch.object(
                module,
                "_call_v12_batch_agent",
                side_effect=AssertionError("completed operation called semantic agent"),
            ) as semantic_call:
                result = _build_node_from_checkpoint(
                    module,
                    checkpoint_dir=checkpoint_dir,
                    graph=_graph(),
                    force_slot_modes={20: "standard"},
                )

            slot_call.assert_not_called()
            semantic_call.assert_not_called()
            persisted = json.loads(
                (checkpoint_dir / "M-G7-NUMBER-LINE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(20, len(result["items"]))
            self.assertEqual(before_candidate, _items_by_slot(persisted)[20])
            self.assertEqual(before_events, persisted["repair_chain_events"])
            self.assertEqual("completed", persisted["status"])
            self.assertEqual("current", module._validate_live_checkpoint_integrity(persisted))

    def test_new_operation_token_supersedes_historical_completed_receipt(self):
        module = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            completed, old_receipt = _write_completed_force_operation_checkpoint(
                module,
                checkpoint_dir,
            )
            accepted = _items_by_slot(completed)
            pending = {
                20: [{
                    "slot": 20,
                    "slots": [20],
                    "reason": "historical_completed_operator_operation",
                    "operator_operation_receipt": copy.deepcopy(old_receipt),
                    "repair_instructions": ["Preserve the historical operation receipt."],
                }]
            }
            slot_rounds = {
                slot: int((completed.get("slot_rounds") or {}).get(str(slot), 0) or 0)
                for slot in range(1, 21)
            }
            counters = module._stage_counters_from_checkpoint(
                completed,
                slot_rounds=slot_rounds,
            )
            events = copy.deepcopy(completed["repair_chain_events"])

            updated = module._apply_forced_slot_regeneration(
                node=next(
                    node
                    for node in _graph()["nodes"]
                    if node["id"] == completed["node_id"]
                ),
                graph_version=completed["graph_version"],
                force_slots={20},
                force_slot_modes={20: "standard"},
                force_slot_operation_tokens={20: NEXT_FORCE_OPERATION_TOKEN},
                accepted_by_slot=accepted,
                pending_repair_by_slot=pending,
                slot_rounds=slot_rounds,
                stage_counters=counters,
                repair_chain_events=events,
            )

            self.assertEqual(events, updated[:-1])
            self.assertNotIn(20, accepted)
            self.assertEqual(1, len(pending[20]))
            current_receipt = pending[20][0]["operator_operation_receipt"]
            self.assertNotEqual(old_receipt["operation_id"], current_receipt["operation_id"])
            self.assertEqual(
                module._sha256_text(NEXT_FORCE_OPERATION_TOKEN),
                current_receipt["operation_token_sha256"],
            )
            self.assertEqual(
                current_receipt["operation_id"],
                updated[-1]["operator_operation_receipt"]["operation_id"],
            )
            module._validate_repair_chain_events(updated)

    def test_same_operation_token_conflicting_receipts_still_fail_closed(self):
        module = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            _completed, receipt = _write_completed_force_operation_checkpoint(
                module,
                Path(tmp),
            )
            conflicting = copy.deepcopy(receipt)
            conflicting["source_candidate_sha256"] = "a" * 64
            conflicting["operation_id"] = module._sha256_json({
                key: value
                for key, value in conflicting.items()
                if key != "operation_id"
            })

            with self.assertRaisesRegex(
                model_router.ModelCallError,
                r"conflicting operator slot operation receipts",
            ):
                module._operator_operation_receipts_by_slot([
                    {"operator_operation_receipt": receipt},
                    {"operator_operation_receipt": conflicting},
                ])

    def test_new_token_supersedes_real_terminal_failed_operation_before_model_boundary(self):
        module = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            path = checkpoint_dir / "M-BRIDGE-SOLUTION-HABIT.json"
            source, old_receipt = _write_terminal_failed_process_operation_checkpoint(
                module,
                checkpoint_dir,
            )
            original_events = copy.deepcopy(source["repair_chain_events"])
            self.assertNotIn("20", source["accepted_slots"])
            self.assertEqual(
                3,
                source["stage_counters"]["evidence_contract_repair_rounds_by_slot"]["20"],
            )
            self.assertEqual(
                3,
                sum(
                    instruction.get("reason") == "reviewer_evidence_gate_failed"
                    for instruction in source["pending_repair_by_slot"]["20"]
                ),
            )
            accepted = _items_by_slot(source)
            pending = module._pending_repair_from_checkpoint(source)
            slot_rounds = {
                slot: int((source.get("slot_rounds") or {}).get(str(slot), 0) or 0)
                for slot in range(1, 21)
            }
            counters = module._stage_counters_from_checkpoint(source, slot_rounds=slot_rounds)
            events = module._apply_forced_slot_regeneration(
                node=next(
                    node for node in _graph()["nodes"] if node["id"] == source["node_id"]
                ),
                graph_version=source["graph_version"],
                force_slots={20},
                force_slot_modes={20: "unprompted_process_evidence"},
                force_slot_operation_tokens={20: NEXT_FORCE_OPERATION_TOKEN},
                accepted_by_slot=accepted,
                pending_repair_by_slot=pending,
                slot_rounds=slot_rounds,
                stage_counters=counters,
                repair_chain_events=module._repair_chain_events_from_checkpoint(source),
                max_semantic_rounds=3,
            )
            module._write_checkpoint(
                checkpoint_dir,
                node_id=source["node_id"],
                graph_version=source["graph_version"],
                rounds_used=max(slot_rounds.values() or [0]),
                rejected_rounds=int(source.get("rejected_rounds") or 0),
                report={"issues": []},
                node_entry=module._node_entry_from_accepted(
                    node=next(
                        node for node in _graph()["nodes"] if node["id"] == source["node_id"]
                    ),
                    accepted_by_slot=accepted,
                ),
                status="incomplete",
                slot_rounds=slot_rounds,
                pending_repair_by_slot=pending,
                stage_counters=counters,
                repair_chain_events=events,
                checkpoint_migrations=[],
            )

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(original_events, persisted["repair_chain_events"][:-2])
            terminal_event, current_event = persisted["repair_chain_events"][-2:]
            self.assertEqual(
                "operator_force_slot_regeneration_terminal_failed_superseded",
                terminal_event["reason"],
            )
            supersession = terminal_event["operator_operation_supersession"]
            terminal_receipt = terminal_event["operator_terminal_failure_receipt"]
            self.assertEqual(
                {
                    "schema_version",
                    "operation_id",
                    "node_id",
                    "graph_version",
                    "slot",
                    "accepted_candidate_absent",
                    "stage_counter_key",
                    "stage_counter_value",
                    "max_semantic_rounds",
                    "reviewer_evidence_failure_event_sha256s",
                    "reviewer_evidence_failure_event_digest_aggregate_sha256",
                    "failure_count",
                    "failure_class",
                    "receipt_digest_sha256",
                },
                set(terminal_receipt),
            )
            self.assertEqual(old_receipt["operation_id"], supersession["superseded_operation_id"])
            self.assertEqual("2026-07-15.operator-slot-supersession.v2", supersession["schema_version"])
            self.assertEqual(
                terminal_receipt["receipt_digest_sha256"],
                supersession["terminal_failure_receipt_sha256"],
            )
            self.assertEqual(3, terminal_receipt["stage_counter_value"])
            self.assertEqual(3, terminal_receipt["max_semantic_rounds"])
            self.assertEqual(3, terminal_receipt["failure_count"])
            prior_failures = [
                event
                for event in original_events
                if event.get("reason") == "reviewer_evidence_gate_failed"
            ]
            self.assertEqual(3, len(prior_failures))
            self.assertEqual(
                [event["event_sha256"] for event in prior_failures],
                terminal_receipt["reviewer_evidence_failure_event_sha256s"],
            )
            self.assertTrue(terminal_receipt["accepted_candidate_absent"])
            self.assertEqual(source["node_id"], terminal_event["node_id"])
            self.assertEqual(source["graph_version"], terminal_event["graph_version"])
            self.assertEqual(
                supersession["superseding_operation_id"],
                current_event["operator_operation_receipt"]["operation_id"],
            )
            current_pending_receipt = persisted["pending_repair_by_slot"]["20"][0][
                "operator_operation_receipt"
            ]
            self.assertEqual(
                module._sha256_text(NEXT_FORCE_OPERATION_TOKEN),
                current_pending_receipt["operation_token_sha256"],
            )
            self.assertEqual(
                0,
                persisted["stage_counters"]["evidence_contract_repair_rounds_by_slot"]["20"],
            )
            self.assertEqual("current", module._validate_live_checkpoint_integrity(persisted))

    def test_supersession_rejects_resealed_cross_node_graph_and_slot_receipts(self):
        module = _load_builder()
        _checkpoint, valid_events = _terminal_supersession_events(module)
        terminal_index = len(valid_events) - 2
        current_index = len(valid_events) - 1
        attacks = {
            "cross_node": {"node_id": "M-G7-NUMBER-LINE", "process_node_policy_protected": False},
            "cross_graph": {"graph_version": "2026-07-15.cross-graph-adversary"},
            "cross_slot": {"slot": 18, "process_node_policy_protected": False},
        }
        for name, mutation in attacks.items():
            with self.subTest(name=name):
                tampered = copy.deepcopy(valid_events)
                terminal_event = tampered[terminal_index]
                current_event = tampered[current_index]
                current_receipt = current_event["operator_operation_receipt"]
                current_receipt.update(mutation)
                _reseal_operation_receipt(module, current_receipt)
                current_event.update({
                    key: value
                    for key, value in mutation.items()
                    if key in {"node_id", "graph_version", "slot"}
                })
                terminal_event["operator_operation_supersession"]["superseding_operation_id"] = (
                    current_receipt["operation_id"]
                )
                _reseal_repair_chain(module, tampered)
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    r"supersession.*identity|lineage|context",
                ):
                    module._validate_repair_chain_events(tampered)

    def test_terminal_failure_receipt_rejects_resealed_event_with_tampered_source_evidence(self):
        module = _load_builder()
        _checkpoint, valid_events = _terminal_supersession_events(module)
        for field, value in (
            ("stage_counter_value", 2),
            ("failure_count", 2),
            ("receipt_digest_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                tampered = copy.deepcopy(valid_events)
                terminal_event = tampered[-2]
                terminal_event["operator_terminal_failure_receipt"][field] = value
                _reseal_repair_chain(module, tampered)
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    r"terminal failure receipt|supersession",
                ):
                    module._validate_repair_chain_events(tampered)

    def test_terminal_supersession_rejects_complete_reseal_of_prior_failure_digest(self):
        module = _load_builder()
        _checkpoint, valid_events = _terminal_supersession_events(module)
        tampered = copy.deepcopy(valid_events)
        failure_event = next(
            event
            for event in tampered
            if event.get("reason") == "reviewer_evidence_gate_failed"
        )
        self.assertIn("reviewer_evidence_failure", failure_event)
        failure_event["reviewer_evidence_failure"]["failure_payload_sha256"] = "a" * 64
        failure_event["instruction_sha256"] = "a" * 64
        _reseal_repair_chain(module, tampered)

        terminal_event = next(
            event
            for event in tampered
            if event.get("reason") == "operator_force_slot_regeneration_terminal_failed_superseded"
        )
        prior_failure_hashes = [
            event["event_sha256"]
            for event in tampered[: tampered.index(terminal_event)]
            if event.get("reason") == "reviewer_evidence_gate_failed"
        ]
        terminal_receipt = terminal_event["operator_terminal_failure_receipt"]
        terminal_receipt["reviewer_evidence_failure_event_sha256s"] = prior_failure_hashes
        terminal_receipt["reviewer_evidence_failure_event_digest_aggregate_sha256"] = (
            module._sha256_json(prior_failure_hashes)
        )
        terminal_receipt["receipt_digest_sha256"] = module._sha256_json({
            key: value
            for key, value in terminal_receipt.items()
            if key != "receipt_digest_sha256"
        })
        terminal_event["operator_operation_supersession"]["terminal_failure_receipt_sha256"] = (
            terminal_receipt["receipt_digest_sha256"]
        )
        _reseal_repair_chain(module, tampered)

        with self.assertRaisesRegex(
            model_router.ModelCallError,
            r"reviewer evidence failure|terminal failure receipt",
        ):
            module._validate_repair_chain_events(tampered)

    def test_legacy_v1_supersession_checkpoint_is_not_activation_grade(self):
        module = _load_builder()
        legacy = json.loads(_pinned_source_bytes(PROCESS_LEGACY_SUPERSESSION_BACKUP))
        self.assertEqual("completed", legacy["status"])
        with self.assertRaisesRegex(
            model_router.ModelCallError,
            r"operator slot operation receipt schema is invalid|legacy operator slot supersession.*quarantine",
        ):
            module._validate_live_checkpoint_integrity(legacy)

    def test_new_token_cannot_supersede_active_pending_operation(self):
        module = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint, _receipt = _write_terminal_failed_process_operation_checkpoint(
                module,
                Path(tmp),
            )
            accepted = _items_by_slot(checkpoint)
            pending = module._pending_repair_from_checkpoint(checkpoint)
            slot_rounds = {
                slot: int((checkpoint.get("slot_rounds") or {}).get(str(slot), 0) or 0)
                for slot in range(1, 21)
            }
            counters = module._stage_counters_from_checkpoint(checkpoint, slot_rounds=slot_rounds)
            counters["evidence_contract_repair_rounds_by_slot"]["20"] = 2

            with self.assertRaisesRegex(
                model_router.ModelCallError,
                r"conflicting operator slot operation receipts",
            ):
                module._apply_forced_slot_regeneration(
                    node=next(
                        node
                        for node in _graph()["nodes"]
                        if node["id"] == checkpoint["node_id"]
                    ),
                    graph_version=checkpoint["graph_version"],
                    force_slots={20},
                    force_slot_modes={20: "unprompted_process_evidence"},
                    force_slot_operation_tokens={20: NEXT_FORCE_OPERATION_TOKEN},
                    accepted_by_slot=accepted,
                    pending_repair_by_slot=pending,
                    slot_rounds=slot_rounds,
                    stage_counters=counters,
                    repair_chain_events=module._repair_chain_events_from_checkpoint(checkpoint),
                    max_semantic_rounds=3,
                )

    def test_operator_operation_receipt_fields_and_tampering_are_rejected(self):
        module = _load_builder()
        checkpoint = json.loads(_number_line_checkpoint_bytes(module))
        item = _items_by_slot(checkpoint)[20]
        accepted = {20: copy.deepcopy(item)}
        pending: dict[int, list[dict]] = {}
        slot_rounds = {20: 1}
        counters = module._stage_counters_from_checkpoint(None, slot_rounds=slot_rounds)
        events = module._apply_forced_slot_regeneration(
            node=next(
                node for node in _graph()["nodes"] if node["id"] == checkpoint["node_id"]
            ),
            graph_version=checkpoint["graph_version"],
            force_slots={20},
            force_slot_modes={20: "standard"},
            force_slot_operation_tokens={20: FORCE_OPERATION_TOKEN},
            accepted_by_slot=accepted,
            pending_repair_by_slot=pending,
            slot_rounds=slot_rounds,
            stage_counters=counters,
            repair_chain_events=[],
        )
        receipt = events[0]["operator_operation_receipt"]
        self.assertEqual(
            {
                "schema_version",
                "operation_id",
                "receipt_integrity_sha256",
                "node_id",
                "graph_version",
                "slot",
                "source_candidate_sha256",
                "source_candidate_state",
                "source_review_artifact_sha256",
                "source_pending_repair_sha256",
                "source_pending_repair_count",
                "source_pending_reasons",
                "source_pending_reasons_sha256",
                "source_mode",
                "target_mode",
                "mode_override_applied",
                "process_node_policy_protected",
                "operation_token_sha256",
                "operation_generation",
            },
            set(receipt),
        )
        self.assertEqual(module.V12_OPERATOR_SLOT_OPERATION_VERSION, receipt["schema_version"])
        self.assertEqual("standard", receipt["source_mode"])
        self.assertEqual("standard", receipt["target_mode"])
        self.assertEqual("accepted", receipt["source_candidate_state"])
        self.assertEqual(
            module._sha256_json(item["review_artifact"]),
            receipt["source_review_artifact_sha256"],
        )
        self.assertEqual(module._sha256_json([]), receipt["source_pending_repair_sha256"])
        self.assertEqual(0, receipt["source_pending_repair_count"])
        self.assertEqual([], receipt["source_pending_reasons"])
        self.assertEqual(module._sha256_json([]), receipt["source_pending_reasons_sha256"])
        self.assertFalse(receipt["mode_override_applied"])
        self.assertFalse(receipt["process_node_policy_protected"])
        self.assertEqual(1, receipt["operation_generation"])
        self.assertEqual(64, len(receipt["operation_id"]))
        self.assertEqual(
            module._operator_operation_receipt_integrity_sha256(receipt),
            receipt["receipt_integrity_sha256"],
        )
        self.assertEqual(module._sha256_text(FORCE_OPERATION_TOKEN), receipt["operation_token_sha256"])
        module._validate_repair_chain_events(events)

        tampered_values = {
            "schema_version": "tampered-version",
            "operation_id": "0" * 64,
            "receipt_integrity_sha256": "0" * 64,
            "node_id": "",
            "graph_version": "",
            "slot": 0,
            "source_candidate_sha256": "0" * 64,
            "source_candidate_state": "tampered",
            "source_review_artifact_sha256": "0" * 64,
            "source_pending_repair_sha256": "0" * 64,
            "source_pending_repair_count": -1,
            "source_pending_reasons": ["tampered"],
            "source_pending_reasons_sha256": "0" * 64,
            "source_mode": "",
            "target_mode": "tampered",
            "mode_override_applied": True,
            "process_node_policy_protected": True,
            "operation_token_sha256": "0" * 64,
            "operation_generation": 0,
        }
        for field, value in tampered_values.items():
            with self.subTest(field=field):
                tampered = copy.deepcopy(events)
                tampered[0]["operator_operation_receipt"][field] = value
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    r"repair chain integrity failed|operator slot operation receipt",
                ):
                    module._validate_repair_chain_events(tampered)

        resealed = copy.deepcopy(events)
        resealed[0]["operator_operation_receipt"]["target_mode"] = (
            "unprompted_process_evidence"
        )
        payload = {key: value for key, value in resealed[0].items() if key != "event_sha256"}
        resealed[0]["event_sha256"] = module._sha256_json(payload)
        with self.assertRaisesRegex(
            model_router.ModelCallError,
            r"receipt id is invalid|mode transition is invalid",
        ):
            module._validate_repair_chain_events(resealed)

    def test_completed_number_line_slot20_is_a_standard_concept_probe_with_exact_live_lineage(self):
        module = _load_builder()
        checkpoint = json.loads(_number_line_checkpoint_bytes(module))
        graph = _graph()
        node = next(item for item in graph["nodes"] if item["id"] == checkpoint["node_id"])
        item = _items_by_slot(checkpoint)[20]
        review = item["review_artifact"]
        evidence = review["semantic_evidence"]

        self.assertEqual("completed", checkpoint["status"])
        self.assertFalse(question_bank.v12_is_process_node(node))
        self.assertEqual("summary_transfer_check", item["slot_role"])
        self.assertEqual("standard", item["elicitation_mode"])
        self.assertEqual("short_text", item["interaction_schema"]["type"])
        self.assertEqual([], item["interaction_schema"]["choices"])
        self.assertIn("0到1之间被平均分成4小格", item["prompt"])
        self.assertIn("X在0左边第5小格", item["prompt"])
        self.assertIn("Y在1右边第2小格", item["prompt"])
        for expected in ("-5/4", "-1.25", "3/2", "1.5"):
            self.assertIn(expected, item["expected_answer"])
        self.assertEqual([], question_bank.v12_item_policy_errors(node, item))
        self.assertEqual("approved", review["verdict"])
        self.assertGreaterEqual(review["confidence"], question_bank.V12_REVIEW_MIN_CONFIDENCE)
        self.assertEqual(question_bank.QUESTION_REVIEWER_AGENT_KEY, review["agent_key"])
        self.assertEqual("question_review", review["phase"])
        self.assertEqual("live_model", review["provider_mode"])
        self.assertEqual(
            question_bank.v12_external_candidate_sha256(item),
            review["candidate_sha256"],
        )
        self.assertEqual(
            question_bank.v12_item_review_semantic_evidence_sha256(item, review),
            review["semantic_evidence_sha256"],
        )
        subject = question_bank.v12_item_review_subject_binding(item)
        self.assertEqual(subject["child_surface_sha256"], review["child_surface_sha256"])
        self.assertEqual(subject["item_review_request_sha256"], review["item_review_request_sha256"])
        self.assertEqual("not_applicable", evidence["unprompted_process_evidence"]["applicability"])
        self.assertFalse(evidence["process_target_disclosed"])
        node_review = checkpoint["node"]["node_review_artifact"]
        verifier = node_review["global_verifier"]
        finalizer = node_review["global_finalizer"]
        self.assertEqual("node_global_verifier", verifier["phase"])
        self.assertEqual(
            question_bank.V12_NODE_SET_GLOBAL_VERIFIER_CONTRACT_VERSION,
            verifier["contract_version"],
        )
        self.assertEqual(
            question_bank.V12_NODE_SET_GLOBAL_VERIFIER_REQUEST_LINEAGE_VERSION,
            verifier["request_lineage_version"],
        )
        self.assertEqual("node_global_finalizer", finalizer["phase"])
        self.assertEqual(
            question_bank.V12_GLOBAL_FINALIZER_CONTRACT_VERSION,
            finalizer["contract_version"],
        )
        self.assertEqual(
            question_bank.V12_NODE_SET_GLOBAL_FINALIZER_REQUEST_LINEAGE_VERSION,
            finalizer["request_lineage_version"],
        )
        self.assertEqual(
            question_bank.V12_SEMANTIC_EVIDENCE_COMMITMENT_VERSION,
            checkpoint["semantic_evidence_commitment"]["version"],
        )
        self.assertEqual(
            question_bank.V12_COMPLETED_NODE_RECEIPT_SCHEMA_VERSION,
            checkpoint["completed_node_receipt"]["schema_version"],
        )
        self.assertEqual("current", module._validate_live_checkpoint_integrity(checkpoint))

    def test_process_node_standard_downgrade_fails_before_model_and_checkpoint_mutation(self):
        module = _load_builder()
        graph = _graph()
        process_node = next(
            item for item in graph["nodes"] if item["id"] == "M-BRIDGE-SOLUTION-HABIT"
        )
        self.assertTrue(question_bank.v12_is_process_node(process_node))
        self.assertIn(20, question_bank.V12_PROCESS_UNPROMPTED_SLOTS)
        original = _v6_checkpoint_bytes(module, PROCESS_SOURCE)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint_dir = root / "checkpoints"
            checkpoint_dir.mkdir()
            copied = checkpoint_dir / "M-BRIDGE-SOLUTION-HABIT.json"
            copied.write_bytes(original)
            output_path = root / "out.json"
            inventory_before = sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
            with mock.patch.object(
                module,
                "_call_v12_batch_agent",
                side_effect=AssertionError("process downgrade reached a model call"),
            ) as model_call:
                with self.assertRaisesRegex(
                    ValueError,
                    r"cannot weaken process-node evidence policy",
                ):
                    module.build_live(
                        output_path=output_path,
                        checkpoint_dir=checkpoint_dir,
                        project_root=PROJECT_ROOT,
                        node_ids=[process_node["id"]],
                        max_rounds=3,
                        max_concurrency=1,
                        node_review_concurrency=1,
                        resume=True,
                        force_nodes=None,
                        force_slots=None,
                        force_slot_modes={process_node["id"]: {20: "standard"}},
                        force_slot_operation_tokens={
                            process_node["id"]: {20: "invalid-process-downgrade-v6"}
                        },
                        force_node_reviews=None,
                        max_semantic_calls=16,
                        max_provider_attempts=48,
                    )
            model_call.assert_not_called()
            self.assertEqual(original, copied.read_bytes())
            self.assertFalse(output_path.exists())
            self.assertFalse((checkpoint_dir / ".run-state").exists())
            self.assertFalse((checkpoint_dir / ".run-locks").exists())
            self.assertEqual(
                inventory_before,
                sorted(
                    path.relative_to(root).as_posix()
                    for path in root.rglob("*")
                    if path.is_file()
                ),
            )

    def test_number_line_slot20_force_intent_changes_only_target_state_and_is_sealed(self):
        module = _load_builder()
        checkpoint = json.loads(_number_line_checkpoint_bytes(module))
        graph = _graph()
        node = next(item for item in graph["nodes"] if item["id"] == checkpoint["node_id"])
        self.assertFalse(question_bank.v12_is_process_node(node))
        accepted = _items_by_slot(checkpoint)
        before_items = copy.deepcopy(accepted)
        pending = module._pending_repair_from_checkpoint(checkpoint)
        before_pending = copy.deepcopy(pending)
        slot_rounds = {
            slot: int((checkpoint.get("slot_rounds") or {}).get(str(slot), 0) or 0)
            for slot in range(1, 21)
        }
        counters = module._stage_counters_from_checkpoint(
            checkpoint,
            slot_rounds=slot_rounds,
        )
        before_counters = copy.deepcopy(counters)
        events = module._repair_chain_events_from_checkpoint(checkpoint)

        updated_events = module._apply_forced_slot_regeneration(
            node=node,
            graph_version=checkpoint["graph_version"],
            force_slots={20},
            force_slot_modes={20: "standard"},
            force_slot_operation_tokens={20: FORCE_OPERATION_TOKEN},
            accepted_by_slot=accepted,
            pending_repair_by_slot=pending,
            slot_rounds=slot_rounds,
            stage_counters=counters,
            repair_chain_events=events,
        )

        self.assertEqual(before_items.keys() - {20}, accepted.keys())
        for slot in range(1, 20):
            self.assertEqual(before_items[slot], accepted[slot], f"slot {slot} changed")
            self.assertEqual(
                before_counters["local_item_rounds_by_slot"][str(slot)],
                counters["local_item_rounds_by_slot"][str(slot)],
            )
        self.assertEqual(
            {slot: value for slot, value in before_pending.items() if slot != 20},
            {slot: value for slot, value in pending.items() if slot != 20},
        )
        self.assertEqual(0, slot_rounds[20])
        self.assertEqual(0, counters["node_set_review_round"])
        self.assertEqual(1, len(pending[20]))
        self.assertEqual("runtime_elicitation_mode_override", pending[20][0]["reason"])
        self.assertEqual("standard", pending[20][0]["elicitation_mode"])

        event = updated_events[-1]
        self.assertEqual(len(events) + 1, len(updated_events))
        self.assertEqual("operator_force_slot_regeneration", event["stage"])
        self.assertEqual(20, event["slot"])
        self.assertEqual(
            question_bank.v12_external_candidate_sha256(before_items[20]),
            event["old_candidate_sha256"],
        )
        self.assertEqual("", event["new_candidate_sha256"])
        module._validate_repair_chain_events(
            updated_events,
            expected_head_sha256=event["event_sha256"],
            expected_chain_sha256=module._repair_chain_commitment_hash(updated_events),
        )

    def test_force_intent_is_durable_before_first_slot20_model_failure(self):
        module = _load_builder()
        source = _number_line_checkpoint_bytes(module)
        before = json.loads(source)
        before_items = _items_by_slot(before)

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            path = checkpoint_dir / "M-G7-NUMBER-LINE.json"
            path.write_bytes(source)
            with mock.patch.object(
                module,
                "_process_live_slot_chunk",
                side_effect=model_router.ModelCallError("simulated first transport failure"),
            ):
                with self.assertRaisesRegex(
                    model_router.ModelCallError,
                    r"simulated first transport failure",
                ):
                    _build_node_from_checkpoint(
                        module,
                        checkpoint_dir=checkpoint_dir,
                        graph=_graph(),
                        force_slot_modes={20: "standard"},
                    )

            persisted = json.loads(path.read_text(encoding="utf-8"))
            persisted_items = _items_by_slot(persisted)
            self.assertEqual(set(range(1, 20)), set(persisted_items))
            for slot in range(1, 20):
                self.assertEqual(before_items[slot], persisted_items[slot], f"slot {slot} changed")
            pending = module._pending_repair_from_checkpoint(persisted)
            self.assertEqual("standard", pending[20][0]["elicitation_mode"])
            self.assertEqual(
                "operator_force_slot_regeneration",
                persisted["repair_chain_events"][-1]["reason"],
            )
            self.assertEqual(
                "current",
                module._validate_live_checkpoint_integrity(persisted),
            )

    def test_successful_slot20_state_transition_commits_new_candidate_to_repair_chain(self):
        module = _load_builder()
        source = _number_line_checkpoint_bytes(module)
        before = json.loads(source)
        before_items = _items_by_slot(before)
        replacement = _state_only_replacement(before_items[20])
        replacement_sha256 = question_bank.v12_external_candidate_sha256(replacement)
        captured_overrides: list[dict[int, str]] = []

        def fake_slot_chunk(**kwargs):
            captured_overrides.append(dict(kwargs.get("elicitation_mode_overrides") or {}))
            return {
                "round_number": kwargs["round_number"],
                "requested_slots": [20],
                "accepted_by_slot": {20: copy.deepcopy(replacement)},
                "rejected_slots": [],
                "repair_instructions": [],
            }

        class StopAfterForcedCheckpoint(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint_dir = Path(tmp)
            path = checkpoint_dir / "M-G7-NUMBER-LINE.json"
            path.write_bytes(source)
            with mock.patch.object(
                module,
                "_process_live_slot_chunk",
                side_effect=fake_slot_chunk,
            ), mock.patch.object(
                module.question_bank,
                "validate_external_question_bank_v12",
                side_effect=StopAfterForcedCheckpoint("checkpoint captured"),
            ):
                with self.assertRaisesRegex(StopAfterForcedCheckpoint, "checkpoint captured"):
                    _build_node_from_checkpoint(
                        module,
                        checkpoint_dir=checkpoint_dir,
                        graph=_graph(),
                        force_slot_modes={20: "standard"},
                    )

            persisted = json.loads(path.read_text(encoding="utf-8"))
            persisted_items = _items_by_slot(persisted)
            self.assertEqual([{20: "standard"}], captured_overrides)
            self.assertEqual(set(range(1, 21)), set(persisted_items))
            for slot in range(1, 20):
                self.assertEqual(before_items[slot], persisted_items[slot], f"slot {slot} changed")
            self.assertEqual(replacement, persisted_items[20])
            completion_events = [
                event
                for event in persisted["repair_chain_events"]
                if event.get("slot") == 20
                and event.get("new_candidate_sha256") == replacement_sha256
            ]
            self.assertEqual(1, len(completion_events))
            self.assertTrue(completion_events[0]["source_review_artifact_sha256"])
            module._validate_repair_chain_events(
                persisted["repair_chain_events"],
                expected_head_sha256=persisted["repair_chain_head_sha256"],
                expected_chain_sha256=persisted["repair_chain_hash"],
            )
            self.assertEqual(
                "current",
                module._validate_live_checkpoint_integrity(persisted),
            )


if __name__ == "__main__":
    unittest.main()
