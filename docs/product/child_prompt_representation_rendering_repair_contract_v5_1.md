# Child Prompt Representation And Rendering Repair Contract v5.1

Status: `UX_REPAIR_READY_FOR_IMPLEMENTATION`

Result type: `UX_DESIGN/REPAIR_CONTRACT`

Owner: 清秋 (`qingqiu`)

Date: 2026-07-17 CST

Implementer: 听云

## Purpose And Precedence

This contract closes four child-facing delivery gaps in generated math questions:

1. Markdown tables are shown as source text because the child renderer does not
   render Markdown.
2. Daily runtime projection collapses meaningful prompt line breaks into spaces.
3. Unicode modifier letters such as `ᵏ` and `ᵃ` are used as variable exponents
   without stable mathematical or accessibility semantics.
4. A prompt instruction can request a response move that its interaction schema
   does not represent, such as asking why an option was "classified" when the
   child only made one choice.

This is a representation and rendering repair, not a new learning experience.
For child-visible question prompts and answer controls, it overrides conflicting
behavior in the current question interaction v1 normalization, daily runtime
projection, and local child renderer. It does not change mathematical answers,
node alignment, assessment policy, question selection, or evidence authority.

## Non-Goals

- No general Markdown renderer.
- No general LaTeX, MathJax, or KaTeX authoring surface.
- No rich-text editor or child-authored table editor.
- No new question type beyond the existing `short_text`, `fill_blank`,
  `single_choice`, `multi_choice`, and `formula_input` controls.
- No change to photo submission, stuck handling, grading, or answer evidence.
- No rewrite of otherwise valid questions merely to make every prompt use the
  same sentence pattern.

## Root Decisions

### 1. Prompt And Interaction Have Separate Ownership

The child prompt describes the mathematical situation and instruction. The
interaction schema describes the answer controls and required response moves.

- Prompt grouping is not encoded in `interaction_schema`.
- Choices, named blanks, one formula input, and required explanation state are
  encoded in `interaction_schema` and are not duplicated in the prompt body.
- A table or list that the child must read is stimulus content. In this repair it
  must be represented as labeled plain-text lines, not Markdown.
- A table or set of fields that the child must complete is answer structure. It
  must use `fill_blank.fields`, or the instruction must be rewritten to request
  a short explanation/list that a `short_text` control can actually accept.

### 2. Child Prompt Uses One Restricted Plain-Text Format

Question source, prompt package, child DTO, and renderer use:

```json
{
  "prompt_format": "2026-07-17.child-plain-text.v1",
  "prompt": "受限纯文本题面"
}
```

`prompt_format` is adjacent to `prompt`; it is not nested inside
`interaction_schema`.

New or repaired v5.1 question items must declare this exact format. During the
compatibility window, a missing format identifies a legacy item: runtime may
first apply the lossless legacy normalization defined below and then validate it
as this format. Unsupported formats must not be silently rendered as plain text.

### 3. The Renderer Supports Structure, Not Authoring Markup

The renderer supports only:

- ordinary text;
- preserved line breaks and one blank line between groups;
- safe inline exponent tokens defined below;
- existing structured answer controls from `interaction_schema`.

It does not interpret Markdown, HTML, or LaTeX.

## Restricted Plain-Text Prompt Contract

### Allowed Grouping

- `\n` creates a new visible line.
- `\n\n` creates one visible group break.
- More than one consecutive blank line is normalized to one group break.
- A labeled item uses one complete line, for example `p 项：4p，−p`.
- A named representation or plan begins on its own line, for example
  `方案甲：...` or `表示二：...`.
- Plain numbered lines such as `1. ...` and literal bullet lines beginning with
  `• ` are allowed as text. Their meaning must not depend on Markdown styling.
- Tabs and repeated spaces are not layout tools.

### Required Projection Behavior

For `prompt`, daily runtime must:

1. normalize `CRLF` and `CR` to `LF`;
2. trim spaces at the beginning and end of the full prompt;
3. trim trailing horizontal spaces on each line;
4. preserve single line breaks and one blank line between groups;
5. continue child-safe forbidden-term validation without joining all whitespace;
6. reject an over-limit or malformed prompt before child delivery instead of
   silently truncating a formula, label, or final instruction.

The generic `_child_safe_text` behavior that uses `" ".join(text.split())` is
not valid for prompt projection. Compact labels, button copy, placeholders, and
single-line metadata may continue using whitespace collapse.

### Required Renderer Behavior

- Prompt content remains escaped and cannot inject HTML.
- Text lines are rendered using text nodes plus explicit line structure, or an
  escaped container whose computed `white-space` is `pre-line`.
- The renderer must not replace prompt line breaks with spaces.
- Long formulas may wrap, but the page must not gain horizontal document scroll.
- A line break must not create an extra focus stop.
- A blank line is visual spacing only and is not announced as an empty control.

