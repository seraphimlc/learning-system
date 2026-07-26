import base64
import hashlib
import http.client
import json
import os
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from learning_system import (
    auto_review,
    daily_runtime,
    db,
    model_router,
    multimodal_evidence,
    server,
    test_support,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InputRecognitionAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_dir = tempfile.TemporaryDirectory()
        cls._seed_path = Path(cls._seed_dir.name) / "input-recognition-seed.sqlite"
        conn = db.connect(cls._seed_path)
        try:
            db.init_schema(conn)
            db.seed_from_assets(conn, PROJECT_ROOT)
            test_support.seed_runtime_test_question_bank(conn, PROJECT_ROOT)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._seed_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "input-recognition.sqlite"
        shutil.copy2(self._seed_path, self.db_path)
        self.env = mock.patch.dict(
            os.environ,
            {
                "V3_DAILY_RUNTIME_ENABLED": "1",
                "ANSWER_ASSESSMENT_POLICY": "",
                "KNOWLEDGE_MAP_HOME_POLICY": "",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        conn = db.connect(self.db_path)
        try:
            started = daily_runtime.DailyLearningRuntime(
                conn,
                project_root=PROJECT_ROOT,
            ).start_review_mode(
                client_day_key=f"2099-09-01-input-recognition-{id(self)}"
            )
            self.step = started["current_step"]
            self.step_row = dict(
                conn.execute(
                    "select * from flow_steps where step_handle = ? and position = ?",
                    (self.step["step_handle"], self.step["position"]),
                ).fetchone()
            )
        finally:
            conn.close()

        self.httpd, self.base_url = server.start_test_server(self.db_path)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmpdir.cleanup()

    def test_handwriting_endpoint_persists_current_step_bound_opaque_run(self):
        image_bytes = b"\x89PNG\r\n\x1a\nhandwriting-api"
        recognition = {
            "status": "usable",
            "confidence": 0.97,
            "transcript": "-3",
            "math_tokens": ["-", "3"],
            "critical_token_uncertainties": [],
            "notes": "",
        }
        route = self._enabled_handwriting_route()

        with mock.patch.object(
            auto_review,
            "recognize_handwriting_input",
            return_value=recognition,
        ), mock.patch.object(
            model_router,
            "answer_photo_vision_route",
            return_value=route,
        ):
            first = self._request_json(
                "POST",
                "/api/input-recognition/handwriting",
                self._handwriting_payload(image_bytes),
            )
            replay = self._request_json(
                "POST",
                "/api/input-recognition/handwriting",
                self._handwriting_payload(image_bytes),
            )

        self.assertEqual(200, first["status"], first["raw"])
        self.assertEqual("ready", first["body"]["status"])
        self.assertEqual("-3", first["body"]["recognized_text"])
        self.assertTrue(first["body"]["confirmation_required"])
        handle = first["body"]["recognition_handle"]
        self.assertRegex(handle, r"^MR-[0-9a-f]{12}$")
        self.assertEqual(handle, replay["body"]["recognition_handle"])
        self.assertNotIn(self.step_row["id"], handle)
        self.assertNotIn(self.step_row["question_id"], handle)
        self.assertNotIn(hashlib.sha256(image_bytes).hexdigest(), handle)
        self._assert_child_safe(first["body"])

        with closing(db.connect(self.db_path)) as conn:
            run = db.get_media_recognition_run(conn, handle)
            self.assertEqual(self.step_row["id"], run["flow_step_id"])
            self.assertEqual(self.step_row["step_revision"], run["step_revision"])
            self.assertEqual(self.step_row["question_id"], run["question_id"])
            self.assertEqual("handwriting", run["input_mode"])
            self.assertEqual(hashlib.sha256(image_bytes).hexdigest(), run["media_sha256"])
            self.assertEqual(len(image_bytes), run["media_byte_size"])
            self.assertEqual(multimodal_evidence.MEDIA_VERSION, run["media_version"])
            self.assertEqual("-3", run["recognized_text"])
            self.assertTrue(run["output_digest_sha256"])
            self.assertEqual(1, conn.execute(
                "select count(*) from media_recognition_runs where id = ?",
                (handle,),
            ).fetchone()[0])

    def test_stale_step_rejects_handwriting_without_model_call_or_run(self):
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "update flow_steps set status = 'completed' where id = ?",
                (self.step_row["id"],),
            )
            conn.commit()

        with mock.patch.object(auto_review, "recognize_handwriting_input") as recognize:
            response = self._request_json(
                "POST",
                "/api/input-recognition/handwriting",
                self._handwriting_payload(b"\x89PNG\r\n\x1a\nstale-step"),
            )

        self.assertEqual(409, response["status"], response["raw"])
        self.assertEqual("stale_step", response["body"]["status"])
        recognize.assert_not_called()
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(0, conn.execute("select count(*) from media_recognition_runs").fetchone()[0])

    def test_handwriting_handle_rejects_different_media_on_submission(self):
        original = b"\x89PNG\r\n\x1a\noriginal-handwriting"
        changed = b"\x89PNG\r\n\x1a\nchanged-handwriting"
        route = self._enabled_handwriting_route()
        recognition = {
            "status": "usable",
            "confidence": 0.95,
            "transcript": "-3",
            "math_tokens": ["-3"],
            "critical_token_uncertainties": [],
            "notes": "",
        }
        with mock.patch.object(
            auto_review,
            "recognize_handwriting_input",
            return_value=recognition,
        ), mock.patch.object(
            model_router,
            "answer_photo_vision_route",
            return_value=route,
        ):
            recognized = self._request_json(
                "POST",
                "/api/input-recognition/handwriting",
                self._handwriting_payload(original),
            )

        response = self._request_json(
            "POST",
            "/api/current-step/submit",
            {
                "step_handle": self.step["step_handle"],
                "position": self.step["position"],
                "client_idempotency_key": "handwriting-media-mismatch",
                "answer_text": "-3",
                "handwriting_image_data_url": self._data_url("image/png", changed),
                "handwriting_image_name": "answer.png",
                "input_evidence": {
                    "schema_version": multimodal_evidence.INPUT_EVIDENCE_SCHEMA_VERSION,
                    "input_mode": "handwriting",
                    "recognition_status": "confirmed",
                    "recognition_handle": recognized["body"]["recognition_handle"],
                    "recognized_text": "-3",
                    "recognition_confidence": 0.95,
                    "critical_token_uncertainties": [],
                    "media_version": multimodal_evidence.MEDIA_VERSION,
                    "child_confirmed": True,
                    "child_confirmed_text": "-3",
                },
            },
        )

        self.assertEqual(409, response["status"], response["raw"])
        self._assert_child_safe(response["body"])
        with closing(db.connect(self.db_path)) as conn:
            self.assertEqual(0, conn.execute(
                "select count(*) from attempts where client_idempotency_key = ?",
                ("handwriting-media-mismatch",),
            ).fetchone()[0])

    def test_voice_endpoint_persists_browser_transcript_and_raw_audio_identity(self):
        audio_bytes = b"focused-browser-audio"
        response = self._request_json(
            "POST",
            "/api/input-recognition/voice",
            {
                "step_handle": self.step["step_handle"],
                "position": self.step["position"],
                "voice_audio_data_url": self._data_url("audio/webm", audio_bytes),
                "recognized_text": "负三",
                "recognition_confidence": 0.88,
            },
        )

        self.assertEqual(200, response["status"], response["raw"])
        self.assertEqual("ready", response["body"]["status"])
        self.assertEqual("负三", response["body"]["recognized_text"])
        self.assertTrue(response["body"]["confirmation_required"])
        handle = response["body"]["recognition_handle"]
        self.assertRegex(handle, r"^MR-[0-9a-f]{12}$")
        self._assert_child_safe(response["body"])

        with closing(db.connect(self.db_path)) as conn:
            run = db.get_media_recognition_run(conn, handle)
            self.assertEqual(self.step_row["id"], run["flow_step_id"])
            self.assertEqual(self.step_row["step_revision"], run["step_revision"])
            self.assertEqual(self.step_row["question_id"], run["question_id"])
            self.assertEqual("voice", run["input_mode"])
            self.assertEqual(hashlib.sha256(audio_bytes).hexdigest(), run["media_sha256"])
            self.assertEqual(len(audio_bytes), run["media_byte_size"])
            self.assertEqual(multimodal_evidence.VOICE_RECOGNIZER_VERSION, run["recognizer_version"])
            self.assertEqual("browser_speech_recognition", run["recognition_source"])
            self.assertEqual("负三", run["recognized_text"])
            self.assertAlmostEqual(0.88, run["recognition_confidence"])
            self.assertTrue(run["route_digest_sha256"])
            self.assertTrue(run["output_digest_sha256"])

    def test_stale_step_rejects_voice_without_persisting_run(self):
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "update flow_steps set step_revision = step_revision + 1, status = 'completed' where id = ?",
                (self.step_row["id"],),
            )
            conn.commit()

        response = self._request_json(
            "POST",
            "/api/input-recognition/voice",
            {
                "step_handle": self.step["step_handle"],
                "position": self.step["position"],
                "voice_audio_data_url": self._data_url("audio/webm", b"stale-voice"),
                "recognized_text": "负三",
            },
        )

        self.assertEqual(409, response["status"], response["raw"])
        self.assertEqual("stale_step", response["body"]["status"])
        self._assert_child_safe(response["body"])
        with db.connect(self.db_path) as conn:
            self.assertEqual(0, conn.execute("select count(*) from media_recognition_runs").fetchone()[0])

    def _handwriting_payload(self, image_bytes):
        return {
            "step_handle": self.step["step_handle"],
            "position": self.step["position"],
            "handwriting_image_data_url": self._data_url("image/png", image_bytes),
        }

    @staticmethod
    def _enabled_handwriting_route():
        return model_router.ModelRoute(
            agent_key="answer_analysis_agent",
            task="answer_photo_vision",
            provider="openai",
            model="gpt-5.5",
            model_alias="gpt-5.5",
            base_url="https://unit.invalid/v1",
            api_key="test-only",
            timeout_seconds=30,
            model_params={"temperature": 0},
        )

    def _request_json(self, method, path, payload=None):
        host, port = self.base_url.replace("http://", "").split(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            return {"status": response.status, "body": json.loads(raw), "raw": raw}
        finally:
            conn.close()

    def _assert_child_safe(self, payload):
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in (
            "provider",
            "model",
            "queue",
            "job_id",
            "attempt_id",
            "question_id",
            "flow_id",
            "flow_step_id",
            "route_digest",
            "output_digest",
            "media_sha256",
            "media_byte_size",
            "recognizer_version",
        ):
            self.assertNotIn(forbidden, serialized)

    @staticmethod
    def _data_url(content_type, data):
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{content_type};base64,{encoded}"


if __name__ == "__main__":
    unittest.main()
