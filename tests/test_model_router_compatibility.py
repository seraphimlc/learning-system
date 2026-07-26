from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from learning_system import model_router
from learning_system.admin.model_deadline import bind_admin_structured_model_deadline
from learning_system.admin import model_deadline


def _route(*, provider: str, model: str) -> model_router.ModelRoute:
    return model_router.ModelRoute(
        agent_key="compat_test_agent",
        task="compat_test",
        provider=provider,
        model=model,
        model_alias=model,
        base_url="https://api.amux.xyb2b.com/v1",
        api_key="test-key",
        timeout_seconds=30.0,
        model_params={},
    )


def _schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }


class ModelRouterCompatibilityTests(unittest.TestCase):
    def test_explicit_absolute_deadline_is_context_local_across_workers(self) -> None:
        barrier = threading.Barrier(2)
        observed: list[tuple[float, float]] = []

        def worker(offset: float) -> None:
            deadline = time.monotonic() + offset
            with model_deadline.bind_admin_absolute_deadline(deadline):
                barrier.wait()
                with bind_admin_structured_model_deadline(
                    batch_attempt_id=f"worker-{offset}",
                    timeout_envs=(),
                    default_seconds=30.0,
                ) as meta:
                    observed.append((deadline, meta["model_wall_deadline_monotonic"]))

        threads = [threading.Thread(target=worker, args=(offset,)) for offset in (0.5, 2.0)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(2, len(observed))
        for expected, actual in observed:
            self.assertAlmostEqual(expected, actual, delta=0.02)
    def test_provider_schema_omits_unique_items_but_keeps_canonical_contract(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                }
            },
            "required": ["items"],
        }

        formatted = model_router._json_schema_format(schema)

        self.assertNotIn("uniqueItems", formatted["schema"]["properties"]["items"])
        self.assertTrue(schema["properties"]["items"]["uniqueItems"])

    def test_locally_enforces_unique_items_omitted_from_provider_schema(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                }
            },
            "required": ["items"],
        }

        with mock.patch.dict(
            "os.environ",
            {"AI_ENDPOINT_MODE": "responses", "AI_JSON_MODE": "json_schema"},
            clear=True,
        ), mock.patch.object(
            model_router,
            "call_responses",
            return_value={"output_text": '{"items":["same","same"]}'},
        ):
            with self.assertRaisesRegex(
                model_router.ModelJSONParseError,
                "uniqueItems",
            ):
                model_router.call_structured_json(route, {"input": []}, schema=schema)

    def test_deepseek_skips_json_schema_because_provider_does_not_support_it(self) -> None:
        status = model_router.route_status(
            _route(provider="deepseek", model="deepseek-v4-pro-260425")
        ).as_dict()

        self.assertEqual(["json_object", "plain_json"], status["json_modes"])
        self.assertEqual(["responses", "chat_completions"], status["endpoints"])

    def test_glm_uses_chat_first_and_keeps_json_schema_as_preferred_mode(self) -> None:
        status = model_router.route_status(
            _route(provider="openai-compatible", model="zai-org/GLM-5.2")
        ).as_dict()

        self.assertEqual(["json_schema", "json_object", "plain_json"], status["json_modes"])
        self.assertEqual(["chat_completions", "responses"], status["endpoints"])

    def test_429_retries_same_endpoint_and_format_without_candidate_storm(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls: list[dict] = []

        def fake_responses(_route, payload):
            calls.append(payload)
            if len(calls) < 3:
                raise model_router.ModelCallError(
                    "HTTP 429 rate limited",
                    status_code=429,
                    retry_after_seconds=3.0,
                    transport_error_kind="http_status",
                )
            return {"output_text": '{"ok":true}'}

        with mock.patch.dict(
            "os.environ",
            {
                "AI_ENDPOINT_MODE": "responses,chat_completions",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
                "AI_MODEL_TRANSPORT_MAX_RETRIES": "2",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=fake_responses
        ), mock.patch.object(
            model_router, "call_chat_completions"
        ) as chat, mock.patch.object(
            model_router.time, "sleep"
        ) as sleep:
            result = model_router.call_structured_json(
                route, {"input": []}, schema=_schema()
            )

        self.assertEqual({"ok": True}, result.value)
        self.assertEqual(3, len(calls))
        self.assertTrue(
            all(call["text"]["format"]["type"] == "json_schema" for call in calls)
        )
        chat.assert_not_called()
        self.assertEqual([mock.call(3.0), mock.call(3.0)], sleep.call_args_list)

    def test_5xx_exhaustion_does_not_walk_json_format_candidates(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls: list[dict] = []

        def unavailable(_route, payload):
            calls.append(payload)
            raise model_router.ModelCallError(
                "HTTP 503 temporarily unavailable",
                status_code=503,
                transport_error_kind="http_status",
            )

        with mock.patch.dict(
            "os.environ",
            {
                "AI_ENDPOINT_MODE": "responses,chat_completions",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
                "AI_MODEL_TRANSPORT_MAX_RETRIES": "1",
                "AI_MODEL_TRANSPORT_RETRY_BASE_SECONDS": "0",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=unavailable
        ), mock.patch.object(
            model_router, "call_chat_completions"
        ) as chat, mock.patch.object(
            model_router.time, "sleep"
        ):
            with self.assertRaisesRegex(model_router.ModelCallError, "HTTP 503"):
                model_router.call_structured_json(
                    route, {"input": []}, schema=_schema()
                )

        self.assertEqual(2, len(calls))
        self.assertTrue(
            all(call["text"]["format"]["type"] == "json_schema" for call in calls)
        )
        chat.assert_not_called()

    def test_connection_timeout_retries_current_lane_only(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls: list[dict] = []

        def timeout(_route, payload):
            calls.append(payload)
            raise model_router.ModelCallError(
                "connection timed out",
                transport_error_kind="timeout",
            )

        with mock.patch.dict(
            "os.environ",
            {
                "AI_ENDPOINT_MODE": "responses,chat_completions",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
                "AI_MODEL_TRANSPORT_MAX_RETRIES": "1",
                "AI_MODEL_TRANSPORT_RETRY_BASE_SECONDS": "0",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=timeout
        ), mock.patch.object(
            model_router, "call_chat_completions"
        ) as chat, mock.patch.object(
            model_router.time, "sleep"
        ):
            with self.assertRaisesRegex(model_router.ModelCallError, "timed out"):
                model_router.call_structured_json(
                    route, {"input": []}, schema=_schema()
                )

        self.assertEqual(2, len(calls))
        chat.assert_not_called()

    def test_explicit_response_format_unsupported_still_falls_back(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls: list[dict] = []

        def fake_responses(_route, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise model_router.ModelCallError(
                    "HTTP 400 response_format.type json_schema is not supported",
                    status_code=400,
                )
            return {"output_text": '{"ok":true}'}

        with mock.patch.dict(
            "os.environ",
            {
                "AI_ENDPOINT_MODE": "responses",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=fake_responses
        ), mock.patch.object(model_router.time, "sleep") as sleep:
            result = model_router.call_structured_json(
                route, {"input": []}, schema=_schema()
            )

        self.assertEqual({"ok": True}, result.value)
        self.assertEqual("json_object", result.mode)
        self.assertEqual("json_schema", calls[0]["text"]["format"]["type"])
        self.assertEqual("json_object", calls[1]["text"]["format"]["type"])
        sleep.assert_not_called()

    def test_invalid_schema_error_is_terminal_not_a_format_fallback(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls: list[dict] = []

        def invalid_schema(_route, payload):
            calls.append(payload)
            raise model_router.ModelCallError(
                "HTTP 400 invalid json_schema: required fields do not match properties",
                status_code=400,
            )

        with mock.patch.dict(
            "os.environ",
            {
                "AI_ENDPOINT_MODE": "responses",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=invalid_schema
        ):
            with self.assertRaisesRegex(model_router.ModelCallError, "invalid json_schema"):
                model_router.call_structured_json(
                    route, {"input": []}, schema=_schema()
                )

        self.assertEqual(1, len(calls))
        self.assertEqual("json_schema", calls[0]["text"]["format"]["type"])

    def test_retry_after_cannot_push_transport_past_admin_deadline(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")

        def rate_limited(_route, _payload):
            raise model_router.ModelCallError(
                "HTTP 429 rate limited",
                status_code=429,
                retry_after_seconds=30.0,
                transport_error_kind="http_status",
            )

        with mock.patch.dict(
            "os.environ",
            {
                "TEST_MODEL_WALL_SECONDS": "0.05",
                "AI_ENDPOINT_MODE": "responses",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
                "AI_MODEL_TRANSPORT_MAX_RETRIES": "2",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=rate_limited
        ) as call, mock.patch.object(model_router.time, "sleep") as sleep:
            with bind_admin_structured_model_deadline(
                batch_attempt_id="compat-deadline",
                timeout_envs=("TEST_MODEL_WALL_SECONDS",),
                default_seconds=1.0,
            ):
                with self.assertRaisesRegex(
                    model_router.ModelCallError, "deadline"
                ):
                    model_router.call_structured_json(
                        route, {"input": []}, schema=_schema()
                    )

        self.assertEqual(1, call.call_count)
        sleep.assert_not_called()

    def test_admin_deadline_rejects_infinite_environment_value(self) -> None:
        with mock.patch.dict(
            "os.environ", {"TEST_MODEL_WALL_SECONDS": "inf"}, clear=True
        ):
            with bind_admin_structured_model_deadline(
                batch_attempt_id="compat-finite-deadline",
                timeout_envs=("TEST_MODEL_WALL_SECONDS",),
                default_seconds=0.25,
            ) as meta:
                self.assertEqual(0.25, meta["model_wall_deadline_seconds"])

    def test_admin_observer_records_each_retry_on_the_same_candidate(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        calls = 0

        def transient(_route, _payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise model_router.ModelCallError(
                    "HTTP 502 bad gateway",
                    status_code=502,
                    transport_error_kind="http_status",
                )
            return {"output_text": '{"ok":true}'}

        with mock.patch.dict(
            "os.environ",
            {
                "TEST_MODEL_WALL_SECONDS": "1",
                "AI_ENDPOINT_MODE": "responses",
                "AI_JSON_MODE": "json_schema,json_object,plain_json",
                "AI_MODEL_TRANSPORT_MAX_RETRIES": "1",
                "AI_MODEL_TRANSPORT_RETRY_BASE_SECONDS": "0",
            },
            clear=True,
        ), mock.patch.object(
            model_router, "call_responses", side_effect=transient
        ):
            with bind_admin_structured_model_deadline(
                batch_attempt_id="compat-observer",
                timeout_envs=("TEST_MODEL_WALL_SECONDS",),
                default_seconds=1.0,
            ) as meta:
                result = model_router.call_structured_json(
                    route, {"input": []}, schema=_schema()
                )

        self.assertEqual({"ok": True}, result.value)
        self.assertEqual(2, len(meta["transport_attempts"]))
        self.assertEqual(
            [0, 0],
            [attempt["candidate_ordinal"] for attempt in meta["transport_attempts"]],
        )
        self.assertEqual(
            ["json_schema", "json_schema"],
            [attempt["structured_json_mode"] for attempt in meta["transport_attempts"]],
        )
        self.assertEqual(
            ["retryable_failure", "response_received"],
            [attempt["outcome"] for attempt in meta["transport_attempts"]],
        )

    def test_route_concurrency_limit_is_enforced_while_waiting_within_deadline(self) -> None:
        route = _route(provider="openai", model="gpt-5.5")
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first_worker() -> None:
            with model_router._acquire_model_route_slot(route, wall_timeout_seconds=1.0):
                first_entered.set()
                release_first.wait(1.0)

        def second_worker() -> None:
            first_entered.wait(1.0)
            with model_router._acquire_model_route_slot(route, wall_timeout_seconds=1.0):
                second_entered.set()

        with mock.patch.dict(
            "os.environ", {"AI_MODEL_ROUTE_MAX_CONCURRENCY": "1"}, clear=True
        ):
            first = threading.Thread(target=first_worker)
            second = threading.Thread(target=second_worker)
            first.start()
            second.start()
            self.assertTrue(first_entered.wait(1.0))
            self.assertFalse(second_entered.wait(0.05))
            release_first.set()
            first.join(1.0)
            second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(second_entered.is_set())


if __name__ == "__main__":
    unittest.main()