## Mathematical Notation Contract

### Canonical Exponent Source

The source representation for an exponent is caret notation:

```text
x^2
y^k
x^a
(−3xy)^2
```

Rules:

- The exponent is one ASCII letter or one unsigned integer.
- The base is the immediately preceding letter, number, or closed parenthesis.
- A negative or compound exponent is out of scope for this v5.1 repair.
- Fractions remain linear, for example `2/5`; parentheses are required when a
  numerator or denominator contains more than one token.
- Use the mathematical minus `−` and multiplication sign `×` in child-visible
  source where they already form part of the question-bank convention.

### Exponent Rendering

The app renderer converts only valid caret exponent tokens into safe DOM, for
example `y^k` to visually rendered `y` with `<sup>k</sup>`.

- Conversion happens after tokenization into safe text, never by accepting raw
  HTML from the source.
- The visible exponent must remain legible at 390px and browser zoom up to 200%.
- The rendered math fragment must expose an accessible name equivalent to
  `y 的 k 次方` or `x 的 2 次方`; a bare visual `<sup>` with no reliable spoken
  meaning is insufficient.
- Copying the rendered expression may yield `y^k` or an equivalent unambiguous
  linear form.

### Forbidden Exponent Source

The following are forbidden in new or repaired child prompts:

- Unicode modifier-letter exponents such as `ᵃ`, `ᵏ`, or other superscript
  alphabetic glyphs;
- Unicode numeric superscripts such as `²`, `³`, and `⁴` as new authoring input;
- LaTeX exponent syntax such as `$x^2$`, `x^{2}`, or `\(x^2\)`;
- HTML such as `x<sup>2</sup>`.

Existing numeric superscripts may be normalized to caret source during migration,
but they must not remain the canonical stored representation after an item is
repaired under this contract.

Legacy v1 compatibility is intentionally narrower than v2 authoring:

- recognized numeric superscripts `⁰` through `⁹` may be converted to their
  equivalent caret exponent;
- recognized modifier-letter exponents used by current items, including `ᵃ` and
  `ᵏ`, may be converted only when the base and exponent are unambiguous;
- the normalized prompt is then subjected to the complete v2 source validation;
- an unrecognized or ambiguous superscript blocks delivery.

This compatibility path does not make Unicode superscripts valid v2 source.

## Interaction Schema Contract

### Version

Repaired and newly generated items use:

```json
{
  "schema_version": "2026-07-17.question-interaction.v2"
}
```

Version 2 retains the five current interaction types and makes
`requires_explanation` an explicit normalized boolean. Version 1 may be read for
legacy items, but an item repaired for this contract must be emitted as v2.

### Minimum Common Shape

```json
{
  "schema_version": "2026-07-17.question-interaction.v2",
  "type": "short_text|fill_blank|single_choice|multi_choice|formula_input",
  "title": "孩子可见的作答区标题",
  "allow_explanation": true,
  "requires_explanation": false,
  "explanation_label": "说明理由",
  "fields": [],
  "choices": [],
  "formula_label": "",
  "placeholder": ""
}
```

### Type Ownership

| Required child action | Schema type | Contract |
|---|---|---|
| Write one coherent answer, process, or explanation | `short_text` | Do not also demand a drawn table or several independently graded blanks. |
| Supply two or more named short values | `fill_blank` | One field per value; labels carry units or meaning. |
| Choose exactly one supplied answer | `single_choice` | Full option labels live only in `choices`. |
| Choose every matching supplied answer | `multi_choice` | Full option labels live only in `choices`. |
| Enter one key equation or expression | `formula_input` | Use `formula_label`; explanation may be separately allowed or required. |

Additional rules:

- `requires_explanation: true` requires `allow_explanation: true`, a nonempty
  `explanation_label`, and an explicit explanation instruction in the prompt.
- A prompt saying `请选择一个` requires `single_choice`.
- A prompt saying `请选择所有` requires `multi_choice`.
- A classification task must state which group the controls capture. If the
  child must assign every option to two groups, either capture one named group
  with `multi_choice` and define the complement, or use named fields. Do not make
  the child reconstruct a control model in free text.
- Prompt option lines such as `A. ...` are forbidden when the same options exist
  in `choices`. Runtime compatibility repair is not the source-authoring model.
- `title` and `explanation_label` must describe the same response move as the
  final prompt sentence. Words such as `分类`, `判断`, `改写`, and `说明` are not
  interchangeable when they ask the child to do different work.

## Forbidden Source Formats

The v2 child prompt validator must reject these before an item can be delivered:

- Markdown tables, including pipe rows and delimiter rows such as `|---|`;
- Markdown headings, fenced code blocks, inline code, links, images, or emphasis
  used with the expectation that they will be rendered;
