import { useEffect, useState } from "react";
import { api, slug } from "./api.js";

const blank = () => ({ id: "", name: "", instructions: "", model_id: "", tools: [], handoffs: [], input_blocked_terms: [], output_blocked_terms: [], max_turns: 10 });
const terms = (value) => value.split(",").map((item) => item.trim()).filter(Boolean);

export default function Agents() {
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  const [draft, setDraft] = useState(blank());
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const [agentList, modelList] = await Promise.all([api.get("/agents"), api.get("/models")]);
      setAgents(agentList); setModels(modelList);
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); }, []);
  const run = async (fn) => { setErr(""); try { await fn(); await load(); } catch (e) { setErr(e.message); } };
  const toggle = (key, value) => setDraft({ ...draft, [key]: draft[key].includes(value) ? draft[key].filter((item) => item !== value) : [...draft[key], value] });
  const save = (e) => {
    e.preventDefault();
    const id = draft.id || slug(draft.name);
    run(async () => { await api.put(`/agents/${id}`, { ...draft, id }); setDraft(blank()); });
  };

  return <div className="page">
    <h1>Agents</h1>
    {err && <div className="err">{err}</div>}
    <section>
      <h2>Configured agents</h2>
      <div className="list">
        {agents.length === 0 && <p className="empty">No agents yet. Define one with a Routapse model alias.</p>}
        {agents.map((agent) => <div className="row" key={agent.id}>
          <b>{agent.name}</b><span>{agent.id}</span><span className="dim">via {agent.model_id}</span>
          <span className="dim">{agent.tools.length} tools · {agent.handoffs.length} handoffs</span>
          <button className="ghost" onClick={() => run(() => api.del(`/agents/${agent.id}`))}>Remove</button>
        </div>)}
      </div>
    </section>
    <section>
      <h2>New agent</h2>
      <form className="form" onSubmit={save}>
        <label>Name
          <input required value={draft.name} placeholder="Support specialist" onChange={(e) => setDraft({ ...draft, name: e.target.value, id: draft.id || slug(e.target.value) })} />
        </label>
        <label>Identifier
          <input required value={draft.id} placeholder="support-specialist" onChange={(e) => setDraft({ ...draft, id: slug(e.target.value) })} />
        </label>
        <label>Model
          <select required value={draft.model_id} onChange={(e) => setDraft({ ...draft, model_id: e.target.value })}>
            <option value="" disabled>Choose…</option>
            {models.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
          </select>
        </label>
        <label>Maximum turns
          <input type="number" min="1" max="20" required value={draft.max_turns} onChange={(e) => setDraft({ ...draft, max_turns: Number(e.target.value) })} />
        </label>
        <label className="wide">Instructions
          <textarea value={draft.instructions} placeholder="How this agent should respond and when to hand off." onChange={(e) => setDraft({ ...draft, instructions: e.target.value })} />
        </label>
        <label>Input blocked terms
          <input placeholder="comma-separated" onChange={(e) => setDraft({ ...draft, input_blocked_terms: terms(e.target.value) })} />
        </label>
        <label>Output blocked terms
          <input placeholder="comma-separated" onChange={(e) => setDraft({ ...draft, output_blocked_terms: terms(e.target.value) })} />
        </label>
        <div className="wide">
          <span>Tools</span><div className="chips pick">
            {[["list_models", "List models"], ["route_prompt", "Route prompt"]].map(([id, label]) => <button key={id} type="button" className={"chip" + (draft.tools.includes(id) ? " on" : "")} onClick={() => toggle("tools", id)}>{label}</button>)}
          </div>
        </div>
        <div className="wide">
          <span>Handoffs</span><div className="chips pick">
            {agents.map((agent) => <button key={agent.id} type="button" className={"chip" + (draft.handoffs.includes(agent.id) ? " on" : "")} onClick={() => toggle("handoffs", agent.id)}>{agent.name}</button>)}
          </div>
        </div>
        <button className="primary" disabled={!models.length}>Save agent</button>
      </form>
    </section>
  </div>;
}
