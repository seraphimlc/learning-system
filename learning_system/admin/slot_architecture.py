"""Validation for the graph-bound v20 question-slot architecture."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .v20_receipts import SHA256_PATTERN, sha256_json


ARCHITECTURE_SCHEMA_VERSION = "question-slot-architecture.v20"
MIN_PLANNED_SLOT_COUNT = 900
MAX_PLANNED_SLOT_COUNT = 1100
ARCHITECTURE_STATUSES = frozenset({"DRAFT", "REVIEWED", "FROZEN"})
ARCHITECTURE_FIELDS = frozenset(
    {
        "schema_version",
        "architecture_version",
        "status",
        "graph_source",
        "capacity",
        "design_principles",
        "allocation_formula",
        "purpose_mix",
        "question_families",
        "high_impact_nodes",
        "modality_policy",
        "graph_coverage",
        "review_policy",
        "review_evidence",
        "distribution_matrix",
    }
)
BRIEF_AUTHORIZED_STATUSES = frozenset({"REVIEWED", "FROZEN"})
ARCHITECTURE_DIGEST_EXCLUDED_FIELDS = frozenset({"status", "review_evidence"})

# Graph annotation fields that do not change the semantics consumed by the
# architecture, brief generation or brief review. These fields are stripped
# before hashing so that pure annotation backfills (e.g. prereq_strength)
# do not invalidate every frozen architecture/brief/manifest digest.
#
# Keep this set intentionally small: a field belongs here only when no
# architecture/brief consumer reads it. A real structural change (node ids,
# edges, mastery criteria, dependencies) MUST still change the digest.
GRAPH_TOP_LEVEL_DIGEST_EXCLUDED_FIELDS = frozenset({"strong_unlock_edges"})
GRAPH_EDGE_DIGEST_EXCLUDED_FIELDS = frozenset(
    {"prereq_strength", "strength_rationale"}
)


class SlotArchitectureError(ValueError):
    """Raised when the architecture cannot safely produce a slot manifest."""


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotArchitectureError(f"unable to load JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SlotArchitectureError("architecture must be an object")
    return value


def load_graph(path: Path | str) -> dict[str, Any]:
    return load_json(path)


def architecture_content_digest(architecture: dict[str, Any]) -> str:
    """Hash design content while allowing the workflow status to transition."""
    if not isinstance(architecture, dict):
        raise SlotArchitectureError("architecture must be an object")
    content = {
        key: value
        for key, value in architecture.items()
        if key not in ARCHITECTURE_DIGEST_EXCLUDED_FIELDS
    }
    return sha256_json(content)


def graph_semantic_view(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of the graph with annotation-only fields stripped.

    Only fields declared in GRAPH_*_DIGEST_EXCLUDED_FIELDS are removed. These
    are annotation/derived fields that no architecture or brief consumer reads;
    stripping them keeps the content digest stable under pure annotation
    backfills while still detecting any real structural change.
    """
    if not isinstance(graph, dict):
        raise SlotArchitectureError("graph must be an object")
    view = {
        key: value
        for key, value in graph.items()
        if key not in GRAPH_TOP_LEVEL_DIGEST_EXCLUDED_FIELDS
    }
    for key in ("edges", "prerequisite_edges"):
        edges = view.get(key)
        if isinstance(edges, list):
            view[key] = [
                {
                    field: item
                    for field, item in edge.items()
                    if field not in GRAPH_EDGE_DIGEST_EXCLUDED_FIELDS
                }
                if isinstance(edge, dict)
                else edge
                for edge in edges
            ]
    return view


def graph_content_digest(graph: dict[str, Any]) -> str:
    """Hash the graph's semantic content consumed by architecture and briefs.

    Annotation-only fields (e.g. prereq_strength backfill metadata) are
    excluded so that pure annotation additions do not invalidate frozen
    architecture/brief/manifest digests. Real structural changes still
    change the digest.
    """
    if not isinstance(graph, dict):
        raise SlotArchitectureError("graph must be an object")
    return sha256_json(graph_semantic_view(graph))


