// components/ui.tsx - reusable UI pieces: severity/status badges, panels, page header,
// incident picker, empty states and a key-value list. Used by every page.
import { Fragment, ReactNode } from "react";

const SEV: Record<string, string> = {
  critical: "bg-crit/15 text-crit border-crit/40", major: "bg-major/15 text-major border-major/40",
  minor: "bg-yellow-400/10 text-yellow-300 border-yellow-400/30", warning: "bg-yellow-400/10 text-yellow-300 border-yellow-400/30",
  high: "bg-ok/15 text-ok border-ok/40", medium: "bg-major/15 text-major border-major/40", low: "bg-mute/15 text-mute border-mute/40",
};
const STATUS: Record<string, string> = {
  up: "text-ok", available: "text-ok", resolved: "text-ok", closed: "text-ok", verified: "text-ok", completed: "text-ok", approved: "text-sig",
  down: "text-crit", unavailable: "text-crit", escalated: "text-crit", rejected: "text-crit", active: "text-crit",
  degraded: "text-major", awaiting_approval: "text-major", analyzing: "text-sig", restoring: "text-sig", in_progress: "text-sig",
  proposed: "text-mute", open: "text-major", cleared: "text-mute",
};

export function Badge({ v, kind = "sev" }: { v?: string | null; kind?: "sev" | "status" | "plain" }) {
  if (!v) return null;
  if (kind === "status") return <span className={`text-xs font-medium ${STATUS[v] || "text-mute"}`}>{v.replace(/_/g, " ")}</span>;
  const cls = kind === "sev" ? SEV[v] || "bg-line/40 text-mute border-line" : "bg-line/40 text-txt border-line";
  return <span className={`inline-block px-1.5 py-0.5 text-xs rounded border ${cls}`}>{v.replace(/_/g, " ")}</span>;
}

export function Category({ v }: { v: string }) {
  const map: Record<string, string> = {
    diagnostic: "border-sig/40 text-sig", non_disruptive: "border-ok/40 text-ok",
    potentially_disruptive: "border-crit/50 text-crit", escalation: "border-major/50 text-major",
  };
  return <span className={`inline-block px-1.5 py-0.5 text-xs rounded border ${map[v] || "border-line"}`}>{v.replace(/_/g, " ")}</span>;
}

export function Panel({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {title && <header className="flex items-center justify-between px-4 py-2.5 border-b border-line"><h2>{title}</h2>{right}</header>}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div><h1>{title}</h1>{sub && <p className="text-sm text-mute mt-1 max-w-3xl">{sub}</p>}</div>
      {right}
    </div>
  );
}

export function IncidentPicker({ id, setId, list }: { id: string | null; setId: (v: string) => void; list: any[] }) {
  return (
    <select className="input min-w-[18rem]" value={id || ""} onChange={(e) => setId(e.target.value)} aria-label="Select incident">
      {list.length === 0 && <option value="">No incidents yet</option>}
      {list.map((i) => <option key={i.id} value={i.id}>{i.id} - {i.title?.slice(0, 60)}</option>)}
    </select>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-mute py-8 text-center">{children}</div>;
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => <Fragment key={k}><dt className="text-mute">{k}</dt><dd>{v ?? "-"}</dd></Fragment>)}
    </dl>
  );
}

export function Evidence({ items, tone = "ok" }: { items?: string[]; tone?: "ok" | "crit" | "sig" }) {
  if (!items || !items.length) return <p className="text-xs text-mute">None</p>;
  const c = tone === "ok" ? "border-ok/60" : tone === "crit" ? "border-crit/60" : "border-sig/60";
  return <ul className="space-y-1">{items.map((e, i) => <li key={i} className={`text-sm pl-2 border-l-2 ${c}`}>{e}</li>)}</ul>;
}

export const fmtTime = (t?: string) => (t ? new Date(t + (t.endsWith("Z") || t.includes("+") ? "" : "Z")).toLocaleTimeString() : "-");
export const fmtDate = (t?: string) => (t ? new Date(t + (t.endsWith("Z") || t.includes("+") ? "" : "Z")).toLocaleString() : "-");
