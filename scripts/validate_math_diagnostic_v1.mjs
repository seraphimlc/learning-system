#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const graphPath = path.join(root, "data/knowledge_graphs/math/math_knowledge_graph_v2.json");
const diagnosticPath = path.join(root, "data/questions/math_diagnostic_v1.json");
const htmlPath = path.join(root, "app/student/math_diagnostic_v1.html");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function assertNonEmptyString(value, label) {
  assert(typeof value === "string" && value.trim().length > 0, `${label} must be a non-empty string`);
}

function assertArray(value, label) {
  assert(Array.isArray(value), `${label} must be an array`);
}

function collectIds(items, label) {
  const seen = new Set();
  for (const item of items) {
    assertNonEmptyString(item.id, `${label}.id`);
    assert(!seen.has(item.id), `duplicate ${label} id: ${item.id}`);
    seen.add(item.id);
  }
  return seen;
}

const graph = readJson(graphPath);
const graphNodeIds = new Set(graph.nodes.map((node) => node.id));
assert(graphNodeIds.size === graph.nodes.length, "math graph node ids must be unique");

const diagnostic = readJson(diagnosticPath);
assertNonEmptyString(diagnostic.diagnostic_id, "diagnostic_id");
assertNonEmptyString(diagnostic.schema_version, "schema_version");
assertNonEmptyString(diagnostic.diagnostic_version, "diagnostic_version");
assert(["draft", "released", "attempted", "archived"].includes(diagnostic.status), "status must be draft/released/attempted/archived");
assertNonEmptyString(diagnostic.title, "title");
assertNonEmptyString(diagnostic.graph_ref?.path, "graph_ref.path");
assert(diagnostic.graph_ref?.version === graph.metadata.version, "graph_ref.version must match graph metadata.version");
assert(diagnostic.graph_ref?.node_count === graph.nodes.length, "graph_ref.node_count must match graph nodes length");
assert(Number.isInteger(diagnostic.total_recommended_minutes), "total_recommended_minutes must be an integer");
assert(diagnostic.total_recommended_minutes <= 60, "diagnostic must fit within 60 minutes");
assertNonEmptyString(diagnostic.source_policy, "source_policy");
assertArray(diagnostic.blocks, "blocks");
assertArray(diagnostic.items, "items");
assert(diagnostic.blocks.length === graph.diagnostic_blueprint.blocks.length, "block count must match graph diagnostic_blueprint");
assert(diagnostic.items.length === graph.diagnostic_blueprint.blocks.reduce((sum, block) => sum + block.items, 0), "item count must match graph diagnostic_blueprint");

const blockIds = collectIds(diagnostic.blocks, "block");
const graphBlueprintByName = new Map(graph.diagnostic_blueprint.blocks.map((block) => [block.name, block]));
for (const block of diagnostic.blocks) {
  assertNonEmptyString(block.name, `block ${block.id}.name`);
  assertNonEmptyString(block.focus, `block ${block.id}.focus`);
  assert(Number.isInteger(block.minutes), `block ${block.id}.minutes`);
  assert(Number.isInteger(block.expected_item_count), `block ${block.id}.expected_item_count`);
  assertArray(block.node_ids, `block ${block.id}.node_ids`);
  const graphBlock = graphBlueprintByName.get(block.name);
  assert(graphBlock, `block ${block.id} name must exist in graph diagnostic_blueprint`);
  assert(block.minutes === graphBlock.minutes, `block ${block.id}.minutes must match graph blueprint`);
  assert(block.expected_item_count === graphBlock.items, `block ${block.id}.expected_item_count must match graph blueprint`);
  for (const nodeId of block.node_ids) {
    assert(graphBlock.nodes.includes(nodeId), `block ${block.id} includes node ${nodeId} not in graph blueprint block`);
  }
}

const questionIds = collectIds(diagnostic.items, "question");
const allowedResultTypes = new Set(["correct", "partial", "wrong", "observe_only"]);
const allowedErrorTags = new Set(Object.keys(graph.schema.error_tags));
const allowedRollbackRelations = new Set(["self_retest", "secondary_node", "prerequisite_chain", "followup_probe"]);
const reasoningMarkers = ["步骤", "过程", "解释", "理由", "检验", "关系", "错因", "设", "列", "画", "规则", "说明", "判断", "单位", "为什么"];
const metaPromptMarkers = ["围绕“", "完成一道", "知识点练习"];

function hasReasoningSignal(question) {
  const text = [question.prompt, question.answer_format, ...(question.solution_steps ?? [])].join(" ");
  return reasoningMarkers.some((marker) => text.includes(marker));
}

function hasMechanicalPrompt(question) {
  return /^计算：[-+()0-9./\s×÷*]+[。?？]?$/.test(question.prompt.trim()) && !hasReasoningSignal(question);
}