def load_graph_node_ids(path: Path | str) -> set[str]:
    graph = load_graph(path)
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise SlotArchitectureError("graph nodes must be a list")
    node_ids = {
        str(node.get("id"))
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    if len(node_ids) != len(nodes):
        raise SlotArchitectureError("graph node ids must be unique and nonempty")
    return node_ids


def expected_slot_count(architecture: dict[str, Any]) -> int:
    allocation = architecture.get("allocation_formula")
    if not isinstance(allocation, dict):
        raise SlotArchitectureError("allocation_formula is required")
    base = allocation.get("node_local_base")
    deepening = allocation.get("high_impact_deepening")
    if not isinstance(base, dict) or not isinstance(deepening, dict):
        raise SlotArchitectureError("base and deepening allocations are required")
    return (
        int(base.get("subtotal", -1))
        + int(deepening.get("subtotal", -1))
        + int(allocation.get("cross_node_transfer", -1))
        + int(allocation.get("application_context", -1))
        + int(allocation.get("visual_interactive", -1))
    )


def validate_architecture(
    architecture: Any,
    *,
    graph_node_ids: set[str],
    graph_prerequisite_edges: list[dict[str, Any]] | None = None,
    graph_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(architecture, dict):
        raise SlotArchitectureError("architecture must be an object")
    if architecture.get("schema_version") != ARCHITECTURE_SCHEMA_VERSION:
        raise SlotArchitectureError("unsupported architecture schema")
    if set(architecture) != ARCHITECTURE_FIELDS:
        raise SlotArchitectureError("architecture fields are incomplete or contain unknown fields")
    if architecture.get("status") not in ARCHITECTURE_STATUSES:
        raise SlotArchitectureError("architecture status must be DRAFT, REVIEWED or FROZEN")

    capacity = architecture.get("capacity")
    if not isinstance(capacity, dict):
        raise SlotArchitectureError("capacity is required")
    planned = capacity.get("planned_slot_count")
    if isinstance(planned, bool) or not isinstance(planned, int):
        raise SlotArchitectureError("planned_slot_count must be an integer")
    if not MIN_PLANNED_SLOT_COUNT <= planned <= MAX_PLANNED_SLOT_COUNT:
        raise SlotArchitectureError("planned_slot_count must be between 900 and 1100")
    if expected_slot_count(architecture) != planned:
        raise SlotArchitectureError("allocation formula does not equal planned_slot_count")

    allocation = architecture["allocation_formula"]
    if allocation.get("formula_total") != planned:
        raise SlotArchitectureError("allocation formula_total does not equal planned_slot_count")
    if allocation.get("buckets_are_exclusive") is not True:
        raise SlotArchitectureError("allocation buckets must be explicitly exclusive")
    base = allocation["node_local_base"]
    deepening = allocation["high_impact_deepening"]
    if base.get("node_count") != len(graph_node_ids):
        raise SlotArchitectureError("node_local_base node_count must cover every graph node")
    if base.get("subtotal") != base.get("node_count") * base.get("slots_per_node"):
        raise SlotArchitectureError("node_local_base subtotal is inconsistent")
    if deepening.get("subtotal") != deepening.get("node_count") * deepening.get("extra_slots_per_node"):
        raise SlotArchitectureError("high_impact_deepening subtotal is inconsistent")

    graph_source = architecture.get("graph_source")
    if not isinstance(graph_source, dict) or graph_source.get("expected_node_count") != len(graph_node_ids):
        raise SlotArchitectureError("graph node count does not match architecture")
    declared_graph_digest = graph_source.get("canonical_sha256")
    if not isinstance(declared_graph_digest, str) or not SHA256_PATTERN.fullmatch(declared_graph_digest):
        raise SlotArchitectureError("graph_source.canonical_sha256 is required")
    if graph_digest is not None and declared_graph_digest != graph_digest:
        raise SlotArchitectureError("graph content digest does not match architecture")

    review_evidence = architecture.get("review_evidence")
    if not isinstance(review_evidence, dict) or set(review_evidence) != {
        "receipt_set_sha256",
        "receipt_ids",
        "architecture_digest_sha256",
        "graph_digest_sha256",
        "policy_digest_sha256",
    }:
        raise SlotArchitectureError("review_evidence fields are incomplete or unknown")
    if not isinstance(review_evidence["receipt_ids"], list) or any(
        not isinstance(item, str) or not item.strip() for item in review_evidence["receipt_ids"]
    ):
        raise SlotArchitectureError("review_evidence.receipt_ids must be a list of strings")
    receipt_set_digest = review_evidence["receipt_set_sha256"]
    if receipt_set_digest != "" and not SHA256_PATTERN.fullmatch(receipt_set_digest):
        raise SlotArchitectureError("review_evidence.receipt_set_sha256 must be empty or a digest")
    for field in (
        "architecture_digest_sha256",
        "graph_digest_sha256",
        "policy_digest_sha256",
    ):
        value = review_evidence[field]
        if value != "" and not SHA256_PATTERN.fullmatch(value):
            raise SlotArchitectureError(f"review_evidence.{field} must be empty or a digest")
    if architecture["status"] == "DRAFT" and (receipt_set_digest or review_evidence["receipt_ids"]):
        raise SlotArchitectureError("DRAFT architecture cannot carry review evidence")
    if architecture["status"] == "DRAFT" and any(
        review_evidence[field]
        for field in (
            "architecture_digest_sha256",
            "graph_digest_sha256",
            "policy_digest_sha256",
        )
    ):
        raise SlotArchitectureError("DRAFT architecture cannot carry review digests")

    high_impact = architecture.get("high_impact_nodes")
    if not isinstance(high_impact, list) or len(high_impact) != 24:
        raise SlotArchitectureError("exactly 24 high-impact nodes are required in this draft")
    if len(set(high_impact)) != len(high_impact):
        raise SlotArchitectureError("high-impact nodes must be unique")
    unknown = sorted(set(high_impact) - graph_node_ids)
    if unknown:
        raise SlotArchitectureError(f"unknown high-impact nodes: {unknown}")

    graph_coverage = architecture.get("graph_coverage")
    if not isinstance(graph_coverage, dict):
        raise SlotArchitectureError("graph_coverage is required")
    if graph_prerequisite_edges is not None:
        expected_edges = graph_coverage.get("expected_prerequisite_edge_count")
        if expected_edges != len(graph_prerequisite_edges):
            raise SlotArchitectureError("prerequisite edge count does not match architecture")
        edge_pairs = set()
        for edge in graph_prerequisite_edges:
            if not isinstance(edge, dict):
                raise SlotArchitectureError("prerequisite edges must be objects")
            source, target = edge.get("from"), edge.get("to")
            if source not in graph_node_ids or target not in graph_node_ids:
                raise SlotArchitectureError("prerequisite edge endpoint is unknown")
            edge_pairs.add((source, target))
        if len(edge_pairs) != len(graph_prerequisite_edges):
            raise SlotArchitectureError("prerequisite edges must be unique")
        if graph_coverage.get("require_acyclic_prerequisite_graph"):
            _assert_acyclic(graph_node_ids, edge_pairs)

    purpose_mix = architecture.get("purpose_mix")
    if not isinstance(purpose_mix, dict):
        raise SlotArchitectureError("purpose_mix is required")
    purpose_total = sum(
        int(purpose_mix.get(key, -1))
        for key in ("diagnostic", "guided", "practice", "challenge")
    )
    if purpose_mix.get("total") != purpose_total or purpose_total != planned:
        raise SlotArchitectureError("purpose_mix does not equal planned_slot_count")

    matrix = architecture.get("distribution_matrix")
    if not isinstance(matrix, dict) or set(matrix) != {
        "count_basis",
        "dimensions",
        "frozen_buckets",
        "conditional_buckets",
        "not_precommitted_dimensions",
    }:
        raise SlotArchitectureError("distribution_matrix fields are incomplete or unknown")
    if not isinstance(matrix["count_basis"], str) or not matrix["count_basis"].strip():
        raise SlotArchitectureError("distribution_matrix.count_basis is required")
    if not isinstance(matrix["dimensions"], list) or not matrix["dimensions"]:
        raise SlotArchitectureError("distribution_matrix.dimensions is required")
    if not isinstance(matrix["not_precommitted_dimensions"], list):
        raise SlotArchitectureError("not_precommitted_dimensions must be a list")
    frozen_buckets = matrix["frozen_buckets"]
    if not isinstance(frozen_buckets, dict) or set(frozen_buckets) != {
        "node_local_base",
        "high_impact_deepening",
        "cross_node_transfer",
        "application_context",
        "purpose_mix",
    }:
        raise SlotArchitectureError("distribution_matrix frozen buckets are incomplete")
    required_bucket_fields = {
        "count",
        "derivation_formula",
        "rationale",
        "evidence_refs",
    }
    for bucket_name, bucket in frozen_buckets.items():
        if not isinstance(bucket, dict) or not required_bucket_fields.issubset(bucket):
            raise SlotArchitectureError(f"invalid distribution bucket: {bucket_name}")
        allowed_bucket_fields = set(required_bucket_fields)
        if bucket_name == "purpose_mix":
            allowed_bucket_fields.add("purpose_counts")
            if not isinstance(bucket.get("purpose_counts"), dict):
                raise SlotArchitectureError("distribution purpose_counts are required")
        if set(bucket) != allowed_bucket_fields:
            raise SlotArchitectureError(f"invalid distribution bucket fields: {bucket_name}")
        if isinstance(bucket["count"], bool) or not isinstance(bucket["count"], int) or bucket["count"] < 0:
            raise SlotArchitectureError(f"invalid distribution count: {bucket_name}")
        for field in ("derivation_formula", "rationale"):
            if not isinstance(bucket[field], str) or not bucket[field].strip():
                raise SlotArchitectureError(f"distribution {field} is required: {bucket_name}")
        if not isinstance(bucket["evidence_refs"], list) or not bucket["evidence_refs"]:
            raise SlotArchitectureError(f"distribution evidence_refs are required: {bucket_name}")
    if frozen_buckets["node_local_base"]["count"] != allocation["node_local_base"]["subtotal"]:
        raise SlotArchitectureError("distribution node_local_base count mismatch")
    if frozen_buckets["high_impact_deepening"]["count"] != allocation["high_impact_deepening"]["subtotal"]:
        raise SlotArchitectureError("distribution high_impact_deepening count mismatch")
    if frozen_buckets["cross_node_transfer"]["count"] != allocation["cross_node_transfer"]:
        raise SlotArchitectureError("distribution cross_node_transfer count mismatch")
    if frozen_buckets["application_context"]["count"] != allocation["application_context"]:
        raise SlotArchitectureError("distribution application_context count mismatch")
    if frozen_buckets["purpose_mix"]["count"] != planned:
        raise SlotArchitectureError("distribution purpose_mix count mismatch")
    if sum(
        frozen_buckets[name]["count"]
        for name in (
            "node_local_base",
            "high_impact_deepening",
            "cross_node_transfer",
            "application_context",
        )
    ) + matrix["conditional_buckets"]["visual_interactive"]["count"] != planned:
        raise SlotArchitectureError("exclusive allocation buckets do not equal planned count")
    purpose_bucket = frozen_buckets["purpose_mix"].get("purpose_counts")
    if purpose_bucket is not None and purpose_bucket != {
        key: purpose_mix[key]
        for key in ("diagnostic", "guided", "practice", "challenge")
    }:
        raise SlotArchitectureError("distribution purpose counts mismatch")
    conditional = matrix["conditional_buckets"]
    if not isinstance(conditional, dict) or set(conditional) != {"visual_interactive"}:
        raise SlotArchitectureError("visual conditional bucket is required")
    visual_bucket = conditional["visual_interactive"]
    if not isinstance(visual_bucket, dict) or set(visual_bucket) != {
        "count",
        "status",
        "derivation_formula",
        "rationale",
        "evidence_refs",
    }:
        raise SlotArchitectureError("visual conditional bucket is incomplete")
    if visual_bucket["count"] != allocation["visual_interactive"]:
        raise SlotArchitectureError("visual conditional bucket count mismatch")
    if visual_bucket["status"] != "conditional_on_renderer_authority":
        raise SlotArchitectureError("visual bucket must remain conditional")
    for field in ("derivation_formula", "rationale"):
        if not isinstance(visual_bucket[field], str) or not visual_bucket[field].strip():
            raise SlotArchitectureError(f"visual conditional {field} is required")
    if not isinstance(visual_bucket["evidence_refs"], list) or not visual_bucket["evidence_refs"]:
        raise SlotArchitectureError("visual conditional evidence_refs are required")

    families = architecture.get("question_families")
    if not isinstance(families, list) or not families:
        raise SlotArchitectureError("question_families are required")
    family_ids = [item.get("family_id") for item in families if isinstance(item, dict)]
    if len(family_ids) != len(set(family_ids)) or any(not str(item or "").strip() for item in family_ids):
        raise SlotArchitectureError("question family ids must be unique and nonempty")
    modality_policy = architecture.get("modality_policy")
    if not isinstance(modality_policy, dict) or "visual_interactive" not in modality_policy:
        raise SlotArchitectureError("modality_policy must declare visual_interactive")
    visual_policy = modality_policy["visual_interactive"]
    if not isinstance(visual_policy, dict) or visual_policy.get("status") != "blocked_without_renderer_authority":
        raise SlotArchitectureError("visual_interactive must be blocked without renderer authority")
    modality_ids = set(modality_policy)
    for family in families:
        if not isinstance(family, dict) or family.get("risk_tier") not in {"R1", "R2", "R3"}:
            raise SlotArchitectureError("every family needs a valid risk_tier")
        allowed_modalities = family.get("allowed_modalities")
        if not isinstance(allowed_modalities, list) or not allowed_modalities:
            raise SlotArchitectureError("every family needs allowed_modalities")
        if not set(allowed_modalities).issubset(modality_ids):
            raise SlotArchitectureError("family references an unknown modality")
    return deepcopy(architecture)


def load_and_validate(architecture_path: Path | str, graph_path: Path | str) -> dict[str, Any]:
    graph = load_graph(graph_path)
    return validate_architecture(
        load_json(architecture_path),
        graph_node_ids=load_graph_node_ids(graph_path),
        graph_prerequisite_edges=graph.get("prerequisite_edges"),
        graph_digest=graph_content_digest(graph),
    )


def _assert_acyclic(node_ids: set[str], edges: set[tuple[str, str]]) -> None:
    outgoing = {node: set() for node in node_ids}
    indegree = {node: 0 for node in node_ids}
    for source, target in edges:
        outgoing[source].add(target)
        indegree[target] += 1
    ready = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for target in outgoing[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(node_ids):
        raise SlotArchitectureError("prerequisite graph must be acyclic")


def assert_brief_authorized(
    architecture: dict[str, Any],
    *,
    graph: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prevent slot-brief work until architecture review has passed."""
    if not isinstance(architecture, dict) or set(architecture) != ARCHITECTURE_FIELDS:
        raise SlotArchitectureError("architecture must be validated before authorization")
    if architecture["status"] not in BRIEF_AUTHORIZED_STATUSES:
        raise SlotArchitectureError(
            "slot brief authorization requires REVIEWED or FROZEN architecture"
        )
    evidence = architecture.get("review_evidence")
    if not isinstance(evidence, dict) or not evidence.get("receipt_set_sha256"):
        raise SlotArchitectureError("slot brief authorization requires review evidence")
    if graph is None or policy is None or receipts is None:
        raise SlotArchitectureError(
            "slot brief authorization requires graph, review policy and receipts"
        )
    from .slot_architecture_review import assert_reviewed_artifact, assert_review_ready

    assert_review_ready(
        architecture=architecture,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    assert_reviewed_artifact(
        architecture=architecture,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    return deepcopy(architecture)


def assert_visual_slot_authorized(
    architecture: dict[str, Any],
    *,
    graph: dict[str, Any],
    renderer_authority: dict[str, Any] | None,
    project_root: Path | str,
) -> None:
    """Keep conditional visual capacity blocked until a real authority exists."""
    if architecture["allocation_formula"]["visual_interactive"] == 0:
        return
    if architecture.get("status") not in {"REVIEWED", "FROZEN"}:
        raise SlotArchitectureError("visual slots require reviewed architecture")
    evidence = architecture.get("review_evidence")
    if not isinstance(evidence, dict) or not evidence.get("receipt_set_sha256"):
        raise SlotArchitectureError("visual slots require architecture review evidence")
    from .slot_architecture_review import (
        assert_reviewed_artifact,
        load_policy,
        validate_review_receipt,
    )

    root = Path(project_root).resolve()
    policy = load_policy(root / "data/question_banks/v20/slot_architecture_review_policy_v20.json")
    receipt_dir = root / "data/question_banks/v20/slot_architecture_receipts"
    try:
        receipt_paths = sorted(receipt_dir.glob("*.json"))
        receipts = [
            validate_review_receipt(json.loads(path.read_text(encoding="utf-8")))
            for path in receipt_paths
        ]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SlotArchitectureError("visual slots require real architecture review receipts") from exc
    assert_reviewed_artifact(
        architecture=architecture,
        graph=graph,
        policy=policy,
        receipts=receipts,
    )
    if renderer_authority is None:
        raise SlotArchitectureError("visual slots require renderer authority")
    if renderer_authority.get("status") != "APPROVED":
        raise SlotArchitectureError("visual renderer authority is not approved")
    if not isinstance(renderer_authority.get("authority_id"), str) or not renderer_authority["authority_id"].strip():
        raise SlotArchitectureError("visual authority requires authority_id")
    expected_architecture = architecture_content_digest(architecture)
    expected_graph = graph_content_digest(graph)
    if renderer_authority.get("architecture_sha256") != expected_architecture:
        raise SlotArchitectureError("visual authority architecture digest mismatch")
    if renderer_authority.get("graph_sha256") != expected_graph:
        raise SlotArchitectureError("visual authority graph digest mismatch")
    for path_field, hash_field in (
        ("renderer_path", "renderer_sha256"),
        ("resource_path", "resource_sha256"),
        ("answer_capture_path", "answer_capture_sha256"),
    ):
        relative = renderer_authority.get(path_field)
        if not isinstance(relative, str) or not relative.strip():
            raise SlotArchitectureError(f"visual authority requires {path_field}")
        artifact = (root / relative).resolve()
        if root not in artifact.parents or not artifact.is_file():
            raise SlotArchitectureError(f"visual authority artifact is missing: {path_field}")
        value = renderer_authority.get(hash_field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            raise SlotArchitectureError(f"visual authority requires {hash_field}")
        from .v20_receipts import sha256_bytes

        if value != sha256_bytes(artifact.read_bytes()):
            raise SlotArchitectureError(f"visual authority {hash_field} does not match artifact")
