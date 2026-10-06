import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app import providers
from app.schemas import Provider

MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello"},
    {"role": "user", "content": "Bye"},
]


def reply(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://provider"))


async def complete(provider, payload, params=None):
    post = AsyncMock(return_value=reply(payload))
    with patch.object(providers.client, "post", post):
        result = await providers.complete(provider, "model-x", MESSAGES, params or {})
    return result, post.call_args


class ProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_request_and_usage(self):
        provider = Provider(id="p", kind="openai_compat", base_url="http://llm/v1/", api_key="secret")
        payload = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 5}}
        (text, usage), call = await complete(provider, payload, {"temperature": 0.2, "unknown": 1, "top_p": None})
        self.assertEqual((text, usage), ("ok", {"total_tokens": 5}))
        self.assertEqual(call.args[0], "http://llm/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(call.kwargs["json"], {"model": "model-x", "messages": MESSAGES, "temperature": 0.2})

    async def test_ollama_uses_configured_default_url(self):
        provider = Provider(id="p", kind="ollama")
        payload = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(providers.settings, "ollama_url", "http://ollama:11434"):
            _, call = await complete(provider, payload)
        self.assertEqual(call.args[0], "http://ollama:11434/v1/chat/completions")

    async def test_anthropic_splits_system_prompt_and_maps_usage(self):
        provider = Provider(id="p", kind="anthropic", api_key="key")
        payload = {
            "content": [{"type": "text", "text": "Hi "}, {"type": "tool_use"}, {"type": "text", "text": "there"}],
            "usage": {"input_tokens": 3, "output_tokens": 4},
        }
        (text, usage), call = await complete(provider, payload, {"max_tokens": 50})
        body = call.kwargs["json"]
        self.assertEqual(text, "Hi there")
        self.assertEqual(usage, {"prompt_tokens": 3, "completion_tokens": 4})
        self.assertEqual(body["system"], "Be brief.")
        self.assertEqual(body["max_tokens"], 50)
        self.assertTrue(all(m["role"] != "system" for m in body["messages"]))
        self.assertEqual(call.kwargs["headers"]["x-api-key"], "key")

    async def test_anthropic_defaults_max_tokens(self):
        provider = Provider(id="p", kind="anthropic")
        payload = {"content": [{"type": "text", "text": "ok"}]}
        _, call = await complete(provider, payload)
        self.assertEqual(call.kwargs["json"]["max_tokens"], 1024)

    async def test_gemini_maps_roles_and_generation_config(self):
        provider = Provider(id="p", kind="gemini", api_key="key")
        payload = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
        }
        (text, usage), call = await complete(provider, payload, {"top_p": 0.9, "max_tokens": 20})
        body = call.kwargs["json"]
        self.assertEqual((text, usage), ("ok", {"prompt_tokens": 2, "completion_tokens": 1}))
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "Be brief."}]})
        self.assertEqual(body["generationConfig"], {"topP": 0.9, "maxOutputTokens": 20})
        self.assertEqual(call.kwargs["params"], {"key": "key"})
        self.assertTrue(call.args[0].endswith("/v1beta/models/model-x:generateContent"))

    async def test_http_errors_propagate(self):
        provider = Provider(id="p", kind="openai")
        post = AsyncMock(return_value=reply({"error": "bad"}, status=429))
        with patch.object(providers.client, "post", post), self.assertRaises(httpx.HTTPStatusError):
            await providers.complete(provider, "model-x", MESSAGES, {})


if __name__ == "__main__":
    unittest.main()
