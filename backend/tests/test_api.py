import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import providers, reqlog
from app.main import app
from app.store import store
from tests.test_engine import FakeRouterClient, response

PROVIDER = {"id": "local", "kind": "openai_compat", "base_url": "http://llm/v1", "api_key": "secret"}
MODEL = {"id": "fast", "provider_id": "local", "model_name": "llama"}
ROUTER = {
    "id": "support",
    "name": "Support",
    "routes": [
        {"label": "answer", "model_id": "fast"},
        {"label": "refuse", "action": "respond", "response_text": "No."},
    ],
    "fallback_label": "answer",
}
COMPLETION = {"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, name, value in (
            (store, "path", os.path.join(self.tmp.name, "store.json")),
            (reqlog.settings, "log_dir", os.path.join(self.tmp.name, "logs")),
            (reqlog.settings, "log_bodies", True),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        store.put("providers", "local", PROVIDER)
        store.put("models", "fast", MODEL)
        store.put("routers", "support", ROUTER)
        self.client = TestClient(app)

    def classify_as(self, label, confidence=0.9):
        result = {"label": label, "confidence": confidence, "signals": {}, "source": "jev"}
        return patch("app.engine.httpx.AsyncClient", return_value=FakeRouterClient(response(200, json=result)))

    def provider_replies(self):
        reply = httpx.Response(200, json=COMPLETION, request=httpx.Request("POST", "http://llm"))
        return patch.object(providers.client, "post", AsyncMock(return_value=reply))


class GatewayTests(ApiTestCase):
    def test_models_lists_routers_and_models(self):
        ids = [m["id"] for m in self.client.get("/v1/models").json()["data"]]
        self.assertEqual(ids, ["router:support", "fast"])

    def test_router_model_forwards_to_lane_model(self):
        with self.classify_as("answer"), self.provider_replies():
            r = self.client.post("/v1/chat/completions", json={
                "model": "router:support", "messages": [{"role": "user", "content": "hi"}]})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body["choices"][0]["message"]["content"], "hello")
        self.assertEqual(body["model"], "fast")
        self.assertEqual(body["routapse"]["label"], "answer")
        self.assertEqual(r.headers["x-routapse-route"], "answer")

    def test_respond_lane_never_calls_a_provider(self):
        post = AsyncMock()
        with self.classify_as("refuse"), patch.object(providers.client, "post", post):
            r = self.client.post("/v1/chat/completions", json={
                "model": "router:support", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.json()["choices"][0]["message"]["content"], "No.")
        post.assert_not_called()

    def test_direct_model_pass_through(self):
        with self.provider_replies():
            r = self.client.post("/v1/chat/completions", json={
                "model": "fast", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.json()["routapse"], None)
        self.assertEqual(r.headers["x-routapse-route"], "direct")

    def test_stream_sends_single_chunk_then_done(self):
        with self.provider_replies():
            r = self.client.post("/v1/chat/completions", json={
                "model": "fast", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        events = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1], "[DONE]")
        self.assertEqual(json.loads(events[0])["choices"][0]["delta"]["content"], "hello")

    def test_route_only_skips_the_model(self):
        post = AsyncMock()
        with self.classify_as("answer"), patch.object(providers.client, "post", post):
            r = self.client.post("/v1/route/support", json=[{"role": "user", "content": "hi"}])
        self.assertEqual(r.json()["label"], "answer")
        post.assert_not_called()

    def test_unknown_router_and_model_errors(self):
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(self.client.post("/v1/chat/completions", json={
            "model": "router:missing", "messages": messages}).status_code, 404)
        self.assertEqual(self.client.post("/v1/chat/completions", json={
            "model": "missing", "messages": messages}).status_code, 400)

    def test_provider_failure_is_a_logged_502(self):
        reply = httpx.Response(500, text="boom", request=httpx.Request("POST", "http://llm"))
        with patch.object(providers.client, "post", AsyncMock(return_value=reply)):
            r = self.client.post("/v1/chat/completions", json={
                "model": "fast", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(reqlog.read_logs()[0]["status"], "error")

    def test_gateway_key_is_enforced(self):
        with patch("app.auth.settings.gateway_key", "key"):
            self.assertEqual(self.client.get("/v1/models").status_code, 401)
            self.assertEqual(self.client.get("/v1/models", headers={"Authorization": "Bearer key"}).status_code, 200)


class AdminTests(ApiTestCase):
    def test_admin_token_is_enforced(self):
        with patch("app.auth.settings.admin_token", "token"):
            self.assertEqual(self.client.get("/admin/routers").status_code, 401)
            self.assertEqual(self.client.get("/admin/routers", headers={"Authorization": "Bearer token"}).status_code, 200)

    def test_provider_keys_are_masked_and_preserved(self):
        self.assertEqual(self.client.get("/admin/providers").json()[0]["api_key"], "***")
        r = self.client.put("/admin/providers/local", json={**PROVIDER, "api_key": "***", "base_url": "http://new/v1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(store.get("providers", "local")["api_key"], "secret")
        self.assertEqual(store.get("providers", "local")["base_url"], "http://new/v1")

    def test_path_and_body_ids_must_match(self):
        self.assertEqual(self.client.put("/admin/models/other", json=MODEL).status_code, 400)

    def test_model_requires_existing_provider(self):
        r = self.client.put("/admin/models/x", json={**MODEL, "id": "x", "provider_id": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_used_provider_and_model_cannot_be_deleted(self):
        self.assertEqual(self.client.delete("/admin/providers/local").status_code, 409)
        self.assertEqual(self.client.delete("/admin/models/fast").status_code, 409)
        self.assertEqual(self.client.delete("/admin/routers/support").status_code, 200)
        self.assertEqual(self.client.delete("/admin/models/fast").status_code, 200)
        self.assertEqual(self.client.delete("/admin/providers/local").status_code, 200)

    def test_router_validation_over_http(self):
        r = self.client.put("/admin/routers/bad", json={**ROUTER, "id": "bad", "fallback_label": "missing"})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(store.get("routers", "bad"))

    def test_test_endpoint_accepts_unsaved_draft(self):
        with self.classify_as("answer"):
            r = self.client.post("/admin/test", json={"router": ROUTER, "prompt": "hi"})
        self.assertEqual(r.json()["decision"]["label"], "answer")
        self.assertNotIn("response", r.json())

    def test_studio_forced_lane_skips_the_classifier(self):
        r = self.client.post("/admin/chat", json={
            "router_id": "support", "force_label": "refuse", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.json()["response"]["text"], "No.")
        self.assertEqual(r.json()["decision"]["reason"], "lane chosen by hand")

    def test_studio_requires_router_or_model(self):
        r = self.client.post("/admin/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(r.status_code, 400)

    def test_logs_endpoint_returns_recorded_requests(self):
        with self.provider_replies():
            self.client.post("/v1/chat/completions", json={
                "model": "fast", "messages": [{"role": "user", "content": "hi"}]})
        logs = self.client.get("/admin/logs", params={"source": "gateway"}).json()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["target_model"], "fast")
        self.assertEqual(len(self.client.get("/admin/logs/info").json()["files"]), 1)


if __name__ == "__main__":
    unittest.main()
