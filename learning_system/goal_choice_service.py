"""Weekly goal choice service (M5) — 动机层 ② 每周自选目标 (有护栏的自主).

Contract: docs/design/specs/2026-08-20-child-learning-companion-design.md
§6.3.2 (每周让孩子从 2 个候选里自选下周目标). 设计意图 (知几视角):
**有护栏的自主** — 孩子从系统策展的 2 个候选中选, 不是自由选择.
候选策展与选择记录在此服务层; 孩子页面呈现 (child-safe 投影) 由 API 层
(objective ②) 负责 — 本服务只出数据 (内部 node_id + name + reason_label).

Role
----
- `goal_candidates`: 策展 2 个候选 (薄弱候选 + 主线候选), 读
  `learner_node_status` (当前 A/B/C/D) + `graph_nodes` (stage/priority/
  unlocks), 零写入.
- `record_goal_choice`: 写/更新 `weekly_goal_choices` (iso_week 周唯一,
  冲突 → UPSERT 更新, 同 weekly_summary 模式; created_at 保留, updated_at 置位).
- `current_goal_choice` / `goal_choice_history`: 读当周选择 / 历史
  (planner 联动与家长面用), 带出节点名 (服务层返回内部 node_id + name).

候选生成规则 (设计决策, 文档化)
-------------------------------
状态语义 (mastery_rules): A=已掌握 / B=已学但未巩固 / C=薄弱 / D=未掌握.
未建档节点 (无 learner_node_status 行) = 无判定证据.

候选 1 — 薄弱候选 (weakness):
  - 池: 当前状态 C 或 D 的节点; 排序键 (设计决策):
    ① priority 档 (P0 < P1 < P2, 优先核心) →
    ② 解锁数降序 (影响面大优先, unlocks_json 长度) →
    ③ 严重度 (D 先于 C, 缺口更大更急) →
    ④ sequence_band 升序 (先补靠前的阶段) → ⑤ node_id (确定性).
  - 降级: 无 C/D 时 → 池降为 B 档节点 ("已学但未巩固"), 排序同上 (无严重度键).
  - 未建档节点绝不作薄弱候选 (无薄弱证据, 不假装薄弱).
候选 2 — 主线候选 (mainline):
  - 池: stage == '七上主线' 且状态 != A (尚未掌握; 未建档算尚未掌握,
    主线推进不要求先建档).
  - 序: `MAINLINE_SEQUENCE` (七上主线推进序, 私有策展清单 — 本仓库既有
    模式: 各服务私有复制, 不互相 import 私有函数; 依据图谱
    learning_routes.core_dependency_chains + 前置依赖链 + 人教版七上章节序,
    与 planner.CORE_LEARN_PATH 对齐). 清单外节点 (未来图谱新增) 按
    sequence_band → priority → id 兜底排在清单之后.
  - "下一个该学" = 推进序中第一个尚未掌握的主线节点.
去重: 薄弱候选与主线候选撞车 (同一节点) → 主线候选顺延取下一个未掌握主线节点,
保证给孩子 2 个不同的选项. 候选不足 2 个 → 返回实际数量 (不编造).

校验严格性 (record_goal_choice, 设计决策)
----------------------------------------
硬校验 (数据合法性, 服务层): node_ids 为 1-2 个去重的非空节点 id 且都存在
于 graph_nodes; iso_week 格式 YYYY-Www (周 1-53); chosen_by 任意非空串
(默认 'child', 未来家长代选可传 'parent').
不校验 "所选节点必须是当周候选" — 策展护栏属于 API/孩子面 (objective ②):
候选由实时状态每次重新生成, 生成与记录之间状态可能漂移, 服务层硬卡成员会
让记录脆弱且重复实现护栏. 服务层只保证数据合法性, 记录的是孩子的意图存档.
不校验状态非 A — 选择记录是意图存档而非判定 (同理由).

ISO 周边界默认当前 UTC 周, 可注入 ``iso_week`` 便于测试/回放 (与
lightup_service / weekly_report_service / manual_entry_service 的私有副本
模式一致).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone

from learning_system import db

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

STATUS_A = "A"
STATUS_B = "B"
STATUS_C = "C"
STATUS_D = "D"

WEAK_STATUSES = (STATUS_C, STATUS_D)
FALLBACK_WEAK_STATUSES = (STATUS_B,)

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
SEVERITY_RANK = {STATUS_D: 2, STATUS_C: 1}  # D 缺口更大更急

STAGE_MAINLINE = "七上主线"

REASON_WEAK = "这块有点薄弱"
REASON_FALLBACK_B = "学过但还不太牢"
REASON_MAINLINE = "接下来该学这块"

CANDIDATE_KIND_WEAKNESS = "weakness"
CANDIDATE_KIND_MAINLINE = "mainline"

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")

# 七上主线推进序 (主线候选 "下一个该学" 的依据). 依据图谱
# learning_routes.core_dependency_chains + 节点前置依赖链 + 人教版七上章节序
# (有理数 → 整式 → 一元一次方程 → 几何图形初步), 与 planner.CORE_LEARN_PATH
# 对齐; 任何节点在推进序中都在其全部前置之后 (拓扑序). 清单外节点按
# sequence_band → priority → id 兜底 (排在清单之后).
MAINLINE_SEQUENCE = (
    # 有理数 (band 5)
    "M-G7-POS-NEG",            # 正数和负数
    "M-G7-RATIONAL-CLASSIFY",  # 有理数分类
    "M-G7-NUMBER-LINE",        # 数轴
    "M-G7-OPPOSITE",           # 相反数
    "M-G7-ABSOLUTE",           # 绝对值
    "M-G7-COMPARE",            # 有理数大小比较
    "M-G7-RATIONAL-ADD-SUB",   # 有理数加减
    "M-G7-RATIONAL-MUL-DIV",   # 有理数乘除
    "M-G7-POWER",              # 乘方
    "M-G7-RATIONAL-MIXED",     # 有理数混合运算
    "M-G7-SCI-NOTATION-APPROX",  # 科学记数法与近似数
    # 整式的加减 (band 6)
    "M-G7-ALG-EXPR",           # 代数式
    "M-G7-MONOMIAL",           # 单项式
    "M-G7-POLYNOMIAL",         # 多项式
    "M-G7-LIKE-TERMS",         # 同类项
    "M-G7-PARENTHESIS",        # 去括号
    "M-G7-COMBINE-LIKE",       # 合并同类项
    "M-G7-POLY-ADD-SUB",       # 整式加减
    "M-G7-EXPR-VALUE",         # 代数式求值
    # 一元一次方程 (band 7)
    "M-G7-EQUATION-CONCEPT",   # 方程与一元一次方程概念
    "M-G7-EQUALITY-PROP",      # 等式性质
    "M-G7-EQ-SOLVE",           # 解一元一次方程基础
    "M-G7-EQ-PAREN",           # 含括号方程
    "M-G7-EQ-DENOM",           # 含分母方程
    "M-G7-EQ-WORD",            # 一元一次方程应用题
    # 几何图形初步 (band 8)
    "M-G7-GEO-SOLID-PLANE",    # 立体图形与平面图形
    "M-G7-POINT-LINE-PLANE",   # 点线面体
    "M-G7-GEO-VIEWS",          # 展开图与视图
    "M-G7-LINE-RAY-SEGMENT",   # 直线、射线、线段
    "M-G7-SEGMENT-MEASURE",    # 线段比较与计算
    "M-G7-ANGLE",              # 角的概念与表示
    "M-G7-ANGLE-CALC",         # 角度计算
)

# ---------------------------------------------------------------------------
# 候选生成
# ---------------------------------------------------------------------------


def goal_candidates(
    conn: sqlite3.Connection,
    *,
    iso_week: str | None = None,
    limit: int = 2,
) -> list[dict]:
    """策展下周目标候选 (薄弱候选 + 主线候选, 至多 ``limit`` 个).

    Args:
        conn: sqlite3 connection (row_factory=Row) with the M5 schema.
        iso_week: 候选所属 ISO 周 (``2026-W35``), 仅校验格式; 默认当前
            UTC 周. 候选内容由实时 learner_node_status 决定, 周键不参与
            候选判定 (API 层用它把候选与当周选择记录关联).
        limit: 至多返回多少个候选 (默认 2).

    Returns:
        list[dict], 每个候选: {node_id, name, reason_label, stage, priority,
        candidate_kind}; 顺序 = [薄弱候选, 主线候选] (存在时). 候选不足
        ``limit`` 个时返回实际数量 (不编造).
    """
    week_key = iso_week if iso_week is not None else _current_iso_week()
    _validate_iso_week(week_key)
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got: {limit!r}")

    rows = conn.execute(
        """
        select n.id, n.name, n.stage, n.priority, n.sequence_band,
               n.unlocks_json, s.status_code
        from graph_nodes n
        left join learner_node_status s on s.node_id = n.id
        """
    ).fetchall()
    nodes = []
    for row in rows:
        unlocks = db.json_load(row["unlocks_json"], [])
        if not isinstance(unlocks, list):
            unlocks = []
        nodes.append({
            "node_id": row["id"],
            "name": row["name"],
            "stage": row["stage"],
            "priority": row["priority"],
            "sequence_band": row["sequence_band"] or 0,
            "unlock_count": len(unlocks),
            "status_code": row["status_code"] if row["status_code"] in
                (STATUS_A, STATUS_B, STATUS_C, STATUS_D) else None,
        })

    candidates: list[dict] = []

    weakness = _pick_weakness_candidate(nodes)
    if weakness is not None:
        candidates.append(weakness)

    if len(candidates) < limit:
        mainline = _pick_mainline_candidate(
            nodes, exclude={c["node_id"] for c in candidates}
        )
        if mainline is not None:
            candidates.append(mainline)

    return candidates[:limit]


def _pick_weakness_candidate(nodes: list[dict]) -> dict | None:
    """薄弱候选: C/D 优先 (无则 B 降级), P0 → 解锁多 → 严重度 → band → id."""
    weak_pool = [n for n in nodes if n["status_code"] in WEAK_STATUSES]
    fallback = False
    if not weak_pool:
        weak_pool = [n for n in nodes if n["status_code"] in FALLBACK_WEAK_STATUSES]
        fallback = True
    if not weak_pool:
        return None
    pick = min(weak_pool, key=_weakness_sort_key)
    reason = REASON_FALLBACK_B if fallback else REASON_WEAK
    return _candidate(pick, reason, CANDIDATE_KIND_WEAKNESS)


def _weakness_sort_key(node: dict) -> tuple:
    priority_rank = PRIORITY_RANK.get(node["priority"], 3)
    severity = SEVERITY_RANK.get(node["status_code"], 0)
    return (
        priority_rank,
        -node["unlock_count"],
        severity,
        node["sequence_band"],
        node["node_id"],
    )


def _pick_mainline_candidate(nodes: list[dict], *, exclude: set[str]) -> dict | None:
    """主线候选: 尚未掌握 (非 A, 含未建档) 的七上主线节点, 推进序第一个."""
    pool = [
        n for n in nodes
        if n["stage"] == STAGE_MAINLINE
        and n["status_code"] != STATUS_A
        and n["node_id"] not in exclude
    ]
    if not pool:
        return None
    pick = min(pool, key=lambda n: _mainline_sort_key(n))
    return _candidate(pick, REASON_MAINLINE, CANDIDATE_KIND_MAINLINE)


def _mainline_sort_key(node: dict) -> tuple:
    try:
        seq_index = MAINLINE_SEQUENCE.index(node["node_id"])
    except ValueError:
        seq_index = len(MAINLINE_SEQUENCE)  # 清单外 → 排最后, 按 band/priority/id
    priority_rank = PRIORITY_RANK.get(node["priority"], 3)
    return (
        seq_index,
        node["sequence_band"],
        priority_rank,
        node["node_id"],
    )


def _candidate(node: dict, reason_label: str, kind: str) -> dict:
    return {
        "node_id": node["node_id"],
        "name": node["name"],
        "reason_label": reason_label,
        "stage": node["stage"],
        "priority": node["priority"],
        "candidate_kind": kind,
    }


# ---------------------------------------------------------------------------
# 选择记录
# ---------------------------------------------------------------------------


def record_goal_choice(
    conn: sqlite3.Connection,
    *,
    iso_week: str,
    node_ids: list[str],
    chosen_by: str = "child",
    commit: bool = True,
) -> dict:
    """记录/更新一周的选择 (iso_week 冲突 → UPSERT, 同 weekly_summary 模式).

    Args:
        conn: sqlite3 connection (row_factory=Row) with the M5 schema.
        iso_week: ISO 周键 ``2026-W35`` (格式校验: YYYY-Www, 周 1-53).
        node_ids: 选中的 1-2 个节点 id (去重, 非空, 须存在于 graph_nodes).
        chosen_by: 选择者, 默认 'child' (家长代选可传 'parent').
        commit: 是否立即 commit (默认 True).

    Returns:
        记录 dict: {id, iso_week, node_ids, chosen_by, created_at, updated_at,
        nodes: [{node_id, name, stage}]} (读取形状同 current_goal_choice).

    Raises:
        ValueError: iso_week 格式非法 / node_ids 数量不在 1-2 / 含空串或重复 /
            节点不存在于 graph_nodes.
    """
    _validate_iso_week(iso_week)
    _validate_node_ids(conn, node_ids)
    if not chosen_by or not str(chosen_by).strip():
        raise ValueError(f"chosen_by must be non-empty, got: {chosen_by!r}")

    now = db.now_iso()
    choice_id = f"GC-{uuid.uuid4().hex[:12]}"
    node_ids_json = db.json_dump(node_ids)

    conn.execute(
        """
        insert into weekly_goal_choices(
          id, iso_week, node_ids_json, chosen_by, created_at, updated_at
        ) values (?, ?, ?, ?, ?, ?)
        on conflict(iso_week) do update set
          node_ids_json = excluded.node_ids_json,
          chosen_by = excluded.chosen_by,
          updated_at = ?
        """,
        (choice_id, iso_week, node_ids_json, chosen_by, now, None, now),
    )
    if commit:
        conn.commit()

    return _read_choice(conn, iso_week)


def current_goal_choice(
    conn: sqlite3.Connection,
    *,
    iso_week: str | None = None,
) -> dict | None:
    """读当周选择 (planner 联动与家长面用); 无记录返回 None.

    iso_week 默认当前 UTC 周. 返回 {id, iso_week, node_ids, chosen_by,
    created_at, updated_at, nodes: [{node_id, name, stage}]}.
    """
    week_key = iso_week if iso_week is not None else _current_iso_week()
    _validate_iso_week(week_key)
    return _read_choice(conn, week_key)


def goal_choice_history(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
) -> list[dict]:
    """历史选择 (家长面), 按周倒序, 至多 ``limit`` 条."""
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got: {limit!r}")
    rows = conn.execute(
        "select iso_week from weekly_goal_choices order by iso_week desc limit ?",
        (limit,),
    ).fetchall()
    return [_read_choice(conn, row["iso_week"]) for row in rows]


# ---------------------------------------------------------------------------
# 读取/校验辅助
# ---------------------------------------------------------------------------


def _read_choice(conn: sqlite3.Connection, iso_week: str) -> dict | None:
    row = conn.execute(
        """
        select w.id, w.iso_week, w.node_ids_json, w.chosen_by,
               w.created_at, w.updated_at
        from weekly_goal_choices w
        where w.iso_week = ?
        """,
        (iso_week,),
    ).fetchone()
    if row is None:
        return None
    node_ids = db.json_load(row["node_ids_json"], [])
    if not isinstance(node_ids, list):
        node_ids = []
    node_ids = [str(item) for item in node_ids]
    nodes = []
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        name_rows = conn.execute(
            f"select id, name, stage from graph_nodes where id in ({placeholders})",
            node_ids,
        ).fetchall()
        names = {r["id"]: r for r in name_rows}
        for node_id in node_ids:
            info = names.get(node_id)
            nodes.append({
                "node_id": node_id,
                "name": info["name"] if info else None,
                "stage": info["stage"] if info else None,
            })
    return {
        "id": row["id"],
        "iso_week": row["iso_week"],
        "node_ids": node_ids,
        "chosen_by": row["chosen_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "nodes": nodes,
    }


def _validate_node_ids(conn: sqlite3.Connection, node_ids) -> None:
    if not isinstance(node_ids, (list, tuple)):
        raise ValueError(f"node_ids must be a list of 1-2 node ids, got: {node_ids!r}")
    ids = list(node_ids)
    if not (1 <= len(ids) <= 2):
        raise ValueError(f"node_ids must contain 1-2 nodes, got {len(ids)}")
    if any(not isinstance(item, str) or not item.strip() for item in ids):
        raise ValueError(f"node_ids entries must be non-empty strings, got: {node_ids!r}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"node_ids must not contain duplicates, got: {node_ids!r}")
    placeholders = ",".join("?" for _ in ids)
    existing = {
        row["id"]
        for row in conn.execute(
            f"select id from graph_nodes where id in ({placeholders})", ids
        ).fetchall()
    }
    missing = [item for item in ids if item not in existing]
    if missing:
        raise ValueError(f"unknown node_ids (not in graph_nodes): {missing}")


def _validate_iso_week(iso_week: str) -> None:
    match = _ISO_WEEK_RE.match(iso_week)
    if not match:
        raise ValueError(
            f"invalid iso_week format (expected YYYY-Www), got: {iso_week!r}"
        )
    week = int(match.group(2))
    if not (1 <= week <= 53):
        raise ValueError(f"iso week out of range (1-53), got: {iso_week!r}")


def _current_iso_week() -> str:
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"
