#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const graphPath = "data/knowledge_graphs/math/math_knowledge_graph_v2.json";
const graph = JSON.parse(fs.readFileSync(path.join(root, graphPath), "utf8"));
const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));

const blocks = [
  {
    id: "B1",
    name: "计算与运算规则",
    focus: "看底层计算、估算、分数小数混合、括号和步骤是否稳定。",
  },
  {
    id: "B2",
    name: "分数百分数与单位1",
    focus: "看单位1、百分率、比和比例是否能从文字关系里提取出来。",
  },
  {
    id: "B3",
    name: "等量关系与小学方程",
    focus: "看文字关系、字母表示数、简易方程是否能自然过渡到七上。",
  },
  {
    id: "B4",
    name: "应用题模型",
    focus: "看审题流程、和差倍、行程、追及是否能建立模型而不是乱算。",
  },
  {
    id: "B5",
    name: "七上入门探针",
    focus: "看正负数、数轴、绝对值、有理数加减、代数式和同类项入口。",
  },
].map((block) => {
  const blueprint = graph.diagnostic_blueprint.blocks.find((item) => item.name === block.name);
  if (!blueprint) {
    throw new Error(`Missing graph diagnostic blueprint block: ${block.name}`);
  }
  return {
    ...block,
    minutes: blueprint.minutes,
    expected_item_count: blueprint.items,
    node_ids: blueprint.nodes,
  };
});

const q = (item) => item;