for (const question of diagnostic.items) {
  assert(blockIds.has(question.block_id), `${question.id} references unknown block ${question.block_id}`);
  assertNonEmptyString(question.item_version, `${question.id}.item_version`);
  assert(Number.isInteger(question.order), `${question.id}.order`);
  assertNonEmptyString(question.prompt, `${question.id}.prompt`);
  assert(!metaPromptMarkers.some((marker) => question.prompt.includes(marker)), `${question.id}.prompt must not expose generator meta language`);
  assertNonEmptyString(question.answer_format, `${question.id}.answer_format`);
  assert(hasReasoningSignal(question), `${question.id} must require observable reasoning, not only a final answer`);
  assert(!hasMechanicalPrompt(question), `${question.id} must not be mechanical arithmetic without reasoning`);
  assert(question.age_floor === "incoming_grade_7", `${question.id}.age_floor must be incoming_grade_7`);
  assert(question.quality?.review_status === "approved", `${question.id}.quality.review_status must be approved`);
  assert(question.quality?.requires_reasoning === true, `${question.id}.quality.requires_reasoning must be true`);
  assert(question.quality?.no_mechanical_drill === true, `${question.id}.quality.no_mechanical_drill must be true`);
  assertNonEmptyString(question.node_id, `${question.id}.node_id`);
  assert(graphNodeIds.has(question.node_id), `${question.id} references missing node ${question.node_id}`);
  assertArray(question.secondary_node_ids ?? [], `${question.id}.secondary_node_ids`);
  for (const nodeId of question.secondary_node_ids ?? []) {
    assert(graphNodeIds.has(nodeId), `${question.id} secondary reference missing node ${nodeId}`);
  }
  assert(question.node_snapshot?.id === question.node_id, `${question.id}.node_snapshot.id must match node_id`);
  assertNonEmptyString(question.question_type, `${question.id}.question_type`);
  assert(["L1", "L2", "L3", "L4"].includes(question.variant_level), `${question.id}.variant_level must be L1/L2/L3/L4`);
  assertArray(question.rollback_candidates, `${question.id}.rollback_candidates`);
  for (const nodeId of question.rollback_candidates) {
    assert(graphNodeIds.has(nodeId), `${question.id} rollback references missing node ${nodeId}`);
  }
  assertArray(question.rollback_candidate_relations, `${question.id}.rollback_candidate_relations`);
  assert(question.rollback_candidate_relations.length === question.rollback_candidates.length, `${question.id}.rollback_candidate_relations must match rollback_candidates length`);
  for (const relation of question.rollback_candidate_relations) {
    assert(question.rollback_candidates.includes(relation.node_id), `${question.id} has relation for non-candidate ${relation.node_id}`);
    assert(allowedRollbackRelations.has(relation.relation), `${question.id} has invalid rollback relation ${relation.relation}`);
  }
  assertArray(question.target_error_tags, `${question.id}.target_error_tags`);
  assert(question.target_error_tags.length > 0, `${question.id}.target_error_tags cannot be empty`);
  for (const tag of question.target_error_tags) {
    assert(allowedErrorTags.has(tag), `${question.id} uses unknown error tag ${tag}`);
  }
  assertNonEmptyString(question.expected_answer, `${question.id}.expected_answer`);
  assertArray(question.rubric, `${question.id}.rubric`);
  assert(question.rubric.length > 0, `${question.id}.rubric cannot be empty`);
  for (const score of question.rubric) {
    assert(allowedResultTypes.has(score.result), `${question.id} has invalid scoring result ${score.result}`);
    assertNonEmptyString(score.evidence, `${question.id}.scoring.evidence`);
  }
  assertArray(question.solution_steps, `${question.id}.solution_steps`);
  assertNonEmptyString(question.parent_observation, `${question.id}.parent_observation`);
  assert(
    ["diagnostic_generated", "graph_generated", "manual_original", "user_provided_material"].includes(question.source?.type),
    `${question.id}.source.type must be diagnostic_generated/graph_generated/manual_original/user_provided_material`,
  );
}

assert(diagnostic.result_interpretation, "result_interpretation is required");
for (const key of ["A_mastered", "B_unstable", "C_weak", "D_blocked"]) {
  assertNonEmptyString(diagnostic.result_interpretation[key], `result_interpretation.${key}`);
}

const html = fs.readFileSync(htmlPath, "utf8");
const match = html.match(/<script id="diagnostic-data" type="application\/json">([\s\S]*?)<\/script>/);
assert(match, "HTML must embed diagnostic data in script#diagnostic-data");
const embedded = JSON.parse(match[1]);
const embeddedQuestionIds = collectIds(embedded.items, "embedded question");
assert(embedded.diagnostic_id === diagnostic.diagnostic_id, "HTML diagnostic_id must match JSON");
assert(embedded.items.length === diagnostic.items.length, "HTML item count must match JSON");
for (const id of questionIds) {
  assert(embeddedQuestionIds.has(id), `HTML embedded data missing question ${id}`);
}

console.log(`PASS math diagnostic v1 validation: ${diagnostic.items.length} items, ${diagnostic.blocks.length} blocks`);
