import { useEffect, useState } from "react";
import { getToken, setToken } from "./api.js";
import Routers from "./Routers.jsx";
import Studio from "./Studio.jsx";
import Logs from "./Logs.jsx";
import Connections from "./Connections.jsx";

const PAGES = [
  ["routers", "Routers"],
  ["studio", "Prompt studio"],
  ["logs", "Logs"],
  ["connections", "Connections"],
];

export default function App() {
  const [page, setPage] = useState("routers");
  const [epoch, setEpoch] = useState(0);
  const [locked, setLocked] = useState(false);
  const [draft, setDraft] = useState(getToken());

  useEffect(() => {
    window.onUnauthorized = () => setLocked(true);
  }, []);

  const unlock = (e) => {
    e.preventDefault();
    setToken(draft);
    setLocked(false);
    setEpoch((n) => n + 1); // remount the page so it refetches with the new token
  };

  return (
    <div className="shell">
      <nav className="side">
        <div className="brand"><img src="/logo-mark.svg" alt="" width="34" height="34" />Routapse</div>
        {PAGES.map(([id, label]) => (
          <button key={id} className={page === id ? "on" : ""} onClick={() => setPage(id)}>{label}</button>
        ))}
        <p className="side-note">Routers decide. The studio sends prompts through them. Logs keep every request.</p>
      </nav>
      <main key={page + epoch}>
        {page === "routers" && <Routers goConnections={() => setPage("connections")} />}
        {page === "studio" && <Studio goRouters={() => setPage("routers")} />}
        {page === "logs" && <Logs />}
        {page === "connections" && <Connections />}
      </main>
      {locked && (
        <div className="veil">
          <form className="card gate" onSubmit={unlock}>
            <h2>Enter admin token</h2>
            <p>This is the ADMIN_TOKEN set on the admin service.</p>
            <input type="password" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} />
            <button className="primary">Unlock</button>
          </form>
        </div>
      )}
    </div>
  );
}
