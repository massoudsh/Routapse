"""Request/response log: one JSON object per line, one file per UTC day.

  <LOG_DIR>/requests-YYYY-MM-DD.jsonl

Gateway and admin containers share the directory through a volume. Appends use O_APPEND
so several replicas can write safely; daily files avoid in-process rotation races.
Set LOG_BODIES=false to log only metadata (sizes, routing, latency) and no prompt/response text.
"""
import glob, json, logging, os, uuid
from datetime import datetime, timezone

from .config import settings

console = logging.getLogger("routapse")


def _file(day: str) -> str:
    return os.path.join(settings.log_dir, f"requests-{day}.jsonl")


def log_event(ev: dict) -> None:
    now = datetime.now(timezone.utc)
    ev = {"id": uuid.uuid4().hex[:12], "ts": now.isoformat(timespec="milliseconds"), **ev}
    if not settings.log_bodies:
        req = ev.pop("request", None) or {}
        resp = ev.pop("response", None) or {}
        ev["request"] = {"messages": len(req.get("messages", [])),
                         "chars": sum(len(m.get("content", "")) for m in req.get("messages", []))}
        if resp:
            ev["response"] = {"chars": len(resp.get("text", "")), "usage": resp.get("usage")}
    d = ev.get("decision") or {}
    console.info("%s %s router=%s lane=%s model=%s %sms", ev.get("source"), ev.get("status"),
                 ev.get("router_id"), d.get("label"), ev.get("target_model"), ev.get("latency_ms"))
    try:
        os.makedirs(settings.log_dir, exist_ok=True)
        fd = os.open(_file(now.strftime("%Y-%m-%d")), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, (json.dumps(ev, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)
    except OSError as e:  # logging must never break serving
        console.warning("could not write request log: %s", e)


def _tail_lines(path: str, max_bytes: int = 8_000_000) -> list[str]:
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - max_bytes))
        data = f.read().decode("utf-8", "replace").splitlines()
    return data[1:] if size > max_bytes else data


def read_logs(limit=100, offset=0, router_id=None, source=None, q=None) -> list[dict]:
    out, skipped = [], 0
    for path in sorted(glob.glob(os.path.join(settings.log_dir, "requests-*.jsonl")), reverse=True):
        for line in reversed(_tail_lines(path)):
            if q and q.lower() not in line.lower():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if (router_id and ev.get("router_id") != router_id) or (source and ev.get("source") != source):
                continue
            if skipped < offset:
                skipped += 1
                continue
            out.append(ev)
            if len(out) >= limit:
                return out
    return out


def info() -> dict:
    files = sorted(glob.glob(os.path.join(settings.log_dir, "requests-*.jsonl")), reverse=True)
    return {"dir": os.path.abspath(settings.log_dir), "bodies": settings.log_bodies,
            "files": [{"name": os.path.basename(f), "bytes": os.path.getsize(f)} for f in files[:14]]}
