import { useEffect, useRef, useState } from "react";
import { api, slug } from "./api.js";

const snippet = (target) => `from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="YOUR_GATEWAY_API_KEY")
reply = client.chat.completions.create(
    model="${target || "router:<id>"}",
    messages=[{"role": "user", "content": "..."}],
)
print(reply.choices[0].message.content)
print(reply.routapse)  # which lane and model were used`;

export default function Studio({ goRouters }) {
  const [routers, setRouters] = useState([]);
  const [models, setModels] = useState([]);
  const [saved, setSaved] = useState([]);
  const [target, setTarget] = useState("");          // "router:<id>" or "model:<id>"
  const [lane, setLane] = useState("");              // "" = let the router decide
  const [system, setSystem] = useState("");
  const [thread, setThread] = useState([]);          // {role, content, meta?}
  const [text, setText] = useState("");
  const [temp, setTemp] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null);
  const [saveName, setSaveName] = useState("");
  const [showCode, setShowCode] = useState(false);
  const end = useRef(null);

  const load = async () => {
    try {
      const [r, m, p] = await Promise.all([api.get("/routers"), api.get("/models"), api.get("/prompts")]);
      setRouters(r); setModels(m); setSaved(p);
      setTarget((t) => t || (r[0] ? `router:${r[0].id}` : m[0] ? `model:${m[0].id}` : ""));
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [thread, busy]);

  const [kind, id] = target.split(/:(.*)/s);
  const router = kind === "router" ? routers.find((r) => r.id === id) : null;

  const body = (messages, routeOnly = false) => ({
    router_id: kind === "router" ? id : null,
    model_id: kind === "model" ? id : null,
    system, messages: messages.map(({ role, content }) => ({ role, content })),
    temperature: temp, max_tokens: Number(maxTokens) || null,
    force_label: router && lane ? lane : null, route_only: routeOnly,
  });

  const send = async () => {
    if (!text.trim() || !target || busy) return;
    const next = [...thread, { role: "user", content: text }];
    setThread(next); setText(""); setBusy(true); setErr(""); setPreview(null);
    try {
      const r = await api.post("/chat", body(next));
      setThread([...next, { role: "assistant", content: r.response.text, meta: { decision: r.decision, model: r.response.model } }]);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  const routeOnly = async () => {
    if (!text.trim() || !router) return;
    setBusy(true); setErr("");
    try { setPreview((await api.post("/chat", body([...thread, { role: "user", content: text }], true))).decision); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  };

  const savePrompt = async () => {
    const name = saveName.trim();
    if (!name) return;
    const sp = { id: slug(name), name, router_id: kind === "router" ? id : null, model_id: kind === "model" ? id : null, system, user: text };
    try { await api.put(`/prompts/${sp.id}`, sp); setSaveName(""); load(); } catch (e) { setErr(e.message); }
  };
  const loadPrompt = (p) => {
    setTarget(p.router_id ? `router:${p.router_id}` : p.model_id ? `model:${p.model_id}` : target);
    setSystem(p.system); setText(p.user); setLane(""); setThread([]);
  };

  if (!routers.length && !models.length && !err)
    return <div className="blank"><h1>Nothing to call yet.</h1><p>Create a router first, then come back to write prompts through it.</p><button className="primary" onClick={goRouters}>Create a router</button></div>;

  return (
    <div className="studio">
      <aside className="st-side">
        <label>Send through
          <select value={target} onChange={(e) => { setTarget(e.target.value); setLane(""); setPreview(null); }}>
            {routers.length > 0 && <optgroup label="Routers">{routers.map((r) => <option key={r.id} value={`router:${r.id}`}>{r.name}</option>)}</optgroup>}
            {models.length > 0 && <optgroup label="One model, no routing">{models.map((m) => <option key={m.id} value={`model:${m.id}`}>{m.id}</option>)}</optgroup>}
          </select>
        </label>
        {router && (
          <label>Lane
            <select value={lane} onChange={(e) => setLane(e.target.value)}>
              <option value="">Let the router decide</option>
              {router.routes.map((r) => <option key={r.label}>{r.label}</option>)}
            </select>
          </label>
        )}
        <label>Temperature {temp.toFixed(1)}
          <input type="range" min="0" max="2" step="0.1" value={temp} onChange={(e) => setTemp(Number(e.target.value))} />
        </label>
        <label>Max tokens
          <input type="number" min="1" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
        </label>

        <h3>Saved prompts</h3>
        {saved.length === 0 && <p className="empty">Write a prompt, name it, and it shows up here.</p>}
        {saved.map((p) => (
          <div className="saved" key={p.id}>
            <button className="link" onClick={() => loadPrompt(p)}>{p.name}</button>
            <button className="ghost" aria-label={"Delete " + p.name} onClick={async () => { await api.del(`/prompts/${p.id}`); load(); }}>Delete</button>
          </div>
        ))}
        <div className="saveform">
          <input placeholder="Name this prompt" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
          <button disabled={!saveName.trim()} onClick={savePrompt}>Save</button>
        </div>
        <button className="link" onClick={() => setShowCode(!showCode)}>{showCode ? "Hide" : "Show"} code for this target</button>
        {showCode && <pre className="code">{snippet(target ? (kind === "router" ? `router:${id}` : id) : "")}</pre>}
      </aside>

      <section className="st-main">
        <details className="sys" open={!!system}>
          <summary>Instructions for every message</summary>
          <textarea rows={3} placeholder="You are a concise assistant for our support team…" value={system} onChange={(e) => setSystem(e.target.value)} />
        </details>

        <div className="thread">
          {thread.length === 0 && <p className="empty">Write a prompt below. With a router selected, the answer shows which lane and model handled it.</p>}
          {thread.map((m, i) => (
            <div key={i} className={"msg " + m.role}>
              <div className="bubble">{m.content}</div>
              {m.meta?.decision && (
                <div className="meta">
                  <i style={{ background: router?.routes.find((r) => r.label === m.meta.decision.label)?.color || "var(--ink)" }} />
                  {m.meta.decision.label} · {m.meta.model || "direct reply"} · routed in {m.meta.decision.latency_ms} ms
                  {m.meta.decision.reason ? ` · ${m.meta.decision.reason}` : ""}
                </div>
              )}
              {m.role === "assistant" && !m.meta?.decision && m.meta?.model && <div className="meta">{m.meta.model}</div>}
            </div>
          ))}
          {busy && <p className="empty">Working…</p>}
          <div ref={end} />
        </div>

        {err && <div className="err">{err}</div>}
        {preview && <div className="ok">Would go to <b>{preview.label}</b>{preview.model_id ? ` (${preview.model_id})` : " (direct reply)"}, confidence {preview.confidence.toFixed(2)}. {preview.reason}</div>}

        <div className="composer">
          <textarea rows={3} placeholder="Write your prompt. Ctrl+Enter sends." value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === "Enter" && send()} />
          <div className="actions">
            <button className="primary" disabled={!text.trim() || busy || !target} onClick={send}>Send</button>
            {router && !lane && <button disabled={!text.trim() || busy} onClick={routeOnly}>Preview the lane</button>}
            <button className="ghost" onClick={() => { setThread([]); setPreview(null); }}>New chat</button>
          </div>
        </div>
      </section>
    </div>
  );
}