- raw HTML tags or entities used for layout;
- LaTeX delimiters or commands, including `$...$`, `$$...$$`, `\(...\)`,
  `\[...\]`, `\frac`, and `\begin`;
- tabs, repeated-space alignment, or ASCII-art columns;
- Unicode variable superscripts and newly authored Unicode numeric superscripts;
- duplicated choice options in both `prompt` and `interaction_schema.choices`;
- instructions whose required response move conflicts with the schema type,
  explanation requirement, title, or label.

A validation failure blocks child delivery and returns the existing safe
`当前步骤还没有准备好，请稍后再试。` state. It must not expose raw source markup.

## Required Slot Repairs

### `M-G7-PARENTHESIS` Slot 5

Keep `short_text`. Replace the Markdown table with labeled lines:

```text
把下面的去括号变化记录翻译成一个完整的化简过程，并写出最后结果。

原式：2m−3(m+4)
变化记录：
m → −3m
+4 → −12
```

The child must see four distinct content lines after the group break and no pipe
or Markdown delimiter characters.

### `M-G7-POLY-ADD-SUB` Slot 5

Keep `short_text`. Preserve this grouping:

```text
小航把整式 (4p−q+3)−(p+2q−5) 的去括号结果整理成了分项记录：

p 项：4p，−p
q 项：−q，−2q
常数项：3，+5

请把这份记录翻译成不含括号的式子，并写出合并同类项后的结果。
```

Do not call the source a table unless a real table structure exists.

### `M-G7-MONOMIAL` Slot 18

Keep `short_text`. Put `表示一` and `表示二` on separate lines and use caret
source for exponents:

```text
同一个单项式有两种表示：

表示一：(−2)×π×u×u×v^3
表示二：
数字因数：−2 和 π
字母指数：u 的指数是 2，v 的指数是 3

请把两种表示都翻译成规范单项式，并判断它们得到的系数和次数是否一致。
```

### `M-G7-POLYNOMIAL` Slot 9

Keep `short_text`. Use this exact prompt:

```text
航模社记录了两种高度调整方案，变量 h 表示同一个调节量。

方案甲：先上升 4h^2 米，再下降 h 米，最后下降 3 米。
方案乙：先上升 2h^3 米，再下降 5 米，最后上升 h 米。

先预测哪一个方案对应的多项式次数更高；再把这个方案对应的多项式写出来，并写出它的各项、常数项和次数。
```

### `M-G7-POLYNOMIAL` Slot 17

Change the answer structure from `short_text` to `multi_choice` plus required
explanation.

Prompt instruction:

```text
有同学说：“判断一个多项式的次数，只要看写在第一项的那一项次数就行。”
请选择所有能直接反驳这句话的式子，并说明其余式子为什么不能直接反驳。
```

The four full expressions live in `interaction_schema.choices`; they are absent
from `prompt`. `requires_explanation` is `true`, and `explanation_label` is
`说明你的分类依据`.

Use this exact interaction schema content:

```json
{
  "schema_version": "2026-07-17.question-interaction.v2",
  "type": "multi_choice",
  "title": "选择所有能直接反驳说法的式子",
  "allow_explanation": true,
  "requires_explanation": true,
  "explanation_label": "说明你的分类依据",
  "fields": [],
  "choices": [
    {"id": "A", "label": "x+4x^3−2"},
    {"id": "B", "label": "5y^2−3y+1"},
    {"id": "C", "label": "7m−4"},
    {"id": "D", "label": "−2a^4+3a^2−6"}
  ],
  "formula_label": "",
  "placeholder": ""
}
```

### `M-G7-PARENTHESIS` Slot 13

Keep `single_choice`. Use this exact prompt:

```text
计算 18−(+6)+(−4) 时，下面哪一种改写最准确地保持了原式的意义？请选择，并说明为什么这个改写保持了原式的意义。
```

Use `explanation_label: "说明改写理由"`. Do not use `分类` in this item.

### `M-G7-MONOMIAL` Slots 11 And 19

Slot 11 uses this exact prompt:

```text
有人记录一个单项式为 −2πx^2y^k，并把它的系数写成 −2π、次数写成 3。根据这个记录，k 可能是多少？请用你找到的 k 反过来检查“系数 −2π、次数 3”这两个判断是否站得住。
```

Slot 19 uses this exact prompt:

```text
已知 5πx^ay^2 是一个次数为 7 的单项式。a 应是多少？请说明你的判断。
```

For both slots:

- The rendered page shows real visual superscripts with accessible exponent
  meaning.
- Literal `ᵏ`, `ᵃ`, `²`, or other superscript source glyphs are absent from the
  repaired item payload.

## Runtime Projection Contract

For a valid question step, the child DTO must include:

```json
{
  "prompt_format": "2026-07-17.child-plain-text.v1",
  "prompt": "换行被保留的题面",
  "interaction_schema": {
    "schema_version": "2026-07-17.question-interaction.v2"
  }
}
```

