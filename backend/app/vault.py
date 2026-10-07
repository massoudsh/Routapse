"""Opt-in exporter that turns request-log records into an Obsidian vault.

Set VAULT_DIR to enable it (disabled when empty, which is the default). The exporter is
on-demand: call `export()` (or `POST /admin/vault/export`) to write the notes. Each request
log entry becomes one markdown note with YAML frontmatter, a fenced body, and wikilinks;
index notes are generated per router, lane, model and source. The request log stays the
source of truth, so the vault can be rebuilt from it at any time.
"""
import glob, json, os, re
from datetime import datetime, timezone

from .config import settings

MAX_NAME = 60
_UNSAFE = re.compile(r"[\\/:*?\"<>|#^\[\]]")
_WS = re.compile(r"\s+")


def _safe(name: str, fallback: str = "note") -> str:
    """Filesystem- and Obsidian-safe name: no path separators or wiki-reserved characters."""
    cleaned = _WS.sub(" ", _UNSAFE.sub("", (name or "").strip())).strip(" .")
    cleaned = cleaned[:MAX_NAME].strip()
    return cleaned or fallback


def _quote(value) -> str:
    """A YAML scalar that is always safe to emit (plain, quoted and multiline forms)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if "\n" in text:
        return json.dumps(text)  # JSON string escapes are valid YAML double-quoted scalars
    return f'"{text.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'


def frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(_quote(v) for v in value)}]")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {_quote(k)}: {_quote(v)}" for k, v in sorted(value.items())]
        else:
            lines.append(f"{key}: {_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def _stamp(ts: str) -> str:
    """A compact, sortable UTC timestamp for ids and index sections."""
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    except (TypeError, ValueError):
        return _safe(str(ts), "unknown")


def note_name(ev: dict) -> str:
    return f"{_stamp(ev.get('ts', ''))}-{_safe(ev.get('source', ''), 'request')}"


def title(ev: dict) -> str:
    """First user message, trimmed to one line, for a readable note title."""
    messages = (ev.get("request") or {}).get("messages")
    for m in messages if isinstance(messages, list) else []:
        if m.get("role") == "user" and m.get("content"):
            text = " ".join(str(m["content"]).split())
            return text[:80] + ("…" if len(text) > 80 else "")
    return f"{ev.get('source', 'request')} request"


def _body(ev: dict) -> str:
    req = ev.get("request") or {}
    resp = ev.get("response") or {}
    messages = req.get("messages")
    usage = (resp.get("usage") or {})
    parts = [
        f"# {title(ev)}",
        "",
        f"[[{ev.get('router_id') or 'no-router'}]] · "
        f"[[{(ev.get('decision') or {}).get('label') or 'none'}]] · "
        f"[[{ev.get('target_model') or 'none'}]]",
        "",
    ]
    if isinstance(messages, list) and messages:
        parts += ["## Request", ""]
        for m in messages:
            parts += [f"**{m.get('role', '')}**", "", str(m.get("content", "")), ""]
    elif "messages" in req:
        detail = f"{req['messages']} messages × {req.get('chars', 0)} chars" if isinstance(req["messages"], int) else ""
        parts += ["## Request", "", f"_Bodies are not logged (LOG_BODIES=false).{f' {detail}.' if detail else ''}_", ""]
    if resp.get("text"):
        parts += ["## Response", "", str(resp["text"]), ""]
    if usage:
        parts += ["## Usage", ""] + [f"- {k}: {v}" for k, v in sorted(usage.items())] + [""]
    parts.append(f"`{ev.get('id', '')}`")
    return "\n".join(parts)


def note(ev: dict) -> tuple[str, str]:
    """Return (filename, markdown) for one request-log record."""
    decision = ev.get("decision") or {}
    fields = {
        "id": ev.get("id"),
        "ts": ev.get("ts"),
        "source": ev.get("source"),
        "status": ev.get("status"),
        "router": ev.get("router_id"),
        "lane": decision.get("label"),
        "action": decision.get("action"),
        "confidence": decision.get("confidence"),
        "reason": decision.get("reason"),
        "target_model": ev.get("target_model"),
        "latency_ms": ev.get("latency_ms"),
        "fallback_from": ev.get("fallback_from") or decision.get("fallback_from"),
        "fallback_reason": ev.get("fallback_reason") or decision.get("fallback_reason"),
        "usage": (ev.get("response") or {}).get("usage") or None,
        "tags": ["routapse", _safe(ev.get("source"), "") or None,
                 (_safe(ev.get("router_id"), "router") and "router/" + _safe(ev.get("router_id"), "router"))
                 if ev.get("router_id") else None,
                 "lane/" + _safe(decision.get("label"), "none") if decision.get("label") else None,
                 "status/" + _safe(ev.get("status"), "unknown")],
        "aliases": [title(ev)],
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    fields["tags"] = [t for t in fields["tags"] if t]
    return note_name(ev) + ".md", frontmatter(fields) + "\n\n" + _body(ev) + "\n"


def _index(folder: str, rows: list[tuple[str, dict]]) -> tuple[str, str]:
    lines = [f"# {folder}", "", f"_{len(rows)} records_", ""]
    for name, ev in rows:
        decision = ev.get("decision") or {}
        head = f"- [[{name[:-3]}]] · {ev.get('ts', '')} · `{ev.get('status', '')}`"
        if decision.get("label"):
            head += f" · lane `{decision['label']}`"
        if ev.get("target_model"):
            head += f" · `{ev['target_model']}`"
        lines.append(head)
    return f"{folder}.md", "\n".join(lines) + "\n"


def _write(vault: str, rel: str, text: str) -> None:
    path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def export(records: list[dict] | None = None, vault: str | None = None) -> dict:
    """Write the vault. Uses `records` when given, otherwise reads the request log."""
    vault = vault or settings.vault_dir
    if not vault:
        raise RuntimeError("VAULT_DIR is not set; the vault exporter is disabled")
    from . import reqlog
    records = reqlog.read_logs(limit=10_000_000) if records is None else records

    by_group: dict[str, dict[str, list]] = {"by-router": {}, "by-lane": {}, "by-model": {}, "by-source": {}}
    counts = {"requests": 0, "notes": 0, "errors": 0}
    for ev in records:
        if not ev.get("id"):
            continue
        name, text = note(ev)
        _write(vault, os.path.join("requests", name), text)
        counts["requests"] += 1
        counts["notes"] += 1
        if ev.get("status") != "ok":
            counts["errors"] += 1
        decision = ev.get("decision") or {}
        groups = {
            "by-router": ev.get("router_id"),
            "by-lane": decision.get("label"),
            "by-model": ev.get("target_model"),
            "by-source": ev.get("source"),
        }
        for folder, key in groups.items():
            if key:
                by_group[folder].setdefault(_safe(key, "none"), []).append((name, ev))
    for folder, groups in by_group.items():
        for key, rows in sorted(groups.items()):
            rows.sort(key=lambda r: r[1].get("ts", ""), reverse=True)
            name, text = _index(key, rows)
            _write(vault, os.path.join(folder, name), text)
            counts["notes"] += 1
    return {"dir": os.path.abspath(vault), **counts}
