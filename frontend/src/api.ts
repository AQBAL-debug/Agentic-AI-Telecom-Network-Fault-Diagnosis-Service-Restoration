// api.ts - every call from the UI to the FastAPI backend goes through these helpers.
// The backend URL comes from VITE_API_URL (set in .env.local or in Vercel settings).
export const API = (import.meta.env.VITE_API_URL as string) || "http://localhost:8000";

export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail ?? msg; } catch { /* plain text */ }
    throw new Error(String(msg));
  }
  return r.json();
}

export async function del(path: string) {
  const r = await fetch(`${API}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
