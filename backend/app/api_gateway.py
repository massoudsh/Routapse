"""OpenAI-compatible data plane. Point any OpenAI SDK at /v1 and use model="router:<id>"."""
import json, time, uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import agents, engine, providers, reqlog
from .auth import gateway_auth
from .config import settings
from .rate_limit import limiter
from .schemas import AgentRunRequest, ChatRequest, Message, Provider
from .store import store

api = APIRouter(prefix="/v1", dependencies=[Depends(gateway_auth)])


def _limit(request: Request):
    client = request.client.host if request.client else "unknown"
    retry_after = limiter.check(client, settings.gateway_rate_limit)
    if retry_after:
        raise HTTPException(429, "gateway rate limit exceeded", headers={"Retry-After": str(retry_after)})



async def _sse(cid: str, model: str, chunks, info):
    def chunk(delta, finish=None, **extra):
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk",
                                      "created": int(time.time()), "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                                      **extra}) + "\n\n"
    yield chunk({"role": "assistant", "content": ""})
    try:
        async for text in chunks:
            yield chunk({"content": text})
    except Exception as e:  # noqa: BLE001 - headers are already sent, so report inside the stream
        detail = str(getattr(e, "detail", None) or type(e).__name__)
        yield "data: " + json.dumps({"error": {"message": detail, "type": "upstream_error"}}) + "\n\n"
        return
    yield chunk({}, "stop", routapse=info)
    yield "data: [DONE]\n\n"


async def _tool_completion(req: ChatRequest, messages: list[dict], params: dict, request: Request, cid: str):
    if req.model.startswith("router:"):
        raise HTTPException(400, "tool calls require a direct model alias")
    model = store.get("models", req.model)
    if not model:
        raise HTTPException(404, f"model '{req.model}' does not exist")
    provider = store.get("providers", model["provider_id"])
    if not provider:
        raise HTTPException(502, f"provider '{model['provider_id']}' does not exist")
    started = time.perf_counter()
    try:
        raw = await providers.openai_chat(Provider.model_validate(provider), model["model_name"], messages, params)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, str(e)) from e
    choice = (raw.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    reqlog.log_event({"source": "gateway", "status": "ok", "requested_model": req.model,
                      "target_model": req.model, "request": {"messages": messages, "params": params},
                      "response": {"text": message.get("content") or "", "usage": raw.get("usage", {})},
                      "latency_ms": round((time.perf_counter() - started) * 1000),
                      "client": request.client.host if request.client else None})
    return JSONResponse({"id": raw.get("id", cid), "object": raw.get("object", "chat.completion"),
                         "created": raw.get("created", int(time.time())), "model": req.model,
                         "choices": raw.get("choices", []), "usage": raw.get("usage", {})},
                        headers={"X-Routapse-Route": "direct", "X-Routapse-Model": req.model})


@api.get("/models")
def list_models():
    ids = [f"router:{r['id']}" for r in store.list("routers")] + [m["id"] for m in store.list("models")]
    return {"object": "list", "data": [{"id": i, "object": "model", "owned_by": "routapse"} for i in ids]}


@api.post("/chat/completions")
async def chat(req: ChatRequest, request: Request, _: None = Depends(_limit)):
    messages = [m.model_dump() for m in req.messages]
    params = {"temperature": req.temperature, "max_tokens": req.max_tokens, "top_p": req.top_p,
              "tools": req.tools, "tool_choice": req.tool_choice}
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    if req.tools:
        if req.stream:
            raise HTTPException(400, "streaming tool calls are not supported")
        return await _tool_completion(req, messages, params, request, cid)
    router = engine.load_router(req.model.split(":", 1)[1]) if req.model.startswith("router:") else None
    meta = {"client": request.client.host if request.client else None, "stream": req.stream}
    if req.stream:
        info, model, chunks = await engine.run_stream("gateway", messages, params, router=router,
                                                      model_id=None if router else req.model, meta=meta)
        shown = model or req.model
        headers = {"X-Routapse-Route": info["label"] if info else "direct", "X-Routapse-Model": shown}
        return StreamingResponse(_sse(cid, shown, chunks, info), media_type="text/event-stream", headers=headers)
    info, out = await engine.run("gateway", messages, params, router=router,
                                 model_id=None if router else req.model, meta=meta)
    shown = out["model"] or req.model
    headers = {"X-Routapse-Route": info["label"] if info else "direct", "X-Routapse-Model": shown}
    return JSONResponse({
        "id": cid, "object": "chat.completion", "created": int(time.time()), "model": shown,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": out["text"]}}],
        "usage": out["usage"], "routapse": info}, headers=headers)


@api.post("/agents/{agent_id}/runs")
async def agent_run(agent_id: str, req: AgentRunRequest, request: Request, _: None = Depends(_limit)):
    started = time.perf_counter()
    try:
        result = await agents.run(agent_id, req.input, req.session_id)
    except HTTPException:
        raise
    except Exception as e:  # SDK errors should retain the gateway's standard HTTP error contract
        raise HTTPException(502, str(e)) from e
    reqlog.log_event({"source": "agent", "agent_id": agent_id, "status": "ok",
                      "request": {"messages": [{"role": "user", "content": req.input}]},
                      "response": {"text": result["output"], "usage": {}}, "trace_id": result["trace_id"],
                      "latency_ms": round((time.perf_counter() - started) * 1000),
                      "client": request.client.host if request.client else None})
    return result


@api.post("/route/{router_id}")
async def route_only(router_id: str, messages: list[Message], request: Request, _: None = Depends(_limit)):
    """Middle-model mode: get the routing decision (and Laya signals) without calling any LLM."""
    if not messages:
        raise HTTPException(400, "messages must not be empty")
    info, _ = await engine.run("gateway-route", [m.model_dump() for m in messages], {},
                               router=engine.load_router(router_id), call_model=False,
                               meta={"client": request.client.host if request.client else None})
    return info
