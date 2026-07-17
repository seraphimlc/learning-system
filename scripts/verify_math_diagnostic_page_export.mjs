#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const diagnostic = JSON.parse(fs.readFileSync(path.join(root, "data/questions/math_diagnostic_v1.json"), "utf8"));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function buildExportData(attemptsByItemId) {
  const now = "2026-07-05T00:00:00.000Z";
  const attemptList = diagnostic.items.map((item) => attemptsByItemId[item.id]).filter(Boolean);
  const gradedAttemptList = attemptList.filter((attempt) =>
    attempt.grading_status === "graded" &&
    ["correct", "partial", "wrong"].includes(attempt.result) &&
    Number.isFinite(attempt.score_points) &&
    Number.isFinite(attempt.max_points)
  );
  const byNode = new Map();
  for (const attempt of gradedAttemptList) {
    if (!byNode.has(attempt.node_id)) byNode.set(attempt.node_id, []);
    byNode.get(attempt.node_id).push(attempt);
  }
  const node_status = Array.from(byNode.entries()).map(([node_id, rows]) => {
    const max = rows.reduce((sum, row) => sum + row.max_points, 0);
    const score = rows.reduce((sum, row) => sum + row.score_points, 0);
    const canExplain = rows.some((row) => row.child_explanation_score_0_to_2 === 2);
    const ratio = max ? score / max : 0;
    const hasBlockingEvidence = rows.some((row) => row.blocking_evidence === true);
    const status = hasBlockingEvidence ? "D" : ratio >= .85 && canExplain ? "A" : ratio >= .6 ? "B" : "C";
    const relationRows = rows.flatMap((row) => row.rollback_candidate_relations || []);
    const unverifiedPrerequisites = Array.from(new Set(
      relationRows.filter((row) => row.relation === "prerequisite_chain").map((row) => row.node_id)
    ));
    const followupProbes = Array.from(new Set(
      relationRows.filter((row) => row.relation === "followup_probe").map((row) => row.node_id)
    ));
    return {
      node_id,
      status_code: status,
      evidence_source: "direct",
      latest_score: Number(ratio.toFixed(2)),
      can_explain: canExplain,
      evidence_question_ids: rows.map((row) => row.question_id),
      last_review_date: now.slice(0, 10),
      next_review_date: "",
      status_reason: hasBlockingEvidence
        ? "Derived from explicit skip/cannot-start evidence in this diagnostic attempt."
        : "Derived from parent-graded diagnostic attempts only; ungraded answers are excluded.",
      unverified_prerequisite_node_ids: status === "A" ? [] : unverifiedPrerequisites,
      followup_probe_node_ids: status === "A" ? [] : followupProbes,
    };
  });
  return {
    attempt_export_id: `${diagnostic.diagnostic_id}-test`,
    schema_version: "1.0.0",
    diagnostic_id: diagnostic.diagnostic_id,
    diagnostic_version: diagnostic.diagnostic_version,
    graph_ref: diagnostic.graph_ref,
    session_date: now.slice(0, 10),
    started_at: "",
    ended_at: now,
    duration_seconds: null,
    exported_at: now,
    learner_alias: "child",
    attempts: attemptList,
    node_status,
    amendments: [],
  };
}

const first = diagnostic.items[0];
const g7Wrong = diagnostic.items.find((item) => item.node_id === "M-G7-RATIONAL-ADD-SUB");
assert(first, "first diagnostic item missing");
assert(g7Wrong, "G7 rational add/sub item missing");

let exported = buildExportData({
  [first.id]: {
    attempt_id: "attempt-ungraded",
    question_id: first.id,
    item_version: first.item_version,
    node_id: first.node_id,
    answer_raw: "answer only",
    answer_normalized: "answer only",
    grading_status: "ungraded",
  },
});
assert(exported.attempts.length === 1, "ungraded raw answer should remain in attempts");
assert(exported.node_status.length === 0, "ungraded raw answer must not create node_status");

exported = buildExportData({
  [g7Wrong.id]: {
    attempt_id: "attempt-wrong",
    question_id: g7Wrong.id,
    item_version: g7Wrong.item_version,
    node_id: g7Wrong.node_id,
    grading_status: "graded",
    answer_raw: "wrong",
    answer_normalized: "wrong",
    result: "wrong",
    score_points: 0,
    max_points: 2,
    error_tag: "general",
    error_tags: ["general"],
    parent_note: "wrong but not skip",
    child_explanation_score_0_to_2: 0,
    next_action: "rollback",
    rollback_candidate_node_ids: g7Wrong.rollback_candidates,
    rollback_candidate_relations: g7Wrong.rollback_candidate_relations,
    blocking_evidence: false,
    manual_override: false,
  },
});
assert(exported.node_status.length === 1, "graded wrong answer should create node_status");
assert(exported.node_status[0].status_code === "C", "ordinary wrong answer should be C, not D");
assert(exported.node_status[0].unverified_prerequisite_node_ids.length > 0, "wrong G7 answer should carry unverified prerequisite ids");

exported = buildExportData({
  [g7Wrong.id]: {
    attempt_id: "attempt-skip",
    question_id: g7Wrong.id,
    item_version: g7Wrong.item_version,
    node_id: g7Wrong.node_id,
    grading_status: "graded",
    answer_raw: "",
    answer_normalized: "",
    result: "wrong",
    score_points: 0,
    max_points: 2,
    error_tag: "general",
    error_tags: ["general"],
    parent_note: "先放一下/跳过",
    child_explanation_score_0_to_2: 0,
    next_action: "rollback",
    rollback_candidate_node_ids: g7Wrong.rollback_candidates,
    rollback_candidate_relations: g7Wrong.rollback_candidate_relations,
    blocking_evidence: true,
    manual_override: false,
  },
});
assert(exported.node_status[0].status_code === "D", "explicit skip/cannot-start should be D");

exported = buildExportData({
  [first.id]: {
    attempt_id: "attempt-correct",
    question_id: first.id,
    item_version: first.item_version,
    node_id: first.node_id,
    grading_status: "graded",
    answer_raw: "681",
    answer_normalized: "681",
    result: "correct",
    score_points: 2,
    max_points: 2,
    error_tag: null,
    error_tags: [],
    parent_note: "clear",
    child_explanation_score_0_to_2: 2,
    next_action: "pass",
    rollback_candidate_node_ids: first.rollback_candidates,
    rollback_candidate_relations: first.rollback_candidate_relations,
    blocking_evidence: false,
    manual_override: false,
  },
});
assert(exported.node_status[0].status_code === "A", "correct explained answer should be A");

console.log("PASS math diagnostic export semantics");
