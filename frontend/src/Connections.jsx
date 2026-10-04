import { useEffect, useState } from "react";
import { api, slug } from "./api.js";

const KINDS = {
  ollama: { label: "Ollama (local)", url: "http://host.docker.internal:11434", key: false },
  openai: { label: "OpenAI", url: "https://api.openai.com/v1", key: true },
  anthropic: { label: "Claude (Anthropic)", url: "https://api.anthropic.com", key: true },
  gemini: { label: "Gemini (Google)", url: "https://generativelanguage.googleapis.com", key: true },
  openai_compat: { label: "Other OpenAI-compatible", url: "https://your-host/v1", key: true },
};
const gb = (b) => (b ? `${(b / 1e9).toFixed(1)} GB` : "");

export default function Connections() {
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [err, setErr] = useState("");
  const [p, setP] = useState({ id: "", kind: "ollama", base_url: "", api_key: "" });
  const [m, setM] = useState({ id: "", provider_id: "", model_name: "", description: "" });
  const [found, setFound] = useState(null);       // Ollama discovery result for the default URL
  const [forProvider, setForProvider] = useState(null); // discovery for the provider chosen in the model form

  const load = async () => {
    try {
      const [a, b] = await Promise.all([api.get("/providers"), api.get("/models")]);
      setProviders(a); setModels(b);
    } catch (e) { setErr(e.message); }
  };
  const detect = () => api.get("/ollama/models").then(setFound).catch(() => {});
  useEffect(() => { load(); detect(); }, []);

  // when the model form points at an Ollama provider, list what it has installed
  useEffect(() => {
    const prov = providers.find((x) => x.id === m.provider_id);
    if (prov?.kind !== "ollama") { setForProvider(null); return; }
    api.get("/ollama/models" + (prov.base_url ? `?base_url=${encodeURIComponent(prov.base_url)}` : "")).then(setForProvider).catch(() => setForProvider(null));
  }, [m.provider_id, providers]);

  const run = async (fn) => {
    setErr("");
    try { await fn(); await load(); } catch (e) { setErr(e.message); }
  };

  const connectOllama = (list) => run(async () => {
    const pid = providers.find((x) => x.kind === "ollama" && (x.base_url || found.base_url) === found.base_url)?.id || "ollama";
    if (!providers.some((x) => x.id === pid))
      await api.put(`/providers/${pid}`, { id: pid, kind: "ollama", base_url: found.base_url, api_key: "" });
    for (const name of list) {
      const id = slug(name);
      if (!models.some((x) => x.id === id))
        await api.put(`/models/${id}`, { id, provider_id: pid, model_name: name, description: "local" });
    }
  });

  const addProvider = (e) => {
    e.preventDefault();
    const id = p.id || slug(p.kind + "-" + (p.base_url || "default"));
    run(async () => { await api.put(`/providers/${id}`, { ...p, id }); setP({ id: "", kind: p.kind, base_url: "", api_key: "" }); });
  };
  const addModel = (e) => {
    e.preventDefault();
    const id = m.id || slug(m.model_name);
    run(async () => { await api.put(`/models/${id}`, { ...m, id }); setM({ id: "", provider_id: m.provider_id, model_name: "", description: "" }); });
  };

  const installed = new Set(models.map((x) => x.model_name));
  const missing = found?.models.filter((x) => !installed.has(x.name)) || [];

  return (
    <div className="page">
      <h1>Connections</h1>
      {err && <div className="err">{err}</div>}

      {found?.reachable && missing.length > 0 && (
        <div className="found">
          <div>
            <b>Ollama is running with {found.models.length} model{found.models.length === 1 ? "" : "s"}.</b>
            <span className="dim"> {missing.map((x) => x.name).join(", ")}</span>
          </div>
          <button className="primary" onClick={() => connectOllama(missing.map((x) => x.name))}>Connect {missing.length === 1 ? "it" : `all ${missing.length}`}</button>
        </div>
      )}
      {found && !found.reachable && (
        <p className="hint">Ollama was not found at <code>{found.base_url}</code>. Start it with <code>OLLAMA_HOST=0.0.0.0 ollama serve</code>, or set OLLAMA_URL, then <button className="link" onClick={detect}>check again</button>.</p>
      )}

      <section>
        <h2>Providers</h2>
        <div className="list">
          {providers.length === 0 && <p className="empty">No providers yet. Add Ollama, OpenAI, Claude or Gemini below.</p>}
          {providers.map((x) => (
            <div className="row" key={x.id}>
              <b>{x.id}</b><span>{KINDS[x.kind]?.label}</span>
              <span className="dim">{x.base_url || "default URL"}</span>
              <span className="dim">{x.api_key ? "key saved" : "no key"}</span>
              <button className="ghost" onClick={() => run(() => api.del(`/providers/${x.id}`))}>Remove</button>
            </div>
          ))}
        </div>
        <form className="form" onSubmit={addProvider}>
          <label>Type
            <select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })}>
              {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          <label>Name (optional)
            <input value={p.id} placeholder={p.kind} onChange={(e) => setP({ ...p, id: slug(e.target.value) })} />
          </label>
          <label>Base URL (optional)
            <input value={p.base_url} placeholder={KINDS[p.kind].url} onChange={(e) => setP({ ...p, base_url: e.target.value })} />
          </label>
          {KINDS[p.kind].key && (
            <label>API key
              <input type="password" value={p.api_key} onChange={(e) => setP({ ...p, api_key: e.target.value })} />
            </label>
          )}
          <button className="primary">Add provider</button>
        </form>
      </section>

      <section>
        <h2>Models</h2>
        <div className="list">
          {models.length === 0 && <p className="empty">Models are what routes point at. Add one per size or role you plan to use.</p>}
          {models.map((x) => (
            <div className="row" key={x.id}>
              <b>{x.id}</b><span>{x.model_name}</span>
              <span className="dim">via {x.provider_id}</span><span className="dim">{x.description}</span>
              <button className="ghost" onClick={() => run(() => api.del(`/models/${x.id}`))}>Remove</button>
            </div>
          ))}
        </div>
        <form className="form" onSubmit={addModel}>
          <label>Provider
            <select required value={m.provider_id} onChange={(e) => setM({ ...m, provider_id: e.target.value })}>
              <option value="" disabled>Choose…</option>
              {providers.map((x) => <option key={x.id} value={x.id}>{x.id}</option>)}
            </select>
          </label>
          <label>Model name at the provider
            <input required value={m.model_name} placeholder="llama3.2:3b, gpt-4o, gemini-2.0-flash…" onChange={(e) => setM({ ...m, model_name: e.target.value })} />
          </label>
          <label>Alias used in routers (optional)
            <input value={m.id} placeholder={slug(m.model_name) || "fast-local"} onChange={(e) => setM({ ...m, id: slug(e.target.value) })} />
          </label>
          <label>Note
            <input value={m.description} placeholder="cheap and quick" onChange={(e) => setM({ ...m, description: e.target.value })} />
          </label>
          <button className="primary" disabled={!providers.length}>Add model</button>
        </form>
        {forProvider?.reachable && (
          <div className="chips pick">
            <span className="dim">Installed on this Ollama:</span>
            {forProvider.models.map((x) => (
              <button type="button" key={x.name} className={"chip" + (m.model_name === x.name ? " on" : "")}
                onClick={() => setM({ ...m, model_name: x.name, description: m.description || [x.params, gb(x.bytes)].filter(Boolean).join(", ") })}>
                {x.name}{x.params ? ` · ${x.params}` : ""}
              </button>
            ))}
          </div>
        )}
        {forProvider && !forProvider.reachable && <p className="hint">Could not reach Ollama at <code>{forProvider.base_url}</code> to list its models.</p>}
      </section>
    </div>
  );
}
