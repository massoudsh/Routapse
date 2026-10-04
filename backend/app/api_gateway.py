"""OpenAI-compatible data plane. Point any OpenAI SDK at /v1 and use model="router:<id>"."""
import json, time, uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import engine
from .auth import gateway_auth
from .schemas import ChatRequest, Message
from .store import store

api = APIRouter(prefix="/v1", dependencies=[Depends(gateway_auth)])


def _sse(cid: str, model: str, text: str):
    def chunk(delta, finish=None):
        return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk",
                                      "created": int(time.time()), "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
    yield chunk({"role": "assistant", "content": text})
    yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


@api.get("/models")
def list_models():
    ids = [f"router:{r['id']}" for r in store.list("routers")] + [m["id"] for m in store.list("models")]
    return {"object": "list", "data": [{"id": i, "object": "model", "owned_by": "routapse"} for i in ids]}


@api.post("/chat/completions")
async def chat(req: ChatRequest, request: Request):
    messages = [m.model_dump() for m in req.messages]
    params = {"temperature": req.temperature, "max_tokens": req.max_tokens, "top_p": req.top_p}
    router = engine.load_router(req.model.split(":", 1)[1]) if req.model.startswith("router:") else None
    info, out = await engine.run("gateway", messages, params, router=router,
                                 model_id=None if router else req.model,
                                 meta={"client": request.client.host if request.client else None, "stream": req.stream})
    cid, shown = f"chatcmpl-{uuid.uuid4().hex[:24]}", out["model"] or req.model
    headers = {"X-Routapse-Route": info["label"] if info else "direct", "X-Routapse-Model": shown}
    if req.stream:
        return StreamingResponse(_sse(cid, shown, out["text"]), media_type="text/event-stream", headers=headers)
    return JSONResponse({
        "id": cid, "object": "chat.completion", "created": int(time.time()), "model": shown,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": out["text"]}}],
        "usage": out["usage"], "routapse": info}, headers=headers)


@api.post("/route/{router_id}")
async def route_only(router_id: str, messages: list[Message], request: Request):
    """Middle-model mode: get the routing decision (and Laya signals) without calling any LLM."""
    if not messages:
        raise HTTPException(400, "messages must not be empty")
    info, _ = await engine.run("gateway-route", [m.model_dump() for m in messages], {},
                               router=engine.load_router(router_id), call_model=False,
                               meta={"client": request.client.host if request.client else None})
    return info
