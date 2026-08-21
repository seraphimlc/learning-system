"""Mastery wiring adapter layer (M2.5 part 5a): the data bridge, no runtime.

Contract: docs/design/specs/2026-08-20-mastery-criteria-proposal.md
- §2.2 judgment-event granularity (one eligible attempt = one event) and the
  rolling-90-day evidence window W ("滚动 90 天"); the window is built by the
  wiring layer and passed into decide_verdict (mastery_rules.py), which only
  consumes eligible events.
- §2.3 unique consecutive C/D counter: the wiring layer reads history from
  mastery_decisions and maps each row's decision verdict into an event dict
  {"verdict": ..., "is_manual": ...} for cd_counter/feed_cd_counter
  (per the M2.5-1 docstring note).

This module is the *pure adapter* between the DB/external row shapes and
mastery_rules.py's pure functions: no I/O, no sqlite, no runtime calls.
Inputs are plain dict sequences (judgment-event rows / mastery_decisions
rows) that the runtime wiring (M2.5-5b/5c) reads from the DB and feeds in.
Nothing here replaces or retires runtime judgment paths — that is 5b/5c.

Judgment-event row shape (the adapter's primary input, aligned with the
decide_verdict evidence contract):

    {attempt_id, verdict_or_code, is_manual, created_at, result,
     score_points, max_points, explanation_score, reasoning_soundness,
     evidence_strength, next_evidence_need, blocking_evidence,
     structure_fingerprint, purpose_role,
     gate_passed, purpose, hint_policy, mastery_update_eligible,
     voice_verifiable, analysis_valid, ...}

Interpretation notes (proposal / code ambiguity, per the M2.5-1 convention
of documenting the chosen reading):

1. Window anchor: the 90-day window is anchored at the *current judgment
   event's* created_at, not at today — the decision-time window
   [current.created_at - 90 days, current.created_at], inclusive on both
   bounds (a row exactly 90 days old still counts; "滚动 90 天" keeps the
   30-day-interval retest evidence inside). Future rows are excluded so a
   replayed/historical decision never sees evidence it could not have known.
   This keeps decide_verdict deterministic and replayable from history.
2. Eligibility is applied per row (rules.is_eligible) after normalization;
   an ineligible current row is filtered like any other row — per §2.2 only
   eligible attempts are judgment events, and decide_verdict already returns
   R6 NO_CHANGE for an ineligible evidence regardless of the window. The
   wiring layer should check is_judgment_event(current) before judging.
3. to_counter_events requires the unified 5-value verdict on each row
   (field verdict_or_code, alias "verdict"); legacy enums (flow_nodes 6-态,
   v51 recommendation, stored new_status_code) are *refused* with
   ValueError rather than silently miscounted — the 5b/5c wiring must record
   the unified verdict on the row (or convert legacy payloads) before
   counter derivation. NO_CHANGE rows are dropped at mapping time (§2.3
   "NO_CHANGE 事件跳过" — inert in feed_cd_counter either way, dropping keeps
   the sequence minimal). Manual events are emitted with is_manual=True
   (透传), which feed_cd_counter treats as inert (§2.3: M1 never enters the
   unique counter).

Run: python3 -m unittest tests.test_mastery_bridge
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from learning_system import mastery_rules as rules

WINDOW_DAYS = 90  # proposal §2.2: "证据窗口 W = 滚动 90 天"

# Contract defaults for the decide_verdict evidence shape (mastery_rules.py
# evidence-shape block); applied when the external row omits the field.
_ELIGIBILITY_DEFAULTS = {
    "gate_passed": True,
    "purpose": "diagnostic",
    "hint_policy": "no_hint",
    "mastery_update_eligible": True,
    "voice_verifiable": True,
    "is_manual": False,
    "analysis_valid": True,
}
_BOOL_FIELDS = tuple(_ELIGIBILITY_DEFAULTS) + ("blocking_evidence",)

_TRUTHY = frozenset({"1", "true", "yes", "t", "y"})
_FALSY = frozenset({"0", "false", "no", "f", "n", "", "none"})


def _as_date(value):
    """Mirror of mastery_rules._as_date (private there): normalize created_at.

    Kept as a local pure copy so the adapter does not reach into a private
    helper; semantics identical: date/datetime passthrough, "YYYY-MM-DD[ T...]"
    strings parsed, anything else raises ValueError.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        head = value.strip()[:10]
        try:
            return datetime.strptime(head, "%Y-%m-%d").date()
        except ValueError:
            pass
    raise ValueError(
        f"created_at must be a date, datetime or 'YYYY-MM-DD' string, got {value!r}"
    )


