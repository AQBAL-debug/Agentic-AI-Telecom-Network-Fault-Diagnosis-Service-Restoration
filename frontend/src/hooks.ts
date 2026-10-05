// hooks.ts - small React hooks:
//   usePoll(path, ms)  -> fetches data and re-fetches every `ms` (live NOC screens)
//   useIncidentId()    -> incident chosen via ?id= in the URL, or the newest incident
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get } from "./api";

export function usePoll<T = any>(path: string | null, ms = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!path) return;
    try { setData(await get<T>(path)); setError(null); } catch (e: any) { setError(e.message); }
  }, [path]);
  useEffect(() => {
    load();
    if (!ms) return;
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  }, [load, ms]);
  return { data, error, reload: load };
}

export function useIncidentId(): [string | null, (id: string) => void, any[]] {
  const [params, setParams] = useSearchParams();
  const { data } = usePoll<any[]>("/api/incidents", 8000);
  const id = params.get("id") || (data && data[0]?.id) || null;
  return [id, (v: string) => setParams({ id: v }), data || []];
}
