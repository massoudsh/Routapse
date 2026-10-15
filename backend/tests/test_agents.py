import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import agents as agent_runtime
from app.main import app
from app.schemas import AgentDef
from app.store import store


MODEL = {"id": "fast", "provider_id": "local", "model_name": "llama"}
AGENT = {"id": "support", "name": "Support", "model_id": "fast", "instructions": "Help customers."}


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "store.json")
        patcher = patch.object(store, "path", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        store.put("models", "fast", MODEL)
        store.put("agents", "support", AGENT)

    async def test_run_uses_the_registered_model_and_returns_trace_id(self):
        result = SimpleNamespace(final_output="done", last_agent=SimpleNamespace(name="Support"))
        with patch.object(agent_runtime.settings, "agent_gateway_url", "http://gateway:8000/v1"), patch.object(
                agent_runtime.Runner, "run", AsyncMock(return_value=result)) as run:
            output = await agent_runtime.run("support", "hello")
        self.assertEqual(output["output"], "done")
        self.assertEqual(output["agent"], "Support")
        self.assertTrue(output["trace_id"])
        self.assertEqual(run.call_args.kwargs["max_turns"], 10)

    async def test_invalid_session_id_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            await agent_runtime.run("support", "hello", "../../bad")
        self.assertEqual(error.exception.status_code, 400)

    async def test_missing_gateway_url_is_rejected_before_a_run(self):
        with patch.object(agent_runtime.settings, "agent_gateway_url", ""):
            with self.assertRaises(HTTPException) as error:
                await agent_runtime.run("support", "hello")
        self.assertEqual(error.exception.status_code, 503)

    async def test_guardrail_matches_case_insensitively(self):
        guardrail = agent_runtime._terms_guardrail(["secret"], "input")
        result = await guardrail(None, None, "No SECRET here")
        self.assertTrue(result.tripwire_triggered)
        self.assertEqual(result.output_info["matched"], "secret")


class AgentApiTests(unittest.TestCase):
    def test_run_endpoint_returns_agent_result(self):
        client = TestClient(app)
        result = {"output": "done", "agent": "Support", "trace_id": "trace", "session_id": "s1"}
        with patch("app.api_gateway.agents.run", AsyncMock(return_value=result)), patch("app.api_gateway.reqlog.log_event") as log:
            response = client.post("/v1/agents/support/runs", json={"input": "hello", "session_id": "s1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        self.assertEqual(log.call_args.args[0]["trace_id"], "trace")


if __name__ == "__main__":
    unittest.main()
