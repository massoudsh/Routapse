const BASE = "/api/admin";
export const getToken = () => localStorage.getItem("routapse_token") || "";
export const setToken = (t) => localStorage.setItem("routapse_token", t);

async function req(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + getToken() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) {
    window.onUnauthorized?.();
    throw new Error("Wrong or missing admin token");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : r.statusText);
  }
  return data;
}

export const api = {
  get: (p) => req("GET", p),
  put: (p, b) => req("PUT", p, b),
  post: (p, b) => req("POST", p, b),
  del: (p) => req("DELETE", p),
};

export const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
