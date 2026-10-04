"""Provider adapters. Every adapter returns (text, usage)."""
import httpx

from .config import settings
from .schemas import Provider

client = httpx.AsyncClient(timeout=120)
PARAMS = ("temperature", "max_tokens", "top_p")


def _split_system(messages: list[dict]):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    return system, [m for m in messages if m["role"] != "system"]


async def _openai_like(p: Provider, model: str, messages, params):
    if p.kind == "ollama":
        base = (p.base_url or settings.ollama_url).rstrip("/") + "/v1"
    else:
        base = (p.base_url or "https://api.openai.com/v1").rstrip("/")
    r = await client.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {p.api_key or 'none'}"},
        json={"model": model, "messages": messages, **params},
    )
    r.raise_for_status()
    d = r.json()
    return d["choices"][0]["message"]["content"], d.get("usage", {})


async def _anthropic(p: Provider, model: str, messages, params):
    system, msgs = _split_system(messages)
    body = {"model": model, "messages": msgs, "max_tokens": params.get("max_tokens", 1024)}
    if system:
        body["system"] = system
    for k in ("temperature", "top_p"):
        if k in params:
            body[k] = params[k]
    r = await client.post(
        (p.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
        headers={"x-api-key": p.api_key, "anthropic-version": "2023-06-01"},
        json=body,
    )
    r.raise_for_status()
    d = r.json()
    text = "".join(b.get("text", "") for b in d["content"] if b["type"] == "text")
    u = d.get("usage", {})
    return text, {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}


async def _gemini(p: Provider, model: str, messages, params):
    system, msgs = _split_system(messages)
    body = {"contents": [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in msgs]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    cfg = {}
    if "temperature" in params: cfg["temperature"] = params["temperature"]
    if "top_p" in params: cfg["topP"] = params["top_p"]
    if "max_tokens" in params: cfg["maxOutputTokens"] = params["max_tokens"]
    if cfg:
        body["generationConfig"] = cfg
    base = (p.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
    r = await client.post(f"{base}/v1beta/models/{model}:generateContent",
                          params={"key": p.api_key}, json=body)
    r.raise_for_status()
    d = r.json()
    text = "".join(x.get("text", "") for x in d["candidates"][0]["content"]["parts"])
    u = d.get("usageMetadata", {})
    return text, {"prompt_tokens": u.get("promptTokenCount"), "completion_tokens": u.get("candidatesTokenCount")}


async def complete(p: Provider, model: str, messages: list[dict], params: dict):
    params = {k: v for k, v in params.items() if k in PARAMS and v is not None}
    fn = {"anthropic": _anthropic, "gemini": _gemini}.get(p.kind, _openai_like)
    return await fn(p, model, messages, params)
