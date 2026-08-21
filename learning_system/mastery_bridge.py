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

§2.4 follow-up (planner retest scheduling): retest_history maps a node's
mastery_decisions rows (legacy-aware verdict fallback: verdict_or_code ->
decision_payload_json.unified_verdict.verdict trace -> new_status_code) to
the event sequence + anchor date consumed by
mastery_rules.derive_retest_state / mastery_rules.retest_due.

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


def _trace_verdict(row: dict) -> str:
    """The unified verdict recorded in decision_payload_json.unified_verdict.

    The M2.5-5b/5c wiring writes this trace on every stored mastery_decisions
    row (daily_runtime.py:13616-13625 / orchestrator.py:416). Accepts a dict
    or a JSON string (the DB column is TEXT). Returns "" when absent/invalid.
    """
    payload = row.get("decision_payload_json")
    if isinstance(payload, str):
        try:
            import json as _json
            payload = _json.loads(payload)
        except ValueError:
            payload = None
    if isinstance(payload, dict):
        trace = payload.get("unified_verdict")
        if isinstance(trace, dict):
            verdict = trace.get("verdict")
            if verdict in rules.VERDICTS:
                return verdict
    return ""


def _legacy_verdict(row: dict) -> str:
    """Read the unified verdict from a mastery_decisions row (legacy-aware).

    Fallback chain (documented in retest_history): the explicit unified
    field verdict_or_code (alias "verdict") -> the decision_payload_json
    .unified_verdict.verdict trace -> the legacy stored outcome
    new_status_code (A/B/C/D are the unified verdict codes for stored
    outcomes; NO_CHANGE is never stored). Returns "" when none of the three
    carry a usable verdict — retest_history then skips the row (it carries
    no judgment event; real legacy rows often have new_status_code='').
    """
    verdict = _extract_verdict_or_empty(row)
    if verdict:
        return verdict
    verdict = _trace_verdict(row)
    if verdict:
        return verdict
    verdict = row.get("new_status_code")
    if verdict in rules.VERDICTS:
        return verdict
    return ""


def _extract_verdict_or_empty(row: dict) -> str:
    """_extract_verdict without raising ("" when absent/invalid)."""
    verdict = row.get("verdict_or_code")
    if verdict is None or verdict == "":
        verdict = row.get("verdict")
    if verdict is None or verdict == "":
        return ""
    return verdict if verdict in rules.VERDICTS else ""


def retest_history(rows) -> dict:
    """Map mastery_decisions rows to the §2.4 derivation inputs (pure).

    The planner consumes this to gate interval-spaced retests: the verdict
    sequence is derived from the node's append-only mastery_decisions history
    (§2.4 "last_A_event_at / depth / b_count 均可重算推导"), replayed by
    rules.derive_retest_state, and the anchor date feeds rules.retest_due.

    Returns {"events": [...], "last_event_at": date | None}:
    - events: chronological [{"verdict", "is_manual"}] — the exact input
      shape of rules.derive_retest_state (and of to_counter_events);
    - last_event_at: the created_at date of the last event that maps to a
      real judgment event (None for an empty/no-event history).

    Per row the unified verdict is read legacy-aware (see _legacy_verdict):
    verdict_or_code -> payload unified trace -> new_status_code. The trace
    takes priority over new_status_code because the stored outcome can
    differ from the verdict (e.g. a keep-A event stores new_status_code='A'
    while its verdict is B — using the stored outcome would advance depth
    wrongly). Rows with no readable verdict are skipped (not judgment
    events; real legacy rows often carry new_status_code='' — raising there
    would crash plan generation for pre-unified data). NO_CHANGE rows are
    dropped (never stored); the manual marker is passed through
    (derive_retest_state treats manual events as inert).
    """
    ordered = sorted(
        ((_as_date(r.get("created_at")), index, r) for index, r in enumerate(rows)),
        key=lambda entry: (entry[0], entry[1]),
    )
    events = []
    last_event_at = None
    for _, _, row in ordered:
        verdict = _legacy_verdict(row)
        if not verdict or verdict == rules.VERDICT_NO_CHANGE:
            continue
        events.append({
            "verdict": verdict,
            "is_manual": _to_bool(row.get("is_manual", False)) is True,
        })
        last_event_at = _as_date(row["created_at"])
    return {"events": events, "last_event_at": last_event_at}
