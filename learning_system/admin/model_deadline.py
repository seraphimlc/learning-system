from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Iterator

from .. import model_router


_ADMIN_ABSOLUTE_DEADLINE: ContextVar[float | None] = ContextVar(
    "admin_absolute_deadline_monotonic", default=None
)


@contextmanager
def bind_admin_absolute_deadline(
    absolute_deadline_monotonic: float | None,
) -> Iterator[float | None]:
    if absolute_deadline_monotonic is not None and (
        not math.isfinite(absolute_deadline_monotonic)
        or absolute_deadline_monotonic <= 0
    ):
        raise ValueError("absolute model deadline must be finite and positive")
    token = _ADMIN_ABSOLUTE_DEADLINE.set(absolute_deadline_monotonic)
    try:
        yield absolute_deadline_monotonic
    finally:
        _ADMIN_ABSOLUTE_DEADLINE.reset(token)


def _float_env(names: Iterable[str], default: float) -> float:
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        try:
            parsed = float(value)
        except ValueError:
            return default
        if math.isfinite(parsed) and parsed > 0:
            return parsed
    return default


class AdminStructuredTransportObserver:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []

    def provider_attempt_started(self, context: model_router.StructuredTransportAttemptContext) -> None:
        self.attempts.append(
            {
                "candidate_ordinal": context.candidate_ordinal,
                "endpoint": context.endpoint,
                "structured_json_mode": context.structured_json_mode,
                "request_digest_sha256": context.request_digest_sha256,
                "outcome": "started",
                "started_at_monotonic": time.monotonic(),
            }
        )

    def provider_attempt_finished(
        self,
        context: model_router.StructuredTransportAttemptContext,
        outcome: model_router.StructuredTransportAttemptOutcome,
    ) -> None:
        matching = None
        for attempt in reversed(self.attempts):
            if (
                attempt.get("candidate_ordinal") == context.candidate_ordinal
                and attempt.get("endpoint") == context.endpoint
                and attempt.get("structured_json_mode") == context.structured_json_mode
                and attempt.get("outcome") == "started"
            ):
                matching = attempt
                break
        if matching is None:
            matching = {
                "candidate_ordinal": context.candidate_ordinal,
                "endpoint": context.endpoint,
                "structured_json_mode": context.structured_json_mode,
                "request_digest_sha256": context.request_digest_sha256,
            }
            self.attempts.append(matching)
        matching.update(
            {
                "outcome": outcome.outcome,
                "status_code": outcome.status_code,
                "retry_after_seconds": outcome.retry_after_seconds,
                "response_digest_sha256": outcome.response_digest_sha256,
                "error_class": outcome.error_class,
                "error_message": outcome.error_message,
                "elapsed_seconds": round(time.monotonic() - float(matching.get("started_at_monotonic") or time.monotonic()), 3),
            }
        )
        matching.pop("started_at_monotonic", None)


@contextmanager
def bind_admin_structured_model_deadline(
    *,
    batch_attempt_id: str,
    timeout_envs: Iterable[str],
    default_seconds: float,
    absolute_deadline_monotonic: float | None = None,
) -> Iterator[dict[str, Any]]:
    wall_seconds = _float_env(timeout_envs, default_seconds)
    if not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise ValueError("model wall deadline must be a finite positive number")
    now = time.monotonic()
    configured_deadline = now + wall_seconds
    context_deadline = _ADMIN_ABSOLUTE_DEADLINE.get()
    deadlines = [configured_deadline]
    if context_deadline is not None:
        deadlines.append(context_deadline)
    if absolute_deadline_monotonic is not None:
        deadlines.append(absolute_deadline_monotonic)
    wall_deadline_monotonic = min(deadlines)
    if wall_deadline_monotonic <= now:
        raise model_router.ModelCallError("structured transport wall deadline exhausted")
    observer = AdminStructuredTransportObserver()
    binding = model_router._new_structured_transport_lifecycle_binding(
        batch_attempt_id=batch_attempt_id,
        observer=observer,
        wall_deadline_monotonic=wall_deadline_monotonic,
    )
    meta = {
        "model_wall_deadline_seconds": wall_deadline_monotonic - now,
        "model_wall_deadline_monotonic": wall_deadline_monotonic,
        "transport_attempts": observer.attempts,
    }
    with model_router.bind_structured_transport_lifecycle(binding):
        yield meta
