"""Router sidecar: turns (prompt + labelled routes [+ signals]) into one chosen label.

Both router models speak the same "questions" format (state + questions -> answers):
- Laya runs IN-PROCESS through its Python package: Router().predict(state, questions).
- Jev is a hosted HTTP API (JEV_KIND=systemone): POST {state, model, questions}.
  Ollama and OpenAI-compatible servers are also supported for Jev (JEV_KIND=ollama | openai_compat),
  but those can only choose a lane: signals are ignored.
Besides the routing choice, the questions API can answer extra "signals" in the same call.
If a router model fails, a keyword heuristic answers so the gateway never hard-fails.
"""
import json, os, re, time
from typing import Any, Literal

import httpx
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

app = FastAPI(title="Routapse router sidecar")
TIMEOUT = float(os.getenv("ROUTER_TIMEOUT", "15"))
ROUTE_Q = "_route"  # reserved question name for the routing choice


class Candidate(BaseModel):
    label: str
    description: str = ""
    examples: list[str] = []


class SignalIn(BaseModel):
    name: str
    type: Literal["choice", "score", "noul"]
    instructions: str
    criteria: dict[str, str] | list[str] | None = None


class ClassifyIn(BaseModel):
    prompt: str
    candidates: list[Candidate]
    signals: list[SignalIn] = []
    model: Literal["jev", "laya"] = "laya"


# ------------------------------------------------------------------ shared questions format
def build_questions(req: ClassifyIn) -> dict:
    criteria = {}
    for c in req.candidates:
        desc = c.description or c.label
        if c.examples:
            desc += " (for example: " + "; ".join(c.examples[:3]) + ")"
        criteria[c.label] = desc
    qs: dict[str, Any] = {ROUTE_Q: {"type": "choice", "criteria": criteria,
                                    "instructions": "Which route should handle this request?"}}
    for s in req.signals:
        q: dict[str, Any] = {"type": s.type, "instructions": s.instructions}
        if s.criteria:
            q["criteria"] = s.criteria
        qs[s.name] = q
    return qs


def first_number(d: dict, keys=("confidence", "probability", "prob", "score")):
    for k in keys:
        if isinstance(d.get(k), (int, float)):
            return float(d[k])
    return None


def extract(result: Any, req: ClassifyIn) -> dict:
    """Read a Laya/Jev questions response: {"answers": {name: {type: value}}, "routing": {...}}."""
    answers = result.get("answers") if isinstance(result, dict) else None
    if not isinstance(answers, dict) or ROUTE_Q not in answers:
        keys = list(result)[:6] if isinstance(result, dict) else type(result).__name__
        raise ValueError(f"unexpected response shape (top-level keys: {keys})")
    route = answers[ROUTE_Q]
    if isinstance(route, str):
        route = {"choice": route}
    label = route.get("choice")
    conf = first_number(route)
    probs = route.get("probabilities") or route.get("probs") or route.get("scores")
    if conf is None and isinstance(probs, dict) and label in probs:
        conf = float(probs[label])
    signals = {}
    for s in req.signals:
        a = answers.get(s.name)
        signals[s.name] = a.get(s.type) if isinstance(a, dict) else None
    routing = result.get("routing") if isinstance(result.get("routing"), dict) else {}
    return {"label": label, "confidence": conf, "signals": signals, "laya_model": routing.get("model")}


# ------------------------------------------------------------------ Laya (local package)
_laya = None


def get_laya():
    global _laya
    if _laya is None:
        from laya import Router  # imported lazily so Jev-only installs work without it
        _laya = Router(preload=os.getenv("LAYA_PRELOAD", "0") == "1")
    return _laya


async def classify_laya(req: ClassifyIn):
    result = await run_in_threadpool(get_laya().predict, req.prompt, build_questions(req))
    return extract(result, req)


# ------------------------------------------------------------------ Jev (hosted API)
def jev_cfg() -> dict:
    kind = os.getenv("JEV_KIND", "systemone")
    default_url = "https://api.typesafe.ai/v1/systemone" if kind == "systemone" else "http://host.docker.internal:11434"
    return {"kind": kind, "url": os.getenv("JEV_URL", default_url).rstrip("/"),
            "model": os.getenv("JEV_MODEL", "jev-latest" if kind == "systemone" else "jev"),
            "key": os.getenv("JEV_API_KEY", "")}