def _to_bool(value):
    """Coerce DB ints (0/1) and common strings to bool; None -> False.

    Unknown truthy-looking strings are passed through untouched: is_eligible
    requires `is True`, so an uncoerced value makes the event ineligible —
    the safe (under-claiming) direction, consistent with §2.3 升降级不对称.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUTHY:
            return True
        if lowered in _FALSY:
            return False
    return value


def _extract_verdict(row: dict) -> str:
    """Read the unified 5-value verdict from a row (verdict_or_code | verdict)."""
    verdict = row.get("verdict_or_code")
    if verdict is None or verdict == "":
        verdict = row.get("verdict")
    if verdict is None or verdict == "":
        raise ValueError(
            "mastery_decisions row carries no unified verdict: expected "
            "'verdict_or_code' (or alias 'verdict'); legacy enums must be "
            f"converted by the wiring layer, got row {row!r}"
        )
    if verdict not in rules.VERDICTS:
        raise ValueError(
            f"verdict must be one of {sorted(rules.VERDICTS)} (unified 5-value "
            f"enum), got {verdict!r} — legacy enums are refused rather than "
            "silently miscounted"
        )
    return verdict


def normalize_evidence(row: dict) -> dict:
    """Map one external/DB judgment-event row to the decide_verdict shape.

    - field aliases: `id` -> `attempt_id`, `verdict` -> `verdict_or_code`;
    - contract defaults for missing eligibility/evidence fields (defaults are
      the eligible side, matching mastery_rules' evidence-shape defaults);
    - int (0/1) and str ("0"/"1"/"true"/...) -> bool for the boolean fields;
    - `created_at` is required (window ordering / counter chronology need it)
      and passed through as-is; decide_verdict's _as_date handles date/
      datetime/"YYYY-MM-DD" strings.
    Other fields pass through unchanged. Pure: no I/O.
    """
    normalized = dict(row)

    if "created_at" not in normalized or normalized["created_at"] in (None, ""):
        raise ValueError(
            f"judgment-event row must carry a created_at, got {row!r}"
        )

    if "attempt_id" not in normalized and "id" in normalized:
        normalized["attempt_id"] = normalized.pop("id")
    if "verdict_or_code" not in normalized and "verdict" in normalized:
        normalized["verdict_or_code"] = normalized.pop("verdict")

    for field in _BOOL_FIELDS:
        if field in normalized:
            normalized[field] = _to_bool(normalized[field])
        else:
            normalized[field] = _ELIGIBILITY_DEFAULTS.get(field, False)

    normalized.setdefault("next_evidence_need", "")
    return normalized


def is_judgment_event(row: dict) -> bool:
    """§2.2 eligibility applied to one external row (is_eligible after normalize).

    gate_passed / purpose / hint_policy / mastery_update_eligible /
    voice_verifiable / is_manual / analysis_valid — rules.is_eligible is the
    single source of truth; this adapter just bridges the row shape.
    """
    return rules.is_eligible(normalize_evidence(row))


def build_window(rows, current, *, days: int = WINDOW_DAYS) -> list[dict]:
    """Build the rolling eligible evidence window for the current judgment event.

    Args:
        rows: iterable of judgment-event rows (external shape; normalized
            internally) — the node's history as read by the wiring layer.
        current: the judgment-event row being decided. If absent from `rows`
            it is appended first.
        days: window length in days (default WINDOW_DAYS = 90, §2.2).

    Returns:
        The window as a list of *normalized* eligible rows, ascending by
        created_at, clipped to [current.created_at - days, current.created_at]
        (inclusive), including `current` when it is eligible. Directly
        consumable by decide_verdict(evidence, window).

    Interpretation notes: the anchor is the current event's created_at (not
    today) so decisions are deterministic/replayable; ineligible rows —
    including an ineligible `current` — are filtered out per §2.2 judgment-
    event granularity (see module docstring).
    """
    current_norm = normalize_evidence(current)
    anchor = _as_date(current_norm["created_at"])

    entries = [normalize_evidence(r) for r in list(rows)]
    current_attempt_id = current_norm.get("attempt_id")
    if current_attempt_id is None:
        # No attempt_id on current: cannot verify membership, so include it
        # unconditionally (a duplicate malformed row is harmless for AGG).
        entries.append(current_norm)
    elif not any(e.get("attempt_id") == current_attempt_id
                 and _as_date(e["created_at"]) == anchor
                 for e in entries):
        entries.append(current_norm)

    eligible = [e for e in entries if rules.is_eligible(e)]
    lower = anchor - timedelta(days=days)
    window = [
        e for e in eligible
        if lower <= _as_date(e["created_at"]) <= anchor
    ]
    # Stable sort by date only: same-day events keep the wiring layer's input
    # order (which should already be chronological), and rows without an
    # attempt_id cannot break the sort key.
    window.sort(key=lambda e: _as_date(e["created_at"]))
    return window


def to_counter_events(rows) -> list[dict]:
    """Map historical mastery_decisions rows to §2.3 counter event sequences.

    Returns a chronological list of {"verdict", "is_manual"} dicts — exactly
    the event shape cd_counter / feed_cd_counter consume. Per §2.3:
    - ordered by created_at (required on every row; missing raises);
    - NO_CHANGE rows are dropped (跳过: not counted, not breaking the streak);
    - manual marker is passed through (is_manual=True events are inert in the
      counter, M1 never enters the unique counter);
    - the unified 5-value verdict is required (verdict_or_code, alias
      "verdict"); legacy enums raise ValueError (see module docstring note 3).
    """
    ordered = sorted(
        ((_as_date(r.get("created_at")), index, r) for index, r in enumerate(rows)),
        key=lambda entry: (entry[0], entry[1]),
    )
    events = []
    for _, _, row in ordered:
        verdict = _extract_verdict(row)
        if verdict == rules.VERDICT_NO_CHANGE:
            continue
        events.append({
            "verdict": verdict,
            "is_manual": _to_bool(row.get("is_manual", False)) is True,
        })
    return events