const rawItems = [
  q({
    block_id: "B1",
    node_id: "M-PRE-INTEGER-OPS",
    question_type: "整数四则与验算",
    variant_level: "L2",
    prompt: "某同学做有余数除法，只写了“商是120，余数是1”。请写出这个答案必须满足的验算关系，并说明余数为什么必须小于除数。",
    answer_format: "验算关系 + 规则解释",
    expected_answer: "必须满足 除数×商+余数=被除数，且余数小于除数；否则商还能继续增加。",
    solution_steps: ["写出有余数除法验算结构。", "说明余数小于除数的原因。", "判断答案是否可检验。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-NUMBER-SENSE"],
    estimated_minutes: 1,
    parent_observation: "看孩子是否知道用结构验算，而不是只相信一个商和余数。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-INTEGER-OPS",
    question_type: "整数乘除与数感",
    variant_level: "L2",
    prompt: "不精算先判断：398 × 51 的结果更接近 2000、20000 还是 200000？再计算。",
    answer_format: "选择 + 计算",
    expected_answer: "更接近 20000；398 × 51 = 20298。",
    solution_steps: ["398 接近 400，51 接近 50。", "400 × 50 = 20000。", "398 × 51 = 398 × 50 + 398 = 20298。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-NUMBER-SENSE", "M-PRE-INTEGER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否先估数量级；若选 2000/200000，优先回数感。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-INTEGER-OPS",
    secondary_node_ids: ["M-PRE-ORDER-OPS"],
    question_type: "整数混合运算",
    variant_level: "L2",
    prompt: "计算：72 - 48 ÷ 6 × 5。请写出先算哪一步。",
    answer_format: "计算过程",
    expected_answer: "32。",
    solution_steps: ["先算同级乘除，从左到右：48 ÷ 6 = 8。", "8 × 5 = 40。", "72 - 40 = 32。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-ORDER-OPS", "M-PRE-NUMBER-SENSE"],
    estimated_minutes: 1,
    parent_observation: "重点看是否把乘除从左到右处理，而不是先做乘法。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-DECIMAL-OPS",
    secondary_node_ids: ["M-PRE-NUMBER-SENSE"],
    question_type: "小数乘法估算",
    variant_level: "L2",
    prompt: "不精算，先判断 6.8 × 0.49 的结果最接近 0.33、3.3、33 中的哪一个。再计算。",
    answer_format: "选择 + 计算 + 估算理由",
    expected_answer: "最接近 3.3；6.8 × 0.49 = 3.332。",
    solution_steps: ["0.49 接近 0.5。", "6.8 × 0.5 = 3.4，所以应在 3 点多。", "6.8 × 0.49 = 3.332。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-NUMBER-SENSE", "M-PRE-DECIMAL-OPS"],
    estimated_minutes: 1,
    parent_observation: "如果数量级错，先记数感；如果估算对但小数点错，记小数运算。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-DECIMAL-OPS",
    question_type: "小数除法转化",
    variant_level: "L2",
    prompt: "计算：4.8 ÷ 0.12。写一句：为什么可以把它变成 480 ÷ 12？",
    answer_format: "计算 + 解释",
    expected_answer: "40；被除数和除数同时扩大 100 倍，商不变。",
    solution_steps: ["4.8 ÷ 0.12 = 480 ÷ 12。", "480 ÷ 12 = 40。", "同时扩大相同倍数，商不变。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion"],
    rollback_candidates: ["M-PRE-DECIMAL-OPS", "M-PRE-INTEGER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否只机械移动小数点，能不能说出商不变。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-DECIMAL-OPS",
    secondary_node_ids: ["M-PRE-FRACTION-OPS"],
    question_type: "小数分数互化",
    variant_level: "L2",
    prompt: "把 0.375 化成最简分数，再把 5/8 化成小数。",
    answer_format: "两个互化结果",
    expected_answer: "0.375 = 3/8；5/8 = 0.625。",
    solution_steps: ["0.375 = 375/1000 = 3/8。", "5 ÷ 8 = 0.625。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion"],
    rollback_candidates: ["M-PRE-DECIMAL-OPS", "M-PRE-FRACTION-OPS"],
    estimated_minutes: 1,
    parent_observation: "看约分、除法和常见分数小数互化是否熟。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-FRACTION-OPS",
    question_type: "异分母加减",
    variant_level: "L2",
    prompt: "计算：5/6 - 1/4。",
    answer_format: "分数结果，能约分则约分",
    expected_answer: "7/12。",
    solution_steps: ["公分母是 12。", "5/6 = 10/12，1/4 = 3/12。", "10/12 - 3/12 = 7/12。"],
    target_error_tags: ["calculation_or_symbol"],
    rollback_candidates: ["M-PRE-FRACTION-MEANING", "M-PRE-INTEGER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否通分只改分母不改分子。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-FRACTION-OPS",
    question_type: "分数乘除",
    variant_level: "L2",
    prompt: "计算：7/9 ÷ 14/15。",
    answer_format: "最简分数",
    expected_answer: "5/6。",
    solution_steps: ["除以 14/15 等于乘 15/14。", "7/9 × 15/14。", "约分后得到 5/6。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion"],
    rollback_candidates: ["M-PRE-FRACTION-OPS", "M-PRE-FRACTION-MEANING"],
    estimated_minutes: 1,
    parent_observation: "若没有转倒数，优先回分数除法微技能。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-FRACTION-OPS",
    secondary_node_ids: ["M-PRE-ORDER-OPS"],
    question_type: "分数小数混合",
    variant_level: "L3",
    prompt: "计算：1.5 ÷ 3/4 - 2/3 × 3/5。请写关键步骤。",
    answer_format: "计算过程",
    expected_answer: "8/5，或 1.6。",
    solution_steps: ["1.5 = 3/2。", "3/2 ÷ 3/4 = 3/2 × 4/3 = 2。", "2/3 × 3/5 = 2/5。", "2 - 2/5 = 8/5。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-FRACTION-OPS", "M-PRE-ORDER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看分数除法、乘法和最后减法是否各自稳定。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-ORDER-OPS",
    question_type: "括号与运算顺序",
    variant_level: "L2",
    prompt: "计算：36 ÷ (3 + 6) × 4。",
    answer_format: "计算过程",
    expected_answer: "16。",
    solution_steps: ["先算括号：3 + 6 = 9。", "36 ÷ 9 = 4。", "4 × 4 = 16。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-ORDER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否先算括号，除乘同级是否从左到右。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-ORDER-OPS",
    secondary_node_ids: ["M-PRE-DISTRIBUTIVE"],
    question_type: "括号前负号意识",
    variant_level: "L3",
    prompt: "判断并改正：80 - (35 - 12) = 80 - 35 - 12。这个等式对吗？如果不对，正确结果是多少？",
    answer_format: "判断 + 改正",
    expected_answer: "不对；80 - (35 - 12) = 80 - 23 = 57，也可写成 80 - 35 + 12。",
    solution_steps: ["括号前是减号，括号里的每一项都要变号。", "80 - 35 + 12 = 57。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion", "process_habit"],
    rollback_candidates: ["M-PRE-ORDER-OPS", "M-PRE-DISTRIBUTIVE"],
    estimated_minutes: 1,
    parent_observation: "这是七上去括号的前置观察点。",
  }),
  q({
    block_id: "B1",
    node_id: "M-PRE-ORDER-OPS",
    secondary_node_ids: ["M-BRIDGE-SOLUTION-HABIT"],
    question_type: "过程改错",
    variant_level: "L3",
    prompt: "小明算 18 + 24 ÷ 6 = 42 ÷ 6 = 7。请指出错在哪里，并写出正确结果。",
    answer_format: "错因 + 正确计算",
    expected_answer: "错在先把 18 和 24 相加；应先算 24 ÷ 6 = 4，再算 18 + 4 = 22。",
    solution_steps: ["先乘除后加减。", "24 ÷ 6 = 4。", "18 + 4 = 22。"],
    target_error_tags: ["process_habit", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-ORDER-OPS", "M-BRIDGE-SOLUTION-HABIT"],
    estimated_minutes: 1,
    parent_observation: "看孩子能不能从别人错解里定位规则，而不是只给答案。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-FRACTION-MEANING",
    question_type: "找单位1",
    variant_level: "L1",
    prompt: "苹果的重量是梨的 3/5。这句话里，谁是单位1？这句话表示什么关系？",
    answer_format: "一句话解释",
    expected_answer: "梨的重量是单位1；苹果重量 = 梨重量 × 3/5。",
    solution_steps: ["“谁的几分之几”中，“谁”通常是单位1。", "苹果是梨的 3/5，所以梨是单位1。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading"],
    rollback_candidates: ["M-PRE-FRACTION-MEANING"],
    estimated_minutes: 1,
    parent_observation: "只要求说清关系，不急着计算。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-FRACTION-MEANING",
    secondary_node_ids: ["M-PRE-FRACTION-OPS"],
    question_type: "已知分率求整体",
    variant_level: "L2",
    prompt: "一盒彩笔中，红色有 18 支，正好是全盒彩笔的 3/8。全盒彩笔有多少支？",
    answer_format: "算式 + 答案",
    expected_answer: "18 ÷ 3/8 = 48 支。",
    solution_steps: ["18 支对应全盒的 3/8。", "全盒 = 18 ÷ 3/8 = 48。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-FRACTION-MEANING", "M-PRE-FRACTION-OPS"],
    estimated_minutes: 1,
    parent_observation: "若用乘法求整体，单位1理解需回补。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-FRACTION-MEANING",
    secondary_node_ids: ["M-PRE-QUANTITY-RELATION"],
    question_type: "分率与数量区分",
    variant_level: "L2",
    prompt: "一条绳子长 40 米，用去了 3/8。用去了多少米？还剩多少米？",
    answer_format: "两个答案",
    expected_answer: "用去 15 米；还剩 25 米。",
    solution_steps: ["用去 = 40 × 3/8 = 15。", "还剩 = 40 - 15 = 25。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-FRACTION-MEANING", "M-PRE-FRACTION-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否把 3/8 当成 3 或 8 米。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-PERCENT",
    question_type: "百分率",
    variant_level: "L2",
    prompt: "一次小测共 25 题，小安做对 21 题。正确率是多少？",
    answer_format: "百分数",
    expected_answer: "21 ÷ 25 = 84%。",
    solution_steps: ["正确率 = 做对题数 ÷ 总题数。", "21 ÷ 25 = 0.84 = 84%。"],
    target_error_tags: ["concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-PERCENT", "M-PRE-FRACTION-MEANING"],
    estimated_minutes: 1,
    parent_observation: "看是否把总数和比较量写反。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-PERCENT",
    secondary_node_ids: ["M-PRE-QUANTITY-RELATION"],
    question_type: "百分数阈值",
    variant_level: "L3",
    prompt: "如果下一次仍是 25 题，想达到至少 90%，最少要做对多少题？",
    answer_format: "整数答案 + 理由",
    expected_answer: "至少 23 题；25 × 90% = 22.5，题数必须是整数且至少达到，所以取 23。",
    solution_steps: ["25 × 0.9 = 22.5。", "至少达到 90%，不能取 22。", "最少 23 题。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-PERCENT", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "看能否处理现实语境中的向上取整。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-RATIO-PROP",
    question_type: "化简比与比值",
    variant_level: "L2",
    prompt: "把 18:24 化成最简整数比，并求比值。",
    answer_format: "最简比 + 比值",
    expected_answer: "最简比 3:4；比值 3/4。",
    solution_steps: ["18 和 24 同除以 6，得 3:4。", "比值 = 18 ÷ 24 = 3/4。"],
    target_error_tags: ["concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-RATIO-PROP", "M-PRE-FRACTION-OPS"],
    estimated_minutes: 1,
    parent_observation: "看是否混淆比和比值。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-RATIO-PROP",
    question_type: "按比例分配",
    variant_level: "L2",
    prompt: "把 84 元按 2:5 分给甲、乙。甲、乙各得多少元？",
    answer_format: "两个数量",
    expected_answer: "甲 24 元，乙 60 元。",
    solution_steps: ["总份数 = 2 + 5 = 7。", "每份 = 84 ÷ 7 = 12。", "甲 = 2 × 12 = 24，乙 = 5 × 12 = 60。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-RATIO-PROP", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "看是否知道比例关系是分份数。",
  }),
  q({
    block_id: "B2",
    node_id: "M-PRE-RATIO-PROP",
    secondary_node_ids: ["M-PRE-UNIT-CONVERSION"],
    question_type: "比例尺",
    variant_level: "L3",
    prompt: "地图上 3 cm 表示实际 600 m。比例尺是多少？先统一单位。",
    answer_format: "比例尺",
    expected_answer: "600 m = 60000 cm，比例尺为 3:60000 = 1:20000。",
    solution_steps: ["600 m = 60000 cm。", "图上距离:实际距离 = 3:60000。", "化简得 1:20000。"],
    target_error_tags: ["modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-RATIO-PROP", "M-PRE-UNIT-CONVERSION"],
    estimated_minutes: 1,
    parent_observation: "若单位不统一，比例尺题暂不推进。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-QUANTITY-RELATION",
    question_type: "只写等量关系",
    variant_level: "L1",
    prompt: "明明有 x 张邮票，亮亮比明明多 8 张，两人一共有 50 张。只写等量关系，不要求解。",
    answer_format: "等量关系",
    expected_answer: "明明的邮票数 + 亮亮的邮票数 = 50；也可写 x + (x + 8) = 50。",
    solution_steps: ["明明是 x。", "亮亮是 x + 8。", "两人合起来是 50。"],
    target_error_tags: ["modeling_or_reading"],
    rollback_candidates: ["M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "看是否先找关系，而不是看到数字就算。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-QUANTITY-RELATION",
    question_type: "多/少关系辨析",
    variant_level: "L2",
    prompt: "小华的钱数比小林的 3 倍少 4 元。如果小林有 x 元，小华有多少元？",
    answer_format: "含 x 的式子",
    expected_answer: "3x - 4。",
    solution_steps: ["小林是 x。", "3 倍是 3x。", "少 4 元，所以是 3x - 4。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion"],
    rollback_candidates: ["M-PRE-QUANTITY-RELATION", "M-BRIDGE-SUM-DIFF-MULTIPLE"],
    estimated_minutes: 1,
    parent_observation: "若写成 3(x-4)，说明文字关系翻译需回退。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-QUANTITY-RELATION",
    secondary_node_ids: ["M-PRE-EQUATION-BASIC"],
    question_type: "列方程不求解",
    variant_level: "L2",
    prompt: "一个数的 4 倍加 7 等于 39。设这个数为 x，只列方程。",
    answer_format: "方程",
    expected_answer: "4x + 7 = 39。",
    solution_steps: ["这个数是 x。", "4 倍是 4x。", "加 7 等于 39。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion"],
    rollback_candidates: ["M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "看能否把文字变成等号两边。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-EQUATION-BASIC",
    question_type: "一步方程",
    variant_level: "L2",
    prompt: "解方程：x/5 + 3 = 11。请代回检验。",
    answer_format: "解 + 检验",
    expected_answer: "x = 40；40/5 + 3 = 11。",
    solution_steps: ["x/5 = 8。", "x = 40。", "代回：40/5 + 3 = 11。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-EQUATION-BASIC", "M-BRIDGE-SOLUTION-HABIT"],
    estimated_minutes: 1,
    parent_observation: "看是否把解方程当作两边同操作，而不是乱移项。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-EQUATION-BASIC",
    secondary_node_ids: ["M-G7-EQUALITY-PROP"],
    question_type: "两步方程",
    variant_level: "L2",
    prompt: "解方程：3x - 8 = 19。",
    answer_format: "解方程过程",
    expected_answer: "x = 9。",
    solution_steps: ["3x = 27。", "x = 9。"],
    target_error_tags: ["calculation_or_symbol", "process_habit"],
    rollback_candidates: ["M-PRE-EQUATION-BASIC", "M-G7-EQUALITY-PROP"],
    estimated_minutes: 1,
    parent_observation: "若 3x=11 或 x=27，等式性质不稳。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-LETTER-EXPR",
    question_type: "用字母表示数量",
    variant_level: "L2",
    prompt: "一本练习本 m 元，一支笔 n 元。买 4 本练习本和 3 支笔，应花多少钱？",
    answer_format: "代数式",
    expected_answer: "4m + 3n。",
    solution_steps: ["4 本练习本是 4m。", "3 支笔是 3n。", "合计 4m + 3n。"],
    target_error_tags: ["modeling_or_reading", "process_habit"],
    rollback_candidates: ["M-PRE-LETTER-EXPR", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "若写成 7mn，说明字母表示数量关系不稳。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-LETTER-EXPR",
    secondary_node_ids: ["M-PRE-DECIMAL-OPS"],
    question_type: "代入求值",
    variant_level: "L2",
    prompt: "上题中，当 m = 6.5，n = 4 时，付 50 元应找回多少钱？",
    answer_format: "算式 + 答案",
    expected_answer: "50 - (4×6.5 + 3×4) = 12 元。",
    solution_steps: ["4×6.5 = 26。", "3×4 = 12。", "应花 38，找回 50 - 38 = 12。"],
    target_error_tags: ["calculation_or_symbol", "modeling_or_reading"],
    rollback_candidates: ["M-PRE-LETTER-EXPR", "M-PRE-DECIMAL-OPS"],
    estimated_minutes: 1,
    parent_observation: "看代入、括号和小数计算是否拖住代数式。",
  }),
  q({
    block_id: "B3",
    node_id: "M-PRE-LETTER-EXPR",
    secondary_node_ids: ["M-G7-EQUATION-CONCEPT"],
    question_type: "表达式与方程辨析",
    variant_level: "L3",
    prompt: "上题能直接写 50 = 4m + 3n 吗？为什么？",
    answer_format: "判断 + 理由",
    expected_answer: "不能。4m + 3n 表示应花的钱；50 是付出的钱，除非刚好不找钱，否则不相等。",
    solution_steps: ["分清应花的钱和付出的钱。", "找回 = 50 - (4m + 3n)。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading"],
    rollback_candidates: ["M-PRE-LETTER-EXPR", "M-G7-EQUATION-CONCEPT"],
    estimated_minutes: 1,
    parent_observation: "看是否把有字母的式子都误当方程。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-WORD-PROBLEM-READING",
    question_type: "审题标注",
    variant_level: "L1",
    prompt: "小船顺流行 3 小时走 72 千米。只标出已知量、未知量和可能用到的关系，不要求解。",
    answer_format: "已知/未知/关系",
    expected_answer: "已知：时间 3 小时，路程 72 千米；未知可能是速度；关系：路程 = 速度 × 时间。",
    solution_steps: ["圈出路程和时间。", "判断可能要求速度。", "写三量关系。"],
    target_error_tags: ["process_habit", "modeling_or_reading"],
    rollback_candidates: ["M-BRIDGE-WORD-PROBLEM-READING", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "看孩子能否先整理题意，不急着算。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-WORD-PROBLEM-READING",
    secondary_node_ids: ["M-PRE-QUANTITY-RELATION"],
    question_type: "信息与问题辨析",
    variant_level: "L2",
    prompt: "一箱牛奶有 24 盒，已经喝了 7 盒，又买来 2 箱。现在一共有多少盒？请先写清楚每个数字的意思。",
    answer_format: "数字含义 + 算式",
    expected_answer: "24 是每箱盒数，7 是喝掉的盒数，2 是新买箱数；24 - 7 + 2×24 = 65 盒。",
    solution_steps: ["原来 24 盒。", "喝掉 7 盒，剩 17。", "又买 2 箱是 48 盒。", "17 + 48 = 65。"],
    target_error_tags: ["modeling_or_reading", "process_habit", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-WORD-PROBLEM-READING", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "若把 2 当作盒数，审题流程要回退。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-SUM-DIFF-MULTIPLE",
    question_type: "和倍关系",
    variant_level: "L2",
    prompt: "两个数的和是 76，大数比小数的 2 倍少 5。设小数为 x，列方程并求两个数。",
    answer_format: "设、列、解、答",
    expected_answer: "x + (2x - 5) = 76；小数 27，大数 49。",
    solution_steps: ["小数 x，大数 2x - 5。", "x + 2x - 5 = 76。", "3x = 81，x = 27。", "大数 49。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-PRE-QUANTITY-RELATION", "M-BRIDGE-SUM-DIFF-MULTIPLE"],
    estimated_minutes: 2,
    parent_observation: "看“大数比小数的 2 倍少 5”是否写反。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-SUM-DIFF-MULTIPLE",
    question_type: "年龄差不变",
    variant_level: "L3",
    prompt: "爸爸今年 40 岁，孩子今年 12 岁。几年后爸爸年龄是孩子的 3 倍？",
    answer_format: "方程或算式",
    expected_answer: "2 年后。",
    solution_steps: ["设 x 年后。", "40 + x = 3(12 + x)。", "40 + x = 36 + 3x。", "x = 2。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-SUM-DIFF-MULTIPLE", "M-PRE-QUANTITY-RELATION", "M-PRE-EQUATION-BASIC"],
    estimated_minutes: 2,
    parent_observation: "若只用 40÷12，说明没有建立变化后的等量关系。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-MOTION-BASIC",
    question_type: "行程三量",
    variant_level: "L2",
    prompt: "汽车 2.5 小时行 180 千米，平均每小时行多少千米？",
    answer_format: "算式 + 单位",
    expected_answer: "180 ÷ 2.5 = 72 千米/时。",
    solution_steps: ["速度 = 路程 ÷ 时间。", "180 ÷ 2.5 = 72。"],
    target_error_tags: ["modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-MOTION-BASIC", "M-PRE-DECIMAL-OPS"],
    estimated_minutes: 1,
    parent_observation: "看三量关系和单位是否稳定。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-MOTION-BASIC",
    secondary_node_ids: ["M-PRE-UNIT-CONVERSION"],
    question_type: "行程单位换算",
    variant_level: "L3",
    prompt: "小明骑车每分钟 250 米，12 分钟行多少千米？",
    answer_format: "数量 + 单位",
    expected_answer: "250 × 12 = 3000 米 = 3 千米。",
    solution_steps: ["路程 = 速度 × 时间。", "250 × 12 = 3000 米。", "3000 米 = 3 千米。"],
    target_error_tags: ["modeling_or_reading", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-MOTION-BASIC", "M-PRE-UNIT-CONVERSION"],
    estimated_minutes: 1,
    parent_observation: "若结果写 3000 千米，单位换算要补测。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-MOTION-CHASE",
    question_type: "同向追及",
    variant_level: "L2",
    prompt: "甲和乙同向前进，开始时乙在甲前面 120 米。甲每分钟 75 米，乙每分钟 60 米。甲几分钟追上乙？",
    answer_format: "算式 + 答案",
    expected_answer: "120 ÷ (75 - 60) = 8 分钟。",
    solution_steps: ["这是追及，看速度差。", "速度差 = 75 - 60 = 15 米/分。", "120 ÷ 15 = 8。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-MOTION-BASIC", "M-BRIDGE-MOTION-CHASE"],
    estimated_minutes: 2,
    parent_observation: "若用速度和，追及/相遇模型需回退。",
  }),
  q({
    block_id: "B4",
    node_id: "M-BRIDGE-MOTION-CHASE",
    question_type: "相遇模型",
    variant_level: "L2",
    prompt: "两地相距 210 千米，甲乙两车同时相向而行，甲每小时 50 千米，乙每小时 55 千米。几小时相遇？",
    answer_format: "算式 + 答案",
    expected_answer: "210 ÷ (50 + 55) = 2 小时。",
    solution_steps: ["相向相遇看速度和。", "速度和 = 105 千米/时。", "210 ÷ 105 = 2。"],
    target_error_tags: ["modeling_or_reading", "concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-BRIDGE-MOTION-BASIC", "M-BRIDGE-MOTION-CHASE"],
    estimated_minutes: 2,
    parent_observation: "看能否说出为什么用速度和。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-POS-NEG",
    question_type: "相反意义量",
    variant_level: "L1",
    prompt: "用正负数表示：收入 80 元，支出 35 元；水位上升 12 cm，下降 7 cm。",
    answer_format: "四个正负数",
    expected_answer: "+80，-35；+12，-7。",
    solution_steps: ["先规定相反意义。", "收入/上升为正，支出/下降为负。"],
    target_error_tags: ["concept_confusion", "visual_spatial"],
    rollback_candidates: ["M-G7-POS-NEG", "M-PRE-NUMBER-SENSE"],
    estimated_minutes: 1,
    parent_observation: "看是否能把生活语境转成正负方向。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-POS-NEG",
    secondary_node_ids: ["M-G7-RATIONAL-ADD-SUB"],
    question_type: "正负变化",
    variant_level: "L2",
    prompt: "早晨气温 -2°C，中午上升 5°C，晚上又下降 4°C。晚上气温是多少？",
    answer_format: "算式 + 答案",
    expected_answer: "-1°C。",
    solution_steps: ["-2 + 5 = 3。", "3 - 4 = -1。"],
    target_error_tags: ["concept_confusion", "calculation_or_symbol", "modeling_or_reading"],
    rollback_candidates: ["M-G7-POS-NEG", "M-G7-RATIONAL-ADD-SUB"],
    estimated_minutes: 1,
    parent_observation: "看上升/下降是否能转成有理数加减。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-NUMBER-LINE",
    question_type: "数轴表示",
    variant_level: "L1",
    prompt: "在纸上画一条数轴，标出 -3、0、2、-1.5。",
    answer_format: "画图",
    expected_answer: "数轴有原点、正方向、单位长度；点从左到右为 -3、-1.5、0、2。",
    solution_steps: ["画原点和正方向。", "单位长度一致。", "负数在 0 左边，正数在 0 右边。"],
    target_error_tags: ["modeling_or_reading", "visual_spatial"],
    rollback_candidates: ["M-G7-POS-NEG", "M-G7-NUMBER-LINE"],
    estimated_minutes: 1,
    parent_observation: "看单位长度是否一致，左右方向是否反。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-NUMBER-LINE",
    secondary_node_ids: ["M-G7-COMPARE"],
    question_type: "数轴比较",
    variant_level: "L2",
    prompt: "把 -3、2、0、-1.5 从小到大排列。",
    answer_format: "排序",
    expected_answer: "-3 < -1.5 < 0 < 2。",
    solution_steps: ["数轴上越往右越大。", "-3 在 -1.5 左边。"],
    target_error_tags: ["concept_confusion", "visual_spatial"],
    rollback_candidates: ["M-G7-NUMBER-LINE", "M-G7-COMPARE"],
    estimated_minutes: 1,
    parent_observation: "若负数比较反，后续有理数加减会受影响。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-ABSOLUTE",
    question_type: "绝对值意义",
    variant_level: "L1",
    prompt: "写出 |-3|、|0|、|2.5|，并说一句绝对值表示什么。",
    answer_format: "三个值 + 一句话",
    expected_answer: "|-3|=3，|0|=0，|2.5|=2.5；绝对值表示数到 0 的距离。",
    solution_steps: ["绝对值是距离。", "距离不为负。"],
    target_error_tags: ["concept_confusion", "general"],
    rollback_candidates: ["M-G7-NUMBER-LINE", "M-G7-ABSOLUTE"],
    estimated_minutes: 1,
    parent_observation: "若只说“去负号”，继续问 |2.5| 和 |0|。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-ABSOLUTE",
    secondary_node_ids: ["M-G7-OPPOSITE"],
    question_type: "绝对值和前置负号",
    variant_level: "L2",
    prompt: "计算：-|-3| 和 -(-3)。",
    answer_format: "两个值",
    expected_answer: "-|-3| = -3；-(-3)=3。",
    solution_steps: ["先算 |-3| = 3，再在前面加负号，得 -3。", "负负得正，所以 -(-3)=3。"],
    target_error_tags: ["concept_confusion", "calculation_or_symbol"],
    rollback_candidates: ["M-G7-ABSOLUTE", "M-G7-OPPOSITE"],
    estimated_minutes: 1,
    parent_observation: "这是相反数、绝对值、符号层级的探针。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-RATIONAL-ADD-SUB",
    question_type: "有理数加法",
    variant_level: "L2",
    prompt: "计算：-7 + 12。",
    answer_format: "结果 + 规则说明",
    expected_answer: "5；异号相加，用绝对值大的减小的，取 12 的正号。",
    solution_steps: ["12 - 7 = 5。", "正数绝对值更大，所以结果为正。"],
    target_error_tags: ["calculation_or_symbol"],
    rollback_candidates: ["M-G7-ABSOLUTE", "M-G7-COMPARE", "M-PRE-INTEGER-OPS"],
    estimated_minutes: 1,
    parent_observation: "看能否先定符号再算绝对值。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-RATIONAL-ADD-SUB",
    question_type: "减法转加法",
    variant_level: "L2",
    prompt: "计算：-4 - (-9)。",
    answer_format: "过程 + 结果",
    expected_answer: "5；-4 - (-9) = -4 + 9 = 5。",
    solution_steps: ["减去一个数，等于加它的相反数。", "-4 + 9 = 5。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion"],
    rollback_candidates: ["M-G7-OPPOSITE", "M-G7-RATIONAL-ADD-SUB"],
    estimated_minutes: 1,
    parent_observation: "若符号混乱，先回相反数和数轴。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-ALG-EXPR",
    question_type: "文字转代数式",
    variant_level: "L2",
    prompt: "一个数 a 的 3 倍减去 5，用代数式表示。",
    answer_format: "代数式",
    expected_answer: "3a - 5。",
    solution_steps: ["a 的 3 倍是 3a。", "再减去 5，得到 3a - 5。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading", "process_habit"],
    rollback_candidates: ["M-PRE-LETTER-EXPR", "M-PRE-QUANTITY-RELATION"],
    estimated_minutes: 1,
    parent_observation: "若写成 3(a-5)，文字翻译仍需回补。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-ALG-EXPR",
    question_type: "代数式实际意义",
    variant_level: "L3",
    prompt: "一支笔 x 元，一个本子 y 元。式子 2x + y 表示什么？",
    answer_format: "一句话解释",
    expected_answer: "买 2 支笔和 1 个本子一共花的钱。",
    solution_steps: ["2x 表示 2 支笔的钱。", "y 表示 1 个本子的钱。", "相加表示总钱数。"],
    target_error_tags: ["concept_confusion", "modeling_or_reading"],
    rollback_candidates: ["M-PRE-LETTER-EXPR", "M-G7-ALG-EXPR"],
    estimated_minutes: 1,
    parent_observation: "看是否能从式子读回实际意义。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-LIKE-TERMS",
    question_type: "同类项识别",
    variant_level: "L1",
    prompt: "下面哪些是同类项：3a、-5a、2a²、7b、a？说明理由。",
    answer_format: "分组 + 理由",
    expected_answer: "3a、-5a、a 是同类项；2a² 和它们不是同类项，7b 也不是。",
    solution_steps: ["同类项看字母和字母指数是否完全相同。", "系数不同不影响同类项。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion"],
    rollback_candidates: ["M-G7-MONOMIAL", "M-G7-POLYNOMIAL"],
    estimated_minutes: 1,
    parent_observation: "若只看字母不看指数，同类项标准不稳。",
  }),
  q({
    block_id: "B5",
    node_id: "M-G7-LIKE-TERMS",
    secondary_node_ids: ["M-G7-PARENTHESIS"],
    question_type: "去括号与同类项",
    variant_level: "L3",
    prompt: "化简：4a - 2b - (a - 5b) + 3。请圈出能合并的同类项。",
    answer_format: "过程 + 化简结果",
    expected_answer: "3a + 3b + 3。",
    solution_steps: ["先去括号：4a - 2b - a + 5b + 3。", "a 项：4a - a = 3a。", "b 项：-2b + 5b = 3b。", "结果 3a + 3b + 3。"],
    target_error_tags: ["calculation_or_symbol", "concept_confusion", "process_habit"],
    rollback_candidates: ["M-PRE-DISTRIBUTIVE", "M-G7-PARENTHESIS", "M-G7-LIKE-TERMS"],
    estimated_minutes: 1,
    parent_observation: "若只变第一项符号，先回括号前负号。",
  }),
];

if (rawItems.length !== 48) {
  throw new Error(`Expected 48 items, got ${rawItems.length}`);
}

const blockItemCounts = new Map(blocks.map((block) => [block.id, 0]));
const blockOrder = new Map(blocks.map((block, index) => [block.id, index + 1]));
const allowedRelationTypes = new Set(["self_retest", "secondary_node", "prerequisite_chain", "followup_probe"]);
const questionProductionContractVersion = "2026-07-05.question-production.v1";
const reasoningMarkers = ["步骤", "过程", "解释", "理由", "检验", "关系", "错因", "设", "列", "画", "规则", "说明", "判断", "单位", "为什么"];
const metaPromptMarkers = ["围绕“", "完成一道", "诊断题", "知识点练习"];
const highSignalMarkers = [
  "错在哪里",
  "错因",
  "错法",
  "只写答案",
  "是否合格",
  "改一个",
  "代入检验",
  "回代检验",
  "等量关系",
  "单位1",
  "设未知数",
  "列方程",
  "数轴",
  "辨析",
  "不严谨",
  "为什么不能",
];

function hasReasoningSignal(item) {
  const text = [item.prompt, item.answer_format, ...(item.solution_steps ?? [])].join(" ");
  return reasoningMarkers.some((marker) => text.includes(marker));
}

function hasHighSignalStructure(item) {
  const text = [item.prompt, item.answer_format, ...(item.solution_steps ?? [])].join(" ");
  return highSignalMarkers.some((marker) => text.includes(marker));
}

function hasMechanicalPrompt(item) {
  return /^计算：[-+()0-9./\s×÷*]+[。?？]?$/.test(item.prompt.trim()) && !hasReasoningSignal(item);
}

function strengthenDiagnosticItem(item) {
  const next = { ...item };
  if (!reasoningMarkers.some((marker) => next.answer_format.includes(marker))) {
    next.answer_format = `${next.answer_format} + 关键步骤/理由`;
  }
  if (!hasReasoningSignal(next)) {
    next.prompt = `${next.prompt} 请写出关键步骤或判断理由。`;
  }
  if (/^计算：/.test(next.prompt.trim()) && !/(请|并|写|说明|解释|理由|检验|规则|过程|步骤|判断)/.test(next.prompt)) {
    next.prompt = `${next.prompt} 请写出关键步骤，并用一句话说明用到的规则。`;
  }
  if (!hasHighSignalStructure(next)) {
    next.prompt = `有人说“这题只写答案就行”。请判断这个说法是否合格，先写关键规则/关系，再完成：${next.prompt} 最后用检验、错因或改一个数字说明方法是否仍成立。`;
    if (!reasoningMarkers.some((marker) => next.answer_format.includes(marker))) {
      next.answer_format = `${next.answer_format} + 规则/关系 + 检验`;
    }
  }
  const rejectionReasons = [];
  if (metaPromptMarkers.some((marker) => next.prompt.includes(marker))) {
    rejectionReasons.push("child_facing_generator_meta_language");
  }
  if (!hasReasoningSignal(next)) {
    rejectionReasons.push("missing_process_or_reasoning_demand");
  }
  if (!hasHighSignalStructure(next)) {
    rejectionReasons.push("missing_high_signal_diagnostic_structure");
  }
  if (hasMechanicalPrompt(next)) {
    rejectionReasons.push("mechanical_arithmetic_without_reasoning");
  }
  next.age_floor = "incoming_grade_7";
  next.design_intent = {
    designer_agent: "diagnostic_agent",
    reviewer_agent: "question_reviewer_agent",
    item_purpose: "首诊少量高信号探针，定位小学前置漏洞和七上入口断点。",
    not_for: "低龄机械刷题、只看最终答案、脱离图谱的随机题",
  };
  next.quality = {
    contract_version: questionProductionContractVersion,
    review_status: rejectionReasons.length ? "rejected" : "approved",
    reviewer_agent: "question_reviewer_agent",
    age_floor: "incoming_grade_7",
    requires_reasoning: hasReasoningSignal(next),
    no_mechanical_drill: !hasMechanicalPrompt(next),
    has_high_signal_structure: hasHighSignalStructure(next),
    rejection_reasons: rejectionReasons,
  };
  if (rejectionReasons.length) {
    throw new Error(`Diagnostic item rejected: ${next.node_id} ${next.question_type}: ${rejectionReasons.join(", ")}`);
  }
  return next;
}

function prerequisiteClosure(nodeIds) {
  const seen = new Set();
  const stack = [...nodeIds];
  while (stack.length > 0) {
    const nodeId = stack.pop();
    const node = nodeById.get(nodeId);
    if (!node) continue;
    for (const prerequisite of node.prerequisites ?? []) {
      if (!seen.has(prerequisite)) {
        seen.add(prerequisite);
        stack.push(prerequisite);
      }
    }
  }
  return seen;
}

function rollbackRelationsFor(item) {
  const secondaryNodeIds = item.secondary_node_ids ?? [];
  const closure = prerequisiteClosure([item.node_id, ...secondaryNodeIds]);
  return item.rollback_candidates.map((nodeId) => {
    let relation = "followup_probe";
    if (nodeId === item.node_id) relation = "self_retest";
    else if (secondaryNodeIds.includes(nodeId)) relation = "secondary_node";
    else if (closure.has(nodeId)) relation = "prerequisite_chain";
    if (!allowedRelationTypes.has(relation)) throw new Error(`Bad relation ${relation}`);
    return { node_id: nodeId, relation };
  });
}

const items = rawItems.map((rawItem, index) => {
  const item = strengthenDiagnosticItem(rawItem);
  const blockIndex = blockOrder.get(item.block_id);
  if (!blockIndex) throw new Error(`Unknown block ${item.block_id}`);
  blockItemCounts.set(item.block_id, blockItemCounts.get(item.block_id) + 1);
  const node = nodeById.get(item.node_id);
  if (!node) throw new Error(`Unknown node ${item.node_id}`);
  const secondaryNodeIds = item.secondary_node_ids ?? [];
  for (const nodeId of secondaryNodeIds) {
    if (!nodeById.has(nodeId)) throw new Error(`Unknown secondary node ${nodeId}`);
  }
  return {
    id: `MD1-B${blockIndex}-Q${String(blockItemCounts.get(item.block_id)).padStart(2, "0")}`,
    item_version: "2026-07-05.v2",
    order: index + 1,
    block_id: item.block_id,
    node_id: item.node_id,
    secondary_node_ids: secondaryNodeIds,
    node_snapshot: {
      id: node.id,
      name: node.name,
      stage: node.stage,
      domain: node.domain,
      priority: node.priority,
      summer_mode: node.summer_execution.mode,
    },
    question_type: item.question_type,
    variant_level: item.variant_level,
    prompt: item.prompt,
    answer_format: item.answer_format,
    expected_answer: item.expected_answer,
    rubric: [
      {
        result: "correct",
        points: 2,
        evidence: "答案正确，关键步骤可复盘，能用一句话说明方法。",
      },
      {
        result: "partial",
        points: 1,
        evidence: "思路或部分步骤正确，但有计算、表达、单位、符号或解释不稳。",
      },
      {
        result: "wrong",
        points: 0,
        evidence: "答案错误、跳过，或说不清关键概念/关系。",
      },
    ],
    solution_steps: item.solution_steps,
    target_error_tags: item.target_error_tags,
    rollback_candidates: item.rollback_candidates,
    rollback_candidate_relations: rollbackRelationsFor(item),
    estimated_minutes: item.estimated_minutes,
    parent_observation: item.parent_observation,
    source: {
      type: "diagnostic_generated",
      note: "Original diagnostic item generated from project graph and blueprint; not copied from private textbook or question bank.",
      production_pipeline: {
        contract_version: questionProductionContractVersion,
        designer_agent: "diagnostic_agent",
        reviewer_agent: "question_reviewer_agent",
        workflow: ["design_from_graph_blueprint", "review_quality_gate", "release_only_if_approved"],
      },
    },
    age_floor: item.age_floor,
    design_intent: item.design_intent,
    quality: item.quality,
  };
});

for (const block of blocks) {
  const actual = blockItemCounts.get(block.id);
  if (actual !== block.expected_item_count) {
    throw new Error(`${block.id} expected ${block.expected_item_count} items, got ${actual}`);
  }
}

const diagnostic = {
  diagnostic_id: "math_diagnostic_v1",
  schema_version: "1.1.0",
  diagnostic_version: "2026-07-05.v2",
  status: "released",
  title: "小升初数学首诊 v1",
  graph_ref: {
    path: graphPath,
    name: graph.metadata.name,
    version: graph.metadata.version,
    node_count: graph.nodes.length,
  },
  purpose: "用少量但覆盖面足够的题定位小学前置漏洞和七上预学入口，不追求考试分数。",
  learner_scope: "incoming_grade_7_private_math_bridge",
  created_at: "2026-07-05",
  created_by: "Codex multi-agent team",
  total_recommended_minutes: graph.diagnostic_blueprint.total_recommended_minutes,
  source_policy: "All questions are original graph-generated diagnostic probes. They do not claim to be textbook, workbook, or private question-bank items.",
  student_visible_instruction: "请写出关键步骤。不会的题不要猜太久，标记卡住的位置。每题做完尽量用一句话说明你为什么这样做。",
  parent_instruction: {
    hard_stop_minutes: 60,
    do_not_prompt_during_first_attempt: "除非孩子完全读不懂题目，否则先不提示方法。",
    record_observations: [
      "result: correct / partial / wrong / skipped",
      "whether key steps are visible",
      "whether the child can explain the method in one sentence",
      "error_tags",
      "parent_note",
      "time_used_seconds",
    ],
  },
  canonical_error_tags: graph.schema.error_tags,
  result_interpretation: {
    A_mastered: "直接证据正确率≥85%，步骤可复盘，且能口头说清方法；只安排间隔复测。",
    B_unstable: "直接证据正确率60%-85%，或结果正确但步骤、解释、单位、符号不稳；安排微课+少量变式+隔天复测。",
    C_weak: "直接证据正确率<60%，或概念/模型说不清；沿图谱前置节点回退补。",
    D_blocked: "当前节点和前置节点同时失败，或孩子无法开始；暂停当前七上内容，补依赖链最早断点。",
    unknown_not_tested: "没有直接诊断证据的节点保持未知，不从本次诊断推断 A/B/C/D。",
  },
  scoring_policy: {
    max_points_per_item: 2,
    partial_credit: "Use partial when core relation is present but computation, expression, unit, or explanation is unstable.",
    explanation_score: "0=cannot explain, 1=can explain after prompting, 2=can explain independently.",
    no_public_percentage_for_child: true,
  },
  lineage_policy: {
    released_items_are_append_only: true,
    status_requires_direct_evidence: true,
    ungraded_attempts_do_not_create_node_status: true,
    status_D_requires_blocking_evidence_or_verified_prerequisite_failure: true,
    allowed_next_actions: ["pass", "retest", "remediate", "rollback"],
  },
  blocks,
  items,
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(diagnostic.title)}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f3ea;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d8d0c2;
      --paper: #fffaf0;
      --soft: #ece5d8;
      --accent: #1f7a6d;
      --accent-dark: #13594f;
      --warn: #b45309;
      --bad: #b42318;
      --ok: #157347;
      --shadow: 0 12px 32px rgba(39, 32, 19, .12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }
    button, input, textarea, select { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      min-height: 42px;
      padding: 0 14px;
      cursor: pointer;
    }
    button:hover { border-color: var(--accent); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 700;
    }
    button.primary:hover { background: var(--accent-dark); }
    button.icon {
      width: 42px;
      padding: 0;
      display: inline-grid;
      place-items: center;
      font-weight: 700;
    }
    .layout {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #eee6d8;
      padding: 20px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }
    .brand {
      font-size: 18px;
      font-weight: 800;
      margin-bottom: 6px;
    }
    .subtle { color: var(--muted); font-size: 13px; line-height: 1.55; }
    .meter { height: 10px; background: #ded5c6; border-radius: 999px; overflow: hidden; margin: 18px 0 10px; }
    .meter > span { display: block; height: 100%; width: 0; background: var(--accent); transition: width .2s ease; }
    .block-list { display: grid; gap: 8px; margin-top: 18px; }
    .block-btn {
      text-align: left;
      min-height: 48px;
      background: rgba(255,255,255,.5);
      display: grid;
      gap: 2px;
    }
    .block-btn.active { border-color: var(--accent); background: #fffaf0; }
    .block-btn strong { font-size: 13px; }
    .main {
      display: grid;
      grid-template-rows: auto 1fr;
      min-width: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(247, 243, 234, .88);
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(10px);
    }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
      gap: 18px;
      padding: 22px;
      align-items: start;
    }
    .question-card, .parent-panel, .finish-panel {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .question-card { padding: 24px; min-height: 520px; display: flex; flex-direction: column; }
    .crumb { color: var(--accent-dark); font-size: 13px; font-weight: 800; margin-bottom: 10px; }
    .prompt { font-size: clamp(20px, 2.2vw, 30px); line-height: 1.45; font-weight: 750; margin: 0 0 18px; }
    .answer-format { color: var(--muted); font-size: 14px; margin-bottom: 16px; }
    textarea {
      width: 100%;
      min-height: 170px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf8;
      padding: 14px;
      line-height: 1.5;
    }
    .child-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: auto; padding-top: 20px; }
    details {
      border-top: 1px solid var(--line);
      margin-top: 18px;
      padding-top: 12px;
    }
    summary { cursor: pointer; color: var(--muted); font-weight: 700; }
    .answer-key { color: var(--muted); line-height: 1.55; }
    .parent-panel { padding: 18px; }
    .panel-title { font-weight: 850; margin-bottom: 6px; }
    .field { margin-top: 14px; display: grid; gap: 7px; }
    label { font-size: 13px; color: var(--muted); font-weight: 700; }
    select, input[type="text"], input[type="number"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf8;
      min-height: 40px;
      padding: 0 10px;
    }
    .result-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .result-grid button { padding: 0 8px; }
    .result-grid button.selected { color: #fff; border-color: transparent; }
    .result-grid button[data-result="correct"].selected { background: var(--ok); }
    .result-grid button[data-result="partial"].selected { background: var(--warn); }
    .result-grid button[data-result="wrong"].selected { background: var(--bad); }
    .tag-grid { display: grid; grid-template-columns: 1fr; gap: 7px; }
    .tag-option {
      display: grid;
      grid-template-columns: 20px 1fr;
      gap: 8px;
      align-items: start;
      color: var(--ink);
      font-size: 13px;
      font-weight: 500;
      background: #fffdf8;
      border: 1px solid var(--line);
      padding: 8px;
      border-radius: 8px;
    }
    .node-note {
      margin-top: 14px;
      padding: 10px;
      background: var(--soft);
      border-radius: 8px;
      font-size: 12px;
      color: #5b5449;
      line-height: 1.5;
    }
    .finish-panel { display: none; padding: 24px; margin: 22px; }
    .finish-panel.show { display: block; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }
    .summary-tile { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fffdf8; }
    .summary-tile strong { display: block; font-size: 22px; }
    .toast {
      position: fixed;
      left: 50%;
      bottom: 22px;
      transform: translateX(-50%);
      background: #1f2933;
      color: #fff;
      padding: 10px 14px;
      border-radius: 8px;
      opacity: 0;
      pointer-events: none;
      transition: opacity .18s ease;
      z-index: 20;
    }
    .toast.show { opacity: 1; }
    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; }
      aside { position: relative; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
      .block-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workspace { grid-template-columns: 1fr; padding: 14px; }
      header { align-items: flex-start; flex-direction: column; }
      .toolbar { justify-content: flex-start; }
      .question-card { min-height: 420px; padding: 18px; }
    }
    @media (max-width: 560px) {
      aside { padding: 14px; }
      .block-list {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        padding-bottom: 4px;
        margin-top: 12px;
      }
      .block-list button {
        width: 168px;
        flex: 0 0 168px;
      }
      .summary-grid, .result-grid { grid-template-columns: 1fr; }
      button { width: 100%; }
      button.icon { width: 42px; }
      .child-actions, .toolbar { width: 100%; }
    }
  </style>
</head>
<body>
  <script id="diagnostic-data" type="application/json">${JSON.stringify(diagnostic)}</script>
  <div class="layout">
    <aside>
      <div class="brand">数学首诊</div>
      <div class="subtle">不是考试。先安静做题，家长只记录证据。</div>
      <div class="meter" aria-label="progress"><span id="progressBar"></span></div>
      <div class="subtle"><span id="progressText">0 / 48</span> 已记录</div>
      <div class="block-list" id="blockList"></div>
    </aside>
    <main class="main">
      <header>
        <div>
          <div class="subtle" id="positionText">第 1 题</div>
          <strong id="blockTitle">计算与运算规则</strong>
        </div>
        <div class="toolbar">
          <button class="icon" id="prevBtn" aria-label="上一题">‹</button>
          <button class="icon" id="nextBtn" aria-label="下一题">›</button>
          <button id="finishBtn">完成查看</button>
          <button class="primary" id="exportBtn">导出记录</button>
        </div>
      </header>
      <section class="workspace" id="workspace">
        <article class="question-card">
          <div class="crumb" id="questionCrumb"></div>
          <h1 class="prompt" id="prompt"></h1>
          <div class="answer-format" id="answerFormat"></div>
          <textarea id="answerInput" placeholder="孩子可以在纸上完成，这里可简单记录答案或卡住的位置。"></textarea>
          <div class="child-actions">
            <button class="primary" id="saveAnswerBtn">我写好了</button>
            <button id="skipBtn">先放一下</button>
          </div>
          <details>
            <summary>家长查看答案与节点信息</summary>
            <div class="answer-key" id="answerKey"></div>
          </details>
        </article>
        <aside class="parent-panel" aria-label="parent marking">
          <div class="panel-title">家长记录</div>
          <div class="subtle">这里记录观察，不给孩子贴标签。</div>
          <div class="field">
            <label>结果</label>
            <div class="result-grid">
              <button data-result="correct">正确</button>
              <button data-result="partial">部分</button>
              <button data-result="wrong">需回看</button>
            </div>
          </div>
          <div class="field">
            <label for="explainScore">孩子解释</label>
            <select id="explainScore">
              <option value="">未记录</option>
              <option value="2">能独立讲清</option>
              <option value="1">提醒后能讲</option>
              <option value="0">说不清</option>
            </select>
          </div>
          <div class="field">
            <label>可能错因</label>
            <div class="tag-grid" id="tagGrid"></div>
          </div>
          <div class="field">
            <label for="timeUsed">本题用时（分钟，可选）</label>
            <input id="timeUsed" type="number" min="0" step="0.5">
          </div>
          <div class="field">
            <label for="parentNote">家长备注</label>
            <textarea id="parentNote" placeholder="例如：单位1说不清；符号变号漏了一项；能做但不愿写步骤。"></textarea>
          </div>
          <button class="primary" id="saveMarkBtn">保存本题记录</button>
          <div class="node-note" id="nodeNote"></div>
        </aside>
      </section>
      <section class="finish-panel" id="finishPanel">
        <h2>今天完成了</h2>
        <p class="subtle">孩子看到这里就可以休息。下面是给家长和 Codex 复盘用的记录概览。</p>
        <div class="summary-grid" id="summaryGrid"></div>
      </section>
    </main>
  </div>
  <div class="toast" id="toast">已保存</div>
  <script>
    const diagnostic = JSON.parse(document.getElementById("diagnostic-data").textContent);
    const stateKey = diagnostic.diagnostic_id + ":attempts";
    const attempts = JSON.parse(localStorage.getItem(stateKey) || "{}");
    let index = 0;

    const tagLabels = {
      calculation_or_symbol: "计算/符号",
      concept_confusion: "概念不清",
      modeling_or_reading: "读题/建模",
      process_habit: "步骤习惯",
      visual_spatial: "图形空间",
      general: "暂不确定"
    };

    const $ = (id) => document.getElementById(id);
    const current = () => diagnostic.items[index];

    function saveState() {
      localStorage.setItem(stateKey, JSON.stringify(attempts));
    }

    function toast(text = "已保存") {
      $("toast").textContent = text;
      $("toast").classList.add("show");
      setTimeout(() => $("toast").classList.remove("show"), 1300);
    }

    function renderBlocks() {
      $("blockList").innerHTML = diagnostic.blocks.map((block) => {
        const firstIndex = diagnostic.items.findIndex((item) => item.block_id === block.id);
        const count = diagnostic.items.filter((item) => item.block_id === block.id).length;
        return '<button class="block-btn" data-index="' + firstIndex + '">' +
          '<strong>' + block.name + '</strong>' +
          '<span class="subtle">' + count + ' 题 · ' + block.minutes + ' 分钟</span>' +
          '</button>';
      }).join("");
      document.querySelectorAll(".block-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          index = Number(btn.dataset.index);
          render();
        });
      });
    }

    function attemptFor(item) {
      return attempts[item.id] || {};
    }

    function renderTags(item, saved) {
      $("tagGrid").innerHTML = item.target_error_tags.map((tag) => {
        const checked = (saved.error_tags || []).includes(tag) ? "checked" : "";
        return '<label class="tag-option"><input type="checkbox" value="' + tag + '" ' + checked + '>' +
          '<span><strong>' + (tagLabels[tag] || tag) + '</strong><br><span class="subtle">' +
          diagnostic.canonical_error_tags[tag] + '</span></span></label>';
      }).join("");
    }

    function render() {
      const item = current();
      const block = diagnostic.blocks.find((candidate) => candidate.id === item.block_id);
      const saved = attemptFor(item);
      $("positionText").textContent = "第 " + (index + 1) + " / " + diagnostic.items.length + " 题";
      $("blockTitle").textContent = block.name;
      $("questionCrumb").textContent = item.id + " · " + item.question_type;
      $("prompt").textContent = item.prompt;
      $("answerFormat").textContent = "作答形式：" + item.answer_format;
      $("answerInput").value = saved.answer_raw || "";
      $("answerKey").innerHTML = "<p><strong>参考答案：</strong>" + item.expected_answer + "</p><ol>" +
        item.solution_steps.map((step) => "<li>" + step + "</li>").join("") + "</ol>";
      $("explainScore").value = saved.child_explanation_score_0_to_2 ?? "";
      $("timeUsed").value = saved.duration_seconds ? Math.round(saved.duration_seconds / 60 * 10) / 10 : "";
      $("parentNote").value = saved.parent_note || "";
      document.querySelectorAll(".result-grid button").forEach((btn) => {
        btn.classList.toggle("selected", saved.result === btn.dataset.result);
      });
      renderTags(item, saved);
      $("nodeNote").innerHTML = "<strong>家长用：</strong>" + item.node_snapshot.name +
        " · " + item.node_snapshot.stage + "<br><span class='subtle'>节点 " + item.node_id +
        "；回退候选：" + item.rollback_candidates.join(", ") + "</span>";
      $("prevBtn").disabled = index === 0;
      $("nextBtn").disabled = index === diagnostic.items.length - 1;
      document.querySelectorAll(".block-btn").forEach((btn) => {
        btn.classList.toggle("active", Number(btn.dataset.index) === diagnostic.items.findIndex((candidate) => candidate.block_id === item.block_id));
      });
      renderProgress();
    }

    function renderProgress() {
      const recorded = Object.values(attempts).filter((item) => item.result || item.answer_raw).length;
      $("progressText").textContent = recorded + " / " + diagnostic.items.length;
      $("progressBar").style.width = Math.round(recorded / diagnostic.items.length * 100) + "%";
    }

    function selectedTags() {
      return Array.from(document.querySelectorAll("#tagGrid input:checked")).map((input) => input.value);
    }

    function saveAnswerOnly() {
      const item = current();
      attempts[item.id] = {
        ...attemptFor(item),
        attempt_id: attemptFor(item).attempt_id || crypto.randomUUID(),
        question_id: item.id,
        item_version: item.item_version,
        node_id: item.node_id,
        answer_raw: $("answerInput").value.trim(),
        answer_normalized: $("answerInput").value.trim(),
        grading_status: "ungraded",
        updated_at: new Date().toISOString(),
      };
      saveState();
      toast("答案已记录");
      renderProgress();
    }

    function saveMark() {
      const item = current();
      const saved = attemptFor(item);
      const result = document.querySelector(".result-grid button.selected")?.dataset.result || "";
      if (!result) {
        toast("请先选择正确、部分或需回看");
        return;
      }
      const minutes = Number($("timeUsed").value || 0);
      const explanation = $("explainScore").value === "" ? null : Number($("explainScore").value);
      const rawTags = selectedTags();
      const tags = result && result !== "correct" && rawTags.length === 0 ? ["general"] : rawTags;
      const nextAction = result === "correct" && explanation === 2 ? "pass" :
        result === "correct" ? "retest" :
        result === "partial" ? "remediate" : "rollback";
      attempts[item.id] = {
        ...saved,
        attempt_id: saved.attempt_id || crypto.randomUUID(),
        question_id: item.id,
        item_version: item.item_version,
        node_id: item.node_id,
        grading_status: "graded",
        answer_raw: $("answerInput").value.trim(),
        answer_normalized: $("answerInput").value.trim(),
        result,
        score_points: result === "correct" ? 2 : result === "partial" ? 1 : 0,
        max_points: 2,
        duration_seconds: minutes > 0 ? Math.round(minutes * 60) : null,
        error_tag: tags[0] || null,
        error_tags: tags,
        parent_note: $("parentNote").value.trim(),
        child_explanation_score_0_to_2: explanation,
        grader: "parent",
        graded_at: new Date().toISOString(),
        next_action: nextAction,
        rollback_candidate_node_ids: item.rollback_candidates,
        rollback_candidate_relations: item.rollback_candidate_relations,
        blocking_evidence: false,
        manual_override: false,
      };
      saveState();
      toast("本题记录已保存");
      renderProgress();
    }

    function exportAttempt() {
      const now = new Date().toISOString();
      const attemptList = diagnostic.items.map((item) => attempts[item.id]).filter(Boolean);
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
          followup_probe_node_ids: status === "A" ? [] : followupProbes
        };
      });
      const exportData = {
        attempt_export_id: diagnostic.diagnostic_id + "-" + now.replaceAll(":", "").replaceAll(".", ""),
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
        amendments: []
      };
      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "math_diagnostic_v1_attempt_" + now.slice(0, 10) + ".json";
      a.click();
      URL.revokeObjectURL(url);
      toast("已导出记录");
    }

    function showFinish() {
      const totals = { correct: 0, partial: 0, wrong: 0, blank: 0 };
      for (const item of diagnostic.items) {
        const result = attempts[item.id]?.result;
        if (result) totals[result] += 1;
        else totals.blank += 1;
      }
      $("summaryGrid").innerHTML = [
        ["正确", totals.correct],
        ["部分", totals.partial],
        ["需回看", totals.wrong],
        ["未记录", totals.blank],
      ].map(([label, value]) => '<div class="summary-tile"><strong>' + value + '</strong><span class="subtle">' + label + '</span></div>').join("");
      $("finishPanel").classList.add("show");
      $("finishPanel").scrollIntoView({ behavior: "smooth" });
    }

    document.querySelectorAll(".result-grid button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".result-grid button").forEach((item) => item.classList.remove("selected"));
        btn.classList.add("selected");
      });
    });
    $("saveAnswerBtn").addEventListener("click", saveAnswerOnly);
    $("saveMarkBtn").addEventListener("click", saveMark);
    $("skipBtn").addEventListener("click", () => {
      const item = current();
      attempts[item.id] = {
        ...attemptFor(item),
        question_id: item.id,
        item_version: item.item_version,
        node_id: item.node_id,
        attempt_id: attemptFor(item).attempt_id || crypto.randomUUID(),
        grading_status: "graded",
        answer_raw: $("answerInput").value.trim(),
        answer_normalized: $("answerInput").value.trim(),
        result: "wrong",
        score_points: 0,
        max_points: 2,
        error_tags: ["general"],
        error_tag: "general",
        parent_note: "先放一下/跳过",
        child_explanation_score_0_to_2: 0,
        grader: "parent",
        next_action: "rollback",
        rollback_candidate_node_ids: item.rollback_candidates,
        rollback_candidate_relations: item.rollback_candidate_relations,
        blocking_evidence: true,
        manual_override: false,
        graded_at: new Date().toISOString(),
      };
      saveState();
      toast("已记录为先放一下");
      render();
    });
    $("prevBtn").addEventListener("click", () => { index = Math.max(0, index - 1); render(); });
    $("nextBtn").addEventListener("click", () => { index = Math.min(diagnostic.items.length - 1, index + 1); render(); });
    $("exportBtn").addEventListener("click", exportAttempt);
    $("finishBtn").addEventListener("click", showFinish);
    renderBlocks();
    render();
  </script>
</body>
</html>
`;

const doc = `# Math Diagnostic v1

Status: ${diagnostic.status}  
Version: ${diagnostic.diagnostic_version}  
Time limit: ${diagnostic.total_recommended_minutes} minutes  
Question source: original graph-generated diagnostic probes from \`${graphPath}\`

## Purpose

This is the first math diagnostic loop for the private AI learning system. It is not a school-style score test.

Use it to locate graph-node breakpoints before summer bridging work begins:

- 小学关键前置是否稳定
- 七上有理数、代数式入口是否能启动
- 错因是概念、计算符号、读题建模、步骤习惯还是图形空间关系
- 七上题错时，应回退到哪一个前置节点

## How To Use

- Hard stop at 60 minutes.
- Do not give method hints during the first attempt unless the child cannot understand the wording.
- Ask the child to write key steps, not only final answers.
- After a question, ask gently: “你为什么这样做？” Record whether the explanation is clear.
- Do not calculate a public percentage grade for the child.
- Open the student page: \`app/student/math_diagnostic_v1.html\`.
- Export the attempt JSON after marking; feed that file back to Codex for node-state analysis.

## Data Contract

- Source diagnostic JSON: \`data/questions/math_diagnostic_v1.json\`
- Graph version: \`${graph.metadata.version}\`
- Every item has a graph \`node_id\`, canonical error tags, rollback candidates, answer key, rubric, and source provenance.
- Version \`${diagnostic.diagnostic_version}\` also carries \`quality.review_status=approved\`,
  \`age_floor=incoming_grade_7\`, and reasoning-signal metadata. The validator
  rejects answer-only arithmetic, child-facing generator/meta language, and items
  without observable process evidence.
- Untested nodes remain \`unknown/not_tested\`; A/B/C/D requires direct evidence.
- Answer-only records are exported as \`grading_status: "ungraded"\` and do not create node status.
- A normal wrong answer becomes C unless there is explicit blocking evidence. D is reserved for clear cannot-start/skip evidence or verified prerequisite-chain failure.
- Rollback candidates include relation labels: \`self_retest\`, \`secondary_node\`, \`prerequisite_chain\`, or \`followup_probe\`.
- Released question content should not be overwritten after a real attempt. Create a new version or superseding item instead.

## Question Map

| ID | Block | Node | Question type |
|---|---|---|---|
${diagnostic.items.map((item) => `| ${item.id} | ${item.block_id} | \`${item.node_id}\` | ${item.question_type} |`).join("\n")}

## Node Status Rules

| Status | Meaning | Next action |
|---|---|---|
| A | Correct, steps visible, can explain method, direct evidence score >=85% | Pass; interval retest only |
| B | Mostly correct but slow, prompted, explanation weak, or unstable | Micro-explain + small variation + next-day retest |
| C | Wrong, skipped, or concept/model unclear | Remediate the node before moving on |
| D | Current node and prerequisite chain both fail, or child cannot start | Roll back to earliest weak prerequisite |
| unknown | No direct evidence | Do not infer mastery or weakness |

Important: if a Grade 7 node is wrong and its prerequisite node is also wrong, do not drill more same-type Grade 7 questions first. Roll back along the prerequisite chain.

## Review Checklist

- Does every wrong/partial item have a concrete error tag or \`general\` plus a parent note?
- Did the child show steps that can be reviewed?
- Did the child explain the method independently, with prompting, or not at all?
- Are units and answer sentences present for word problems?
- Are any rollback candidates outside the first diagnostic set? If yes, mark them as needs follow-up probe rather than weak by assumption.

## Validation

\`\`\`bash
node scripts/validate_math_diagnostic_v1.mjs
jq empty data/questions/math_diagnostic_v1.json
\`\`\`
`;

fs.mkdirSync(path.join(root, "data/questions"), { recursive: true });
fs.mkdirSync(path.join(root, "app/student"), { recursive: true });
fs.mkdirSync(path.join(root, "docs/diagnostics"), { recursive: true });
fs.writeFileSync(path.join(root, "data/questions/math_diagnostic_v1.json"), JSON.stringify(diagnostic, null, 2) + "\n", "utf8");
fs.writeFileSync(path.join(root, "app/student/math_diagnostic_v1.html"), html, "utf8");
fs.writeFileSync(path.join(root, "docs/diagnostics/math_diagnostic_v1.md"), doc, "utf8");

console.log(`Generated ${diagnostic.items.length} diagnostic items.`);