async def classify_jev(req: ClassifyIn):
    cfg = jev_cfg()
    if cfg["kind"] == "systemone":
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(cfg["url"], headers={"Authorization": f"Bearer {cfg['key']}"},
                             json={"state": req.prompt, "model": cfg["model"], "questions": build_questions(req)})
            r.raise_for_status()
        return extract(r.json(), req)
    label, conf = parse_label(await ask_jev_chat(build_instruction(req)), [c.label for c in req.candidates])
    return {"label": label, "confidence": conf, "signals": {}, "laya_model": None}


# Fallback kinds: Jev behind an Ollama or OpenAI-compatible chat server (lane choice only).
def build_instruction(req: ClassifyIn) -> str:
    lines = []
    for c in req.candidates:
        ex = f" Examples: {' | '.join(c.examples[:4])}" if c.examples else ""
        lines.append(f"- {c.label}: {c.description}{ex}")
    return ("You are a routing classifier. Pick exactly ONE label that best fits the user request.\n"
            "Labels:\n" + "\n".join(lines) + "\n\n"
            'Reply with JSON only: {"label": "<one label>", "confidence": <0..1>}\n\n'
            f'User request:\n"""\n{req.prompt[:4000]}\n"""')


async def ask_jev_chat(instruction: str) -> str:
    cfg = jev_cfg()
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if cfg["kind"] == "ollama":
            r = await c.post(f"{cfg['url']}/api/chat", json={
                "model": cfg["model"], "stream": False, "format": "json",
                "options": {"temperature": 0}, "messages": [{"role": "user", "content": instruction}]})
            r.raise_for_status()
            return r.json()["message"]["content"]
        r = await c.post(f"{cfg['url']}/chat/completions",
                         headers={"Authorization": f"Bearer {cfg['key'] or 'none'}"},
                         json={"model": cfg["model"], "temperature": 0,
                               "messages": [{"role": "user", "content": instruction}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def parse_label(text: str, labels: list[str]):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            hit = next((l for l in labels if l.lower() == str(d.get("label", "")).strip().lower()), None)
            if hit:
                return hit, float(d.get("confidence", 0.5))
        except (ValueError, TypeError):
            pass
    hits = [l for l in labels if l.lower() in text.lower()]
    return (hits[0], 0.4) if len(hits) == 1 else (None, 0.0)


# ------------------------------------------------------------------ fallback + endpoint
def tokens(s: str) -> set[str]:
    return set(re.findall(r"[\w']{3,}", s.lower()))


def heuristic(req: ClassifyIn):
    pt = tokens(req.prompt)
    scores = [len(pt & tokens(c.label + " " + c.description + " " + " ".join(c.examples))) for c in req.candidates]
    if max(scores, default=0) > 0:
        i = scores.index(max(scores))
        return req.candidates[i].label, min(0.3 + 0.1 * scores[i], 0.7)
    return req.candidates[min(len(req.candidates) - 1, len(req.prompt) // 400)].label, 0.2


@app.post("/classify")
async def classify(req: ClassifyIn):
    t0 = time.perf_counter()
    labels = [c.label for c in req.candidates]
    res: dict[str, Any] = {"label": None, "confidence": 0.0, "signals": {}, "laya_model": None}
    source = req.model
    # With signals, the router model still has questions to answer even with a single lane.
    if len(labels) == 1 and not req.signals:
        return {"label": labels[0], "confidence": 1.0, "source": "single lane", "signals": {},
                "laya_model": None, "latency_ms": 0}
    try:
        res = await (classify_laya(req) if req.model == "laya" else classify_jev(req))
    except ImportError:
        source = "heuristic (laya package not installed in the router image)"
    except Exception as e:  # noqa: BLE001 - any model failure falls back
        detail = (f"{e.response.status_code} {e.response.text[:150]}" if isinstance(e, httpx.HTTPStatusError)
                  else f"{type(e).__name__}: {str(e)[:120]}")
        source = f"heuristic ({req.model} failed: {detail})"
    if res["label"] not in labels:
        if source == req.model:
            source = f"heuristic ({req.model} returned an unknown label)"
        res["label"], res["confidence"] = heuristic(req)
    elif res["confidence"] is None:  # a choice came back without a probability
        res["confidence"], source = 1.0, f"{source} (no confidence reported)"
    return {**res, "source": source, "latency_ms": int((time.perf_counter() - t0) * 1000)}


@app.get("/healthz")
async def healthz():
    try:
        import laya  # noqa: F401
        laya_ok = True
    except ImportError:
        laya_ok = False
    cfg = jev_cfg()
    return {"ok": True, "laya_installed": laya_ok, "jev": f"{cfg['kind']}@{cfg['url']} model={cfg['model']}",
            "jev_key_set": bool(cfg["key"])}
