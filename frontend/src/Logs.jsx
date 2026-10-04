import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";

const when = (ts) => new Date(ts).toLocaleString();

function Detail({ ev }) {
  const msgs = ev.request?.messages;
  return (
    <div className="detail">
      <div>
        <h3>Request</h3>
        {Array.isArray(msgs)
          ? msgs.map((m, i) => <p key={i}><b>{m.role}</b> {m.content}</p>)
          : <p className="dim">Bodies are not logged (LOG_BODIES=false): {JSON.stringify(msgs)}</p>}
      </div>
      <div>
        <h3>{ev.status === "ok" ? "Response" : "Error"}</h3>
        {ev.status === "ok"
          ? <p>{ev.response?.text ?? <span className="dim">{ev.response ? `${ev.response.chars} characters (not logged)` : "No model call (route only)."}</span>}</p>
          : <p className="errtext">{ev.error}</p>}
        {ev.response?.usage && Object.keys(ev.response.usage).length > 0 && <p className="dim">Tokens: {JSON.stringify(ev.response.usage)}</p>}
      </div>
      <div>
        <h3>Decision</h3>
        <pre>{JSON.stringify({ decision: ev.decision, target_model: ev.target_model, params: ev.request?.params, client: ev.client }, null, 2)}</pre>
      </div>
    </div>
  );
}

export default function Logs() {
  const [events, setEvents] = useState([]);
  const [routers, setRouters] = useState([]);
  const [info, setInfo] = useState(null);
  const [f, setF] = useState({ router_id: "", source: "", q: "" });
  const [open, setOpen] = useState(null);
  const [live, setLive] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ limit: 100, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) });
      setEvents(await api.get("/logs?" + qs));
      setErr("");
    } catch (e) { setErr(e.message); }
  }, [f]);

  useEffect(() => { api.get("/routers").then(setRouters).catch(() => {}); api.get("/logs/info").then(setInfo).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!live) return; const t = setInterval(load, 5000); return () => clearInterval(t); }, [live, load]);

  return (
    <div className="page">
      <h1>Logs</h1>
      <p className="hint">
        Every request and response is written to a file, one JSON line each:{" "}
        <code>{info ? info.dir : "…"}/requests-YYYY-MM-DD.jsonl</code>
        {info && !info.bodies && " (prompt and response text are switched off)"}
      </p>
      <div className="filters">
        <select value={f.router_id} onChange={(e) => setF({ ...f, router_id: e.target.value })}>
          <option value="">All routers</option>{routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
          <option value="">All sources</option>
          {["gateway", "gateway-route", "studio", "test"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input placeholder="Search prompts and responses" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <label className="inline"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Refresh every 5 s</label>
        <button onClick={load}>Refresh</button>
      </div>
      {err && <div className="err">{err}</div>}
      {events.length === 0 && !err && <p className="empty">No requests logged yet. Send one from the Prompt studio or the gateway.</p>}
      <div className="logtable">
        {events.map((ev) => (
          <div key={ev.id} className={"logrow " + ev.status + (open === ev.id ? " open" : "")}>
            <button className="logline" onClick={() => setOpen(open === ev.id ? null : ev.id)} aria-expanded={open === ev.id}>
              <span className="dim">{when(ev.ts)}</span>
              <span>{ev.source}</span>
              <span>{ev.router_id || ev.requested_model}</span>
              <span>{ev.decision ? `${ev.decision.label} → ${ev.target_model || (ev.decision.action === "respond" ? "direct reply" : "no call")}` : ev.target_model || "—"}</span>
              <span className="dim">{ev.latency_ms} ms</span>
              <span className={"status " + ev.status}>{ev.status}</span>
            </button>
            {open === ev.id && <Detail ev={ev} />}
          </div>
        ))}
      </div>
    </div>
  );
}