Projection order:

1. Validate `prompt_format`, forbidden source, schema shape, and prompt/schema
   instruction alignment.
2. Repair legacy letter-only choice labels only during v1 compatibility.
3. Remove duplicated legacy choice lines only during v1 compatibility.
4. Normalize prompt line endings and bounded blank lines without collapsing
   semantic line breaks.
5. Project v2 interaction fields without inventing labels or explanation meaning.
6. If any required field is invalid, return the safe unavailable step; do not
   downgrade to `short_text` or expose raw source.

The child DTO is the renderer authority. The app does not infer whether a line
is a table, choice, heading, or explanation requirement from Chinese text.

## App Renderer Contract

- Render `prompt_format=2026-07-17.child-plain-text.v1` with preserved grouping.
- Escape all prompt text and create exponent DOM only from recognized caret
  tokens.
- Render choices and fields only from `interaction_schema`.
- Do not show a second copy of options inside the prompt.
- Show `(必填)` only when `requires_explanation` is true.
- When required explanation is empty, focus the explanation field and use the
  schema's child-visible label in the recovery message.
- At 390px, answer controls remain at least 44px high; formulas and labels wrap
  inside the control without horizontal page scroll.
- At browser zoom 200%, prompt groups, superscripts, controls, and explanation
  labels remain visible and do not overlap.

## Browser Acceptance

Use real Chromium with a new temporary database or isolated fixture. Do not
write the reviewed questions into live learner data. Run every check at
1280x800 and 390x844.

### A. Source And Projection Gate

1. Load a v2 fixture containing `|---|`; assert delivery is blocked before the raw
   source reaches the child DOM.
2. Load a valid four-line prompt; assert the child DTO still contains its `\n`
   grouping and no line is silently truncated.
3. Load a v2 prompt containing `yᵏ`, `$x^2$`, or `<sup>`; assert validation blocks
   it. Separately load a legacy v1 `yᵏ` fixture and assert it is either losslessly
   normalized to `y^k` or blocked before delivery; the literal glyph never reaches
   the child DOM.
4. Load v2 choice schema with option lines duplicated in prompt; assert validation
   blocks it rather than relying on runtime deletion.

### B. Problem Slot Rendering

1. `M-G7-PARENTHESIS` slot 5: no `|`, `---`, or raw Markdown is visible; `原式`,
   `变化记录`, `m → −3m`, and `+4 → −12` occupy distinct visible lines.
2. `M-G7-POLY-ADD-SUB` slot 5: p item, q item, and constant item remain three
   separately scannable lines.
3. `M-G7-MONOMIAL` slot 18: `表示一` and `表示二` are visually distinct; no
   source caret remains visible after exponent rendering.
4. `M-G7-POLYNOMIAL` slot 9: the two plans are visually separable before the
   child reads the final instruction.
5. `M-G7-POLYNOMIAL` slot 17: four checkbox choices are present, none are
   duplicated in the prompt, and submission without the required explanation is
   stopped with `说明你的分类依据`.
6. `M-G7-PARENTHESIS` slot 13: the page says `说明改写理由`; neither the prompt
   nor answer control asks the child to explain a classification.
7. `M-G7-MONOMIAL` slots 11 and 19: `k` and `a` appear as visible superscripts;
   the DOM contains semantic exponent markup and contains no literal modifier
   letters `ᵏ` or `ᵃ`.

### C. Mobile And Accessibility

1. At 390x844, every grouped prompt can be scanned without horizontal document
   scroll and without a line being clipped behind an answer control.
2. Choice labels, explanation field, submit action, and photo/stuck controls do
   not overlap or change order when a prompt gains multiple lines.
3. Keyboard focus order is prompt-independent: answer controls, optional photo,
   stuck action, then submit/recovery controls according to the existing flow.
4. A screen-reader inspection announces each repaired variable exponent as a
   power, not as an unexplained modifier-letter glyph.
5. At 200% zoom, exponent text remains distinguishable from the base and is not
   clipped by line height.

### D. Regression

1. Existing v1 choice projection tests remain green during compatibility.
2. Add v2 contract tests for preserved newlines, forbidden source formats,
   explicit `requires_explanation`, prompt/schema instruction alignment, and
   safe exponent tokenization.
3. Run the complete child knowledge/question interaction UI suite.
4. Confirm short one-line prompts and existing answer submission payloads retain
   their current behavior.

## Completion Rule

This repair is complete only when:

- all required slot repairs are present in the generated question artifact;
- runtime preserves valid prompt grouping and blocks forbidden source;
- the app renders semantic exponents and schema-owned controls without duplicate
  content;
- every browser acceptance step passes at both viewports;
- no live learner data was used or changed during verification.

Passing schema/unit tests without the real browser checks above is not sufficient
for final UX acceptance.
