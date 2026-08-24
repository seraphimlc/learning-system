"""Question generation & verification pipeline core (objective ③).

Contract under test: `docs/design/specs/2026-08-20-question-bank-contract.md`
(§3 每节点矩阵、§4 校验门禁、§5 元数据派生、§6 生成管线) + 图谱 v2 每节点
`question_generation` 契约 (seed_question_types / variant_ladder /
minimum_daily_set / avoid) 与 `diagnostic_probes`。

设计要点:

- **生成器注入**: `generate_node_bank(conn, node_id, generate_fn=...)` —
  管线不实现 LLM 调用; `generate_fn(batch_spec) -> list[raw_question_dict]`
  由试点阶段 (objective ④) 提供真实适配, 测试用 fake。
- **批量编排**: `node_batch_specs` 按契约 §3 矩阵把每节点 15 题切成 5 批
  (每批 3 题, 均 3-5), 批规格携带生成器需要的全部上下文
  (题型/难度/purpose_role/variant_level/seed_question_type 素材/
  diagnostic_probe 素材/variant_ladder/minimum_daily_set/avoid)。
- **sympy 校验门禁** (§4): 逐题 `verify_expected_answer` —
  verified → 保留; mismatch → 该题重出 (≤ max_retries=2, 注入式重新调
  generate_fn), 仍失败 → 丢弃并计数; unverifiable → 标记保留 (概念类)。
- **元数据派生** (§5): error_tags 从 `CANONICAL_ERROR_TAGS` 按题型选;
  rollback_candidate_node_ids 从图谱 prerequisites 派生 (prerequisite_edges
  strong 优先, 有图谱 dict 时); secondary_node_ids 迁移题标前后知识;
  estimated_minutes 按题型/难度 1-8 分钟。
- **入库**: 用 db.py 既有 `upsert_question` (校验图引用 + review 记录 +
  用量策略), 随后在同一事务内写 3 个契约新列
  (difficulty/purpose_role/answer_verification —— upsert_question 的 INSERT
  不含这三列, 落库后显式 UPDATE)。
- **幂等**: 题 ID 确定性派生 `Q-{node_id}-B{batch}-I{item_index}` +
  upsert (insert or replace) → 同节点重跑不重复入库。

边界: 不实现真实 LLM; 不改 db.py/answer_verification.py。
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from learning_system import db
from learning_system.answer_verification import verify_expected_answer
from learning_system.error_tags import CANONICAL_ERROR_TAGS

QUESTION_ITEM_VERSION = "2026-08-20.v1"
SOURCE_TYPE = "graph_generated"

VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})

# 契约 §3 每节点题目矩阵 (目标 12-20 题; 这里 15 题):
# (matrix_label, question_type_slot, difficulty, purpose_role, variant_level, kind)
# - slot "seed": 素材来自 question_generation.seed_question_types
# - slot "probe": 素材来自 diagnostic_probes (检测/复测/诊断题)
_NODE_MATRIX: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("标准例题", "seed", "medium", "core", "L2", "standard_example"),
    ("变式L1识别", "seed", "easy", "core", "L1", "variant"),
    ("变式L1识别", "seed", "easy", "core", "L1", "variant"),
    ("变式L2套用", "seed", "easy", "core", "L2", "variant"),
    ("变式L2套用", "seed", "medium", "core", "L2", "variant"),
    ("变式L3变式", "seed", "medium", "core", "L3", "variant"),
    ("变式L3变式", "seed", "medium", "core", "L3", "variant"),
    ("变式L4迁移", "seed", "hard", "transfer", "L4", "stretch_transfer"),
    ("变式L4迁移", "seed", "hard", "transfer", "L4", "stretch_transfer"),
    ("检测题", "probe", "easy", "core", "L2", "mastery_check"),
    ("检测题", "probe", "hard", "core", "L3", "mastery_check"),
    ("复测题", "probe", "medium", "core", "L3", "evidence_driven_retest"),
    ("复测题", "probe", "hard", "core", "L4", "evidence_driven_retest"),
    ("诊断题", "probe", "easy", "core", "L1", "misconception_probe"),
    ("诊断题", "probe", "medium", "core", "L2", "misconception_probe"),
)

# 5 批 × 3 题 (每批 3-5): 脚手架 → 套用 → 变式核心 → 检测/复测 → 诊断/迁移
_BATCH_GROUPS: tuple[tuple[int, tuple[int, ...]], ...] = (
    (1, (0, 1, 2)),
    (2, (3, 4, 5)),
    (3, (6, 7, 8)),
    (4, (9, 10, 11)),
    (5, (12, 13, 14)),
)

# 题型 → CANONICAL_ERROR_TAGS 常见错因 (§5: 按题型选 1-2 个)
_QUESTION_TYPE_TAG_RULES: tuple[tuple[str, str], ...] = (
    ("概念", "concept_confusion"),
    ("识别", "concept_confusion"),
    ("判断", "concept_confusion"),
    ("应用", "modeling_or_reading"),
    ("建模", "modeling_or_reading"),
    ("读题", "modeling_or_reading"),
    ("计算", "calculation_or_symbol"),
    ("运算", "calculation_or_symbol"),
    ("列式", "calculation_or_symbol"),
    ("加减", "calculation_or_symbol"),
    ("乘除", "calculation_or_symbol"),
    ("互化", "calculation_or_symbol"),
    ("化简", "calculation_or_symbol"),
    ("求值", "calculation_or_symbol"),
    ("解方程", "calculation_or_symbol"),
    ("过程", "process_habit"),
    ("步骤", "process_habit"),
    ("检查", "process_habit"),
    ("检验", "process_habit"),
    ("复盘", "process_habit"),
    ("几何", "visual_spatial"),
    ("图形", "visual_spatial"),
    ("位置", "visual_spatial"),
    ("看图", "visual_spatial"),
)

# 估算时长 (§5: 按题型/难度 1-8 分钟)
_MINUTES_BASE = {"easy": 2, "medium": 4, "hard": 6}


# ---------------------------------------------------------------------------
# 节点解析 / 批规格
# ---------------------------------------------------------------------------


def _resolve_node(conn_or_graph: Any, node_id: str) -> dict[str, Any]:
    """Node contract dict from a sqlite connection or a graph JSON dict."""
    if isinstance(conn_or_graph, sqlite3.Connection):
        return db.get_graph_node(conn_or_graph, node_id)
    for node in conn_or_graph.get("nodes", []):
        if str(node.get("id")) == node_id:
            return node
    raise KeyError(f"Unknown graph node: {node_id}")


def _ladder_by_level(variant_ladder: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in variant_ladder or []:
        match = re.match(r"\s*(L[1-4])\b", str(entry))
        if match:
            result[match.group(1)] = str(entry)
    return result


def node_batch_specs(conn_or_graph: Any, node_id: str) -> list[dict[str, Any]]:
    """契约 §6 第 1 步: 读节点 question_generation 契约 → 该节点的批规格.

    每批 3-5 题, 批规格携带生成器需要的全部上下文:
    题型/难度/purpose_role/variant_level/seed_question_type 素材/
    diagnostic_probe 素材 + variant_ladder/minimum_daily_set/avoid。
    """
    node = _resolve_node(conn_or_graph, node_id)
    contract = node.get("question_generation") or {}
    seed_types = [
        str(item).strip()
        for item in (contract.get("seed_question_types") or node.get("question_types") or [node_id])
        if str(item).strip()
    ]
    probes = [str(item).strip() for item in (node.get("diagnostic_probes") or []) if str(item).strip()]
    ladder = _ladder_by_level(contract.get("variant_ladder") or [])
    node_name = str(node.get("name", ""))

    batches: list[dict[str, Any]] = []
    for batch_index, offsets in _BATCH_GROUPS:
        items: list[dict[str, Any]] = []
        for per_batch_index, offset in enumerate(offsets):
            label, slot, difficulty, purpose_role, variant_level, kind = _NODE_MATRIX[offset]
            question_type = seed_types[offset % len(seed_types)]
            diagnostic_probe = probes[offset % len(probes)] if slot == "probe" and probes else None
            items.append(
                {
                    "item_index": per_batch_index,
                    "matrix_label": label,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "purpose_role": purpose_role,
                    "variant_level": variant_level,
                    "kind": kind,
                    "seed_question_type": question_type,
                    "diagnostic_probe": diagnostic_probe,
                    "ladder_description": ladder.get(variant_level, variant_level),
                }
            )
        batches.append(
            {
                "node_id": node_id,
                "node_name": node_name,
                "batch_index": batch_index,
                "total_batches": len(_BATCH_GROUPS),
                "variant_ladder": contract.get("variant_ladder") or [],
                "minimum_daily_set": str(contract.get("minimum_daily_set", "")),
                "avoid": str(contract.get("avoid", "")),
                "essence_for_child": str(node.get("essence_for_child", "")),
                "items": items,
            }
        )
    return batches


# ---------------------------------------------------------------------------
# 元数据派生 (§5)
# ---------------------------------------------------------------------------


def derive_error_tags(item: dict[str, Any], node: dict[str, Any] | None = None) -> list[str]:
    """按题型从 CANONICAL_ERROR_TAGS 选 1-2 个常见错因 (单一源, 不发明标签)."""
    haystack = " ".join(
        str(item.get(key, "")) for key in ("question_type", "matrix_label", "kind")
    )
    matched: list[str] = []
    for keyword, tag in _QUESTION_TYPE_TAG_RULES:
        if keyword in haystack and tag not in matched:
            matched.append(tag)
    if not matched and node:
        for tag in (node.get("error_diagnosis") or {}).get("likely_error_tags") or []:
            if tag in CANONICAL_ERROR_TAGS and tag not in matched:
                matched.append(tag)
    if not matched:
        return ["general"]
    return matched[:2]


def derive_rollback_candidates(
    node: dict[str, Any], graph: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """从图谱 prerequisites 派生错因回退候选 (prerequisite_edges strong 优先).

    有 graph dict (含 prerequisite_edges 的 prereq_strength) 时只取 strong 边;
    否则回退到节点 prerequisites 顺序; 再否则 error_diagnosis.rollback_to。
    """
    node_id = str(node.get("id", ""))
    strong_sources: list[str] = []
    if graph and isinstance(graph.get("prerequisite_edges"), list):
        for edge in graph["prerequisite_edges"]:
            if str(edge.get("to", "")) == node_id and edge.get("prereq_strength") == "strong":
                strong_sources.append(str(edge.get("from", "")))
    if strong_sources:
        strong_set = set(strong_sources)
        ordered: list[str] = []
        seen: set[str] = set()
        for prereq in node.get("prerequisites", []):
            prereq = str(prereq)
            if prereq in strong_set and prereq not in seen:
                ordered.append(prereq)
                seen.add(prereq)
        for source in strong_sources:
            if source not in seen:
                ordered.append(source)
                seen.add(source)
        return [
            {"node_id": node_id, "relation": "prerequisite", "strength": "strong"}
            for node_id in ordered
        ]
    prerequisites = [str(p) for p in (node.get("prerequisites") or []) if str(p).strip()]
    if prerequisites:
        return [
            {"node_id": node_id, "relation": "prerequisite", "strength": "unknown"}
            for node_id in prerequisites
        ]
    rollback_to = [
        str(r) for r in ((node.get("error_diagnosis") or {}).get("rollback_to") or []) if str(r).strip()
    ]
    return [
        {"node_id": node_id, "relation": "rollback", "strength": "unknown"}
        for node_id in rollback_to
    ]


def derive_secondary_node_ids(item: dict[str, Any], node: dict[str, Any]) -> list[str]:
    """迁移题 (purpose_role=transfer) 标注前后知识节点; core 题为空."""
    if item.get("purpose_role") != "transfer":
        return []
    before = [str(p) for p in (node.get("prerequisites") or []) if str(p).strip()]
    after = [str(u) for u in (node.get("unlocks") or []) if str(u).strip()]
    node_id = str(node.get("id", ""))
    result: list[str] = []
    seen: set[str] = set()
    for candidate in before + after:
        if candidate and candidate != node_id and candidate not in seen:
            result.append(candidate)
            seen.add(candidate)
    return result


def estimate_minutes(difficulty: str, purpose_role: str, kind: str) -> int:
    """按题型/难度估时, 1-8 分钟."""
    base = _MINUTES_BASE.get(difficulty, 3)
    if purpose_role == "transfer":
        base += 1
    if kind in {"mastery_check", "misconception_probe", "evidence_driven_retest"}:
        base += 1
    return max(1, min(8, base))


# ---------------------------------------------------------------------------
# 入库
# ---------------------------------------------------------------------------


def question_id_for(node_id: str, batch_index: int, item_index: int) -> str:
    """确定性题 ID (幂等重跑的基础: 同槽位同 ID, upsert 覆盖不重复)."""
    return f"Q-{node_id}-B{batch_index}-I{item_index}"


def _spec_defaults(batch_spec: dict[str, Any], item_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question_id_for(
            batch_spec["node_id"], batch_spec["batch_index"], item_spec["item_index"]
        ),
        "node_id": batch_spec["node_id"],
        "node_name": batch_spec.get("node_name", ""),
        "batch_index": batch_spec["batch_index"],
        "item_index": item_spec["item_index"],
        "matrix_label": item_spec["matrix_label"],
        "question_type": item_spec["question_type"],
        "difficulty": item_spec["difficulty"],
        "purpose_role": item_spec["purpose_role"],
        "variant_level": item_spec["variant_level"],
        "kind": item_spec["kind"],
        "seed_question_type": item_spec["seed_question_type"],
        "diagnostic_probe": item_spec.get("diagnostic_probe"),
        "item_version": QUESTION_ITEM_VERSION,
        "source_type": SOURCE_TYPE,
        "source": {
            "type": SOURCE_TYPE,
            "graph_node_id": batch_spec["node_id"],
            "pipeline": "question_generation_service",
            "batch_index": batch_spec["batch_index"],
        },
    }


def _pair_raw_to_items(
    items: list[dict[str, Any]], raw_items: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """把 generate_fn 的原始题按顺序 (或 item_index) 配到批内槽位."""
    if len(raw_items) == len(items):
        return list(zip(items, raw_items))
    by_index: dict[int, dict[str, Any]] = {}
    for raw in raw_items:
        if "item_index" in raw:
            by_index[int(raw["item_index"])] = raw
    if by_index and len(by_index) == len(raw_items):
        pairs = [(item_spec, by_index[i]) for i, item_spec in enumerate(items) if i in by_index]
        if len(pairs) == len(items):
            return pairs
    raise ValueError(
        f"generate_fn returned {len(raw_items)} raw questions for {len(items)} batch items"
    )


def _enrich_metadata(
    item: dict[str, Any], node: dict[str, Any], graph: dict[str, Any] | None
) -> dict[str, Any]:
    """§5 元数据派生: error_tags / rollback / secondary / estimated_minutes."""
    if not item.get("target_error_tags"):
        item["target_error_tags"] = derive_error_tags(item, node)
    if not item.get("rollback_candidates"):
        relations = derive_rollback_candidates(node, graph)
        item["rollback_candidates"] = [relation["node_id"] for relation in relations]
        item["rollback_candidate_relations"] = relations
    if not item.get("secondary_node_ids"):
        item["secondary_node_ids"] = derive_secondary_node_ids(item, node)
    if not item.get("estimated_minutes"):
        item["estimated_minutes"] = estimate_minutes(
            str(item.get("difficulty", "medium")),
            str(item.get("purpose_role", "core")),
            str(item.get("kind", "")),
        )
    return item


def _ingest(conn: sqlite3.Connection, item: dict[str, Any], answer_verification: str) -> None:
    """用 db.upsert_question 入库 (校验图引用/review 记录/用量策略),
    随后写 3 个契约新列 (upsert_question 的 INSERT 不含这三列)."""
    db.upsert_question(conn, item)
    conn.execute(
        "update question_items set difficulty = ?, purpose_role = ?, answer_verification = ? where id = ?",
        (
            str(item.get("difficulty", "medium")),
            str(item.get("purpose_role", "core")),
            answer_verification,
            item["id"],
        ),
    )


def _retry_spec(
    batch_spec: dict[str, Any],
    item_spec: dict[str, Any],
    verification: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    """mismatch 重出规格: 单题批 + 错因上下文 (注入式回生成器)."""
    reason = verification.get("reason") or (
        f"expression {verification.get('expression')} != expected {verification.get('expected')}"
    )
    return {
        **batch_spec,
        "retry": True,
        "retry_attempt": attempt,
        "mismatch_reason": str(reason),
        "items": [dict(item_spec, retry_attempt=attempt)],
    }


# ---------------------------------------------------------------------------
# 管线编排 (§6)
# ---------------------------------------------------------------------------


def generate_node_bank(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    generate_fn,
    verify: bool = True,
    max_retries: int = 2,
    commit: bool = True,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逐批调 generate_fn → sympy 校验门禁 → 元数据派生 → 入库.

    generate_fn(batch_spec) -> list[raw_question_dict]; raw 最少需含
    prompt + expected_answer, 其余字段 (题型/难度/角色/等级/元数据) 由
    管线按批规格默认 + 派生。

    返回统计: {generated, verified, mismatch_discarded, unverifiable,
    ingested, generate_calls, batches, node_id}。
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    node = _resolve_node(conn, node_id)
    batches = node_batch_specs(conn, node_id)

    verified = unverifiable = pending = mismatch_discarded = 0
    generate_calls = 0

    for batch_spec in batches:
        raw_items = generate_fn(batch_spec)
        generate_calls += 1
        pairs = _pair_raw_to_items(batch_spec["items"], raw_items)
        for item_spec, raw in pairs:
            item = {
                **_spec_defaults(batch_spec, item_spec),
                **{key: value for key, value in raw.items() if value is not None},
            }
            if not str(item.get("prompt", "")).strip():
                raise ValueError(f"generate_fn produced a question without a prompt: {item_spec}")
            if not str(item.get("expected_answer", "")).strip():
                raise ValueError(
                    f"generate_fn produced a question without expected_answer: {item_spec}"
                )
            item = _enrich_metadata(item, node, graph)

            verdict = "pending"
            if verify:
                verification = verify_expected_answer(str(item["prompt"]), str(item["expected_answer"]))
                verdict = verification["verdict"]
                if verdict == "mismatch":
                    accepted = None
                    for attempt in range(1, max_retries + 1):
                        retry_spec = _retry_spec(batch_spec, item_spec, verification, attempt)
                        retry_raw = generate_fn(retry_spec)
                        generate_calls += 1
                        retry_pairs = _pair_raw_to_items(retry_spec["items"], retry_raw)
                        if not retry_pairs:
                            continue
                        retry_spec_item, retry_raw_item = retry_pairs[0]
                        retry_item = {
                            **_spec_defaults(retry_spec, retry_spec_item),
                            **{key: value for key, value in retry_raw_item.items() if value is not None},
                        }
                        if not str(retry_item.get("prompt", "")).strip() or not str(
                            retry_item.get("expected_answer", "")
                        ).strip():
                            continue
                        retry_item = _enrich_metadata(retry_item, node, graph)
                        verification = verify_expected_answer(
                            str(retry_item["prompt"]), str(retry_item["expected_answer"])
                        )
                        if verification["verdict"] == "mismatch":
                            continue
                        item, verdict = retry_item, verification["verdict"]
                        accepted = True
                        break
                    if accepted is None:
                        mismatch_discarded += 1
                        continue

            if verdict == "verified":
                verified += 1
            elif verdict == "unverifiable":
                unverifiable += 1
            elif verdict == "pending":
                pending += 1
            _ingest(conn, item, verdict)

    if commit:
        conn.commit()
    return {
        "node_id": node_id,
        "generated": verified + unverifiable + pending + mismatch_discarded,
        "verified": verified,
        "mismatch_discarded": mismatch_discarded,
        "unverifiable": unverifiable,
        "ingested": verified + unverifiable + pending,
        "generate_calls": generate_calls,
        "batches": len(batches),
    }


# ---------------------------------------------------------------------------
# 批间契约校验 (§6 第 6 步)
# ---------------------------------------------------------------------------


def validate_node_bank_contract(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    item_version: str = QUESTION_ITEM_VERSION,
) -> dict[str, Any]:
    """节点题集是否满足契约 §3 判定层证据保证:

    - ≥2 个 question_type 族 (指纹 C2)
    - ≥1 条 transfer 题 (双角色 C3)
    - 难度分布达标: 有 easy/medium/hard 即可 (精确配比按契约 §3)
    - answer_verification 无 mismatch (§4 质量红线)
    """
    rows = conn.execute(
        """
        select question_type, kind, difficulty, purpose_role, answer_verification
        from question_items
        where node_id = ? and item_version = ?
        """,
        (node_id, item_version),
    ).fetchall()

    fingerprints: dict[tuple[str, str], int] = {}
    transfer_count = 0
    difficulty_counts: dict[str, int] = {}
    verification_counts: dict[str, int] = {}
    for row in rows:
        question_type = str(row["question_type"] or "").strip()
        kind = str(row["kind"] or "").strip()
        if question_type:
            key = (kind, question_type)
            fingerprints[key] = fingerprints.get(key, 0) + 1
        if str(row["purpose_role"] or "") == "transfer":
            transfer_count += 1
        difficulty = str(row["difficulty"] or "").strip()
        if difficulty:
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
        verification = str(row["answer_verification"] or "pending").strip()
        verification_counts[verification] = verification_counts.get(verification, 0) + 1

    question_type_families = {question_type for (_kind, question_type) in fingerprints}
    difficulties = set(difficulty_counts)

    checks = {
        "fingerprints_ok": len(question_type_families) >= 2,
        "transfer_ok": transfer_count >= 1,
        "difficulty_distribution_ok": VALID_DIFFICULTIES <= difficulties,
        "no_mismatch": verification_counts.get("mismatch", 0) == 0,
    }
    errors: list[str] = []
    if not checks["fingerprints_ok"]:
        errors.append(
            f"指纹不足: 仅 {len(question_type_families)} 个 question_type 族 (要求 ≥2)"
        )
    if not checks["transfer_ok"]:
        errors.append("缺少 transfer 题 (要求 ≥1 条 purpose_role=transfer)")
    if not checks["difficulty_distribution_ok"]:
        missing = sorted(VALID_DIFFICULTIES - difficulties)
        errors.append(f"难度分布不达标: 缺 {missing} (要求含 easy/medium/hard)")
    if not checks["no_mismatch"]:
        errors.append(
            f"存在 answer_verification=mismatch 的行 ({verification_counts.get('mismatch', 0)} 条), 不应入库"
        )

    return {
        "node_id": node_id,
        "question_count": len(rows),
        "fingerprint_count": len(question_type_families),
        "fingerprints": sorted(f"{kind}:{question_type}" for (kind, question_type) in fingerprints),
        "transfer_count": transfer_count,
        "difficulty_counts": difficulty_counts,
        "answer_verification_counts": verification_counts,
        "checks": checks,
        "errors": errors,
        "valid": all(checks.values()),
    }
