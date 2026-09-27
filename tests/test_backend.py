"""Offline API regression tests. Run: python -m unittest discover -s tests -v."""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PNG = b"\x89PNG\r\n\x1a\n" + b"local-test-fixture"


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="listok-api-test-")
        cls.repo = Path(cls.tmp.name) / "repo"
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source, cls.repo, ignore=shutil.ignore_patterns(
            ".env", ".local-certs", ".git", "__pycache__", "*.db", "uploads",
            "generated", ".venv"))
        cls.env = patch.dict(os.environ, {
            "GIGACHAT_CREDENTIALS": "dummy-offline-test",
            "GIGACHAT_MODEL": "GigaChat-3-Ultra",
            "GIGACHAT_CA_BUNDLE_FILE": "",
        })
        cls.env.start()
        cls.network = patch("socket.socket.connect",
                            side_effect=AssertionError("Network is disabled in tests"))
        cls.network.start()
        spec = importlib.util.spec_from_file_location("local_test_launcher", cls.repo / "run_local.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        cls.app = launcher.load_application(cls.repo)
        cls.backend = sys.modules["worksheet_local_backend"]
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.generated = Path(cls.backend.latex_engine.OUTPUT_DIR)
        cls.generated.mkdir(parents=True, exist_ok=True)
        (cls.generated / "route-fixture.pdf").write_bytes(b"%PDF-1.4\nfixture")
        (cls.generated / "secret.log").write_text("not downloadable")
        cls.png = lambda _: (io.BytesIO(PNG), "photo.png")

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def test_01_home(self):
        with self.client.get("/") as response:
            self.assertEqual(response.status_code, 200)

    def test_02_script(self):
        with self.client.get("/script.js") as response:
            self.assertEqual(response.status_code, 200)

    def test_03_styles(self):
        with self.client.get("/style.css") as response:
            self.assertEqual(response.status_code, 200)

    def test_04_history(self):
        self.assertEqual(self.client.get("/api/history").status_code, 200)

    def test_05_history_alias(self):
        self.assertEqual(self.client.get("/worksheet-api/history").status_code, 200)

    def test_06_empty_upload(self):
        self.assertEqual(self.client.post("/worksheet-api/process").status_code, 400)

    def test_07_empty_compile(self):
        self.assertEqual(self.client.post("/worksheet-api/compile", json={}).status_code, 400)

    def test_08_no_debug(self):
        response = self.client.get("/api/debug-env")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"cred_", response.data)

    def test_09_no_debug_alias(self):
        response = self.client.get("/worksheet-api/debug-env")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"cred_", response.data)

    def test_10_pdf(self):
        response = self.client.get("/api/generated/route-fixture.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))
        response.close()

    def test_11_pdf_alias(self):
        response = self.client.get("/worksheet-api/generated/route-fixture.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))
        response.close()

    def test_status_does_not_expose_credentials(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["ai_ready"])
        self.assertFalse(response.json["ai_connection_verified"])
        self.assertEqual(response.json["ai_model"], "GigaChat-3-Ultra")
        self.assertIsInstance(response.json["latex_ready"], bool)
        self.assertNotIn(b"dummy-offline-test", response.data)

    def test_manual_examples_are_explicit(self):
        for subject in ("math", "physics"):
            with self.subTest(subject=subject):
                result = self.client.get("/api/demo?subject=" + subject)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["source"], "manual_demo")
                self.assertTrue(result.json["requires_review"])
                self.assertEqual(result.json["latex_code"].count(r"\TaskBox{"), 3)
        self.assertEqual(self.client.get("/api/demo?subject=other").status_code, 400)

    def test_upload_configuration_missing(self):
        response = self.client.post("/api/process", data={"files": self.png()})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "ai_not_configured")
        self.assertNotIn("latex_code", response.json)

    def test_unconfigured_model_cannot_override_server(self):
        result = self.client.post("/api/process", data={"files": self.png(), "model": "OtherModel"})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.json["code"], "unsupported_model")
        result = self.client.post("/api/generate_similar", data={"original_text": "x", "model": "OtherModel"})
        self.assertEqual(result.status_code, 400)

    def test_upload_types(self):
        for body, name, code in ((b"%PDF", "input.pdf", "pdf_not_supported"),
                                  (b"plain", "input.png", "invalid_image"),
                                  (b"plain", "input.exe", "unsupported_file_type")):
            with self.subTest(name=name):
                result = self.client.post("/api/process", data={"files": (io.BytesIO(body), name)})
                self.assertEqual(result.status_code, 415)
                self.assertEqual(result.json["code"], code)

    def test_upload_limits(self):
        response = self.client.post("/api/process", data={"files": [self.png() for _ in range(11)]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "too_many_files")
        response = self.client.post("/api/process", data={"files": (io.BytesIO(PNG + b"0" * (20 * 1024 * 1024)), "big.png")})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json["code"], "upload_too_large")

    def test_upload_cleanup_and_error_status(self):
        paths_seen = []
        def fail(paths, **kwargs):
            self.assertTrue(all(Path(p).is_file() for p in paths))
            self.assertEqual(len(set(paths)), 2)
            paths_seen.extend(paths)
            raise self.backend.AIServiceError("Provider unavailable", "ai_provider_error", 502)
        with patch.object(self.backend, "get_ai_status", return_value={
            "ai_ready": True, "ai_configured": True, "ai_model": "GigaChat-3-Ultra"
        }), patch.object(self.backend, "process_image_with_gigachat", side_effect=fail):
            response = self.client.post("/api/process", data={"files": [self.png(), self.png()]})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("latex_code", response.json)
        self.assertTrue(paths_seen)
        self.assertFalse(any(Path(p).exists() for p in paths_seen))

    def test_successful_upload_is_draft_and_cleans_source(self):
        seen = []
        def generate(paths, **kwargs):
            seen.extend(paths)
            return self.backend.DEMOS["math"]["latex_code"]
        with patch.object(self.backend, "get_ai_status", return_value={
            "ai_ready": True, "ai_configured": True, "ai_model": "GigaChat-3-Ultra"
        }), patch.object(self.backend, "process_image_with_gigachat", side_effect=generate):
            result = self.client.post("/api/process", data={"files": self.png()})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["requires_review"])
        self.assertEqual(result.json["source"], "ai_draft")
        self.assertFalse(any(Path(p).exists() for p in seen))

    def test_compile_validation(self):
        for payload in ([], {"latex_code": ""}, {"latex_code": "x", "layout": "3col"},
                        {"latex_code": "x", "layout": []},
                        {"latex_code": "x", "topic": {}}, {"latex_code": "x", "is_variant2": "false"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/compile", json=payload).status_code, 400)

    def test_compile_unavailable_or_failed(self):
        with patch.object(self.backend, "_compiler", return_value=None):
            result = self.client.post("/api/compile", json={"latex_code": "x"})
            self.assertEqual(result.status_code, 503)
        with patch.object(self.backend, "_compiler", return_value="compiler"), \
             patch.object(self.backend.latex_engine, "compile_latex", return_value=(None, None, "Bad LaTeX")):
            result = self.client.post("/api/compile", json={"latex_code": "x"})
            self.assertEqual(result.status_code, 422)
            self.assertNotIn("pdf_url", result.json)

    def test_similar_validation_and_missing_key(self):
        self.assertEqual(self.client.post("/api/generate_similar").status_code, 400)
        self.assertEqual(self.client.post("/api/generate_similar", data={"original_text": "x", "difficulty": "invalid"}).status_code, 400)
        response = self.client.post("/api/generate_similar", data={"original_text": "x"})
        self.assertEqual(response.status_code, 503)

    def test_no_arbitrary_generated_download(self):
        for path in ("/api/generated/secret.log", "/api/generated/../worksheets.db"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_invalid_limits(self):
        for limit in ("abc", "0", "101"):
            self.assertEqual(self.client.get("/api/history?limit=" + limit).status_code, 400)
        for count in ("0", "7", "bad"):
            self.assertEqual(self.client.post("/api/process", data={"files": self.png(), "task_count": count}).status_code, 400)

    def test_provider_response_is_not_successful_error_text(self):
        from utils.gigachat_client import clean_latex, AIServiceError, _format_rules
        for body in ("Error: upstream failed", "", "unstructured answer"):
            with self.assertRaises(AIServiceError):
                clean_latex(body)
        self.assertIn(r"\WriteField{150mm}", _format_rules(1, "math"))
        self.assertIn(r"\WriteField{35mm}", _format_rules(3, "physics"))

    def test_unexpected_error_is_json_without_details(self):
        with patch.object(self.backend, "process_image_with_gigachat", side_effect=RuntimeError("PRIVATE_DETAILS")), \
             patch.object(self.backend, "get_ai_status", return_value={"ai_ready": True, "ai_model": "GigaChat-3-Ultra"}):
            response = self.client.post("/api/process", data={"files": self.png()})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json["code"], "internal_error")
        self.assertNotIn(b"PRIVATE_DETAILS", response.data)


if __name__ == "__main__":
    unittest.main()
