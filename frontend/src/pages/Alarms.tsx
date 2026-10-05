// pages/Alarms.tsx - Alarm Console (Requirements 3 and 5). Two views:
//   * Clusters (default): alarm-storm friendly - one row per incident with counts per device/type
//   * Raw list: every original alarm with filters; click an alarm to see the original vendor payload
// Duplicates are hidden from the incident view but always available here for audit.
import { useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { usePoll } from "../hooks";
import { Badge, Panel, PageHeader, Empty, fmtTime } from "../components/ui";

export default function Alarms() {
  const [view, setView] = useState<"clusters" | "raw">("clusters");
  const [f, setF] = useState({ status: "active", severity: "", device: "", role: "" });
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as any).toString();
  const { data: clusters } = usePoll<any[]>("/api/alarms/clusters", 4000);
  const { data: alarms } = usePoll<any[]>(`/api/alarms?${qs}&limit=400`, 4000);
  const [raw, setRaw] = useState<any>(null);

  return (
    <div>
      <PageHeader title="Alarm Console" sub="Incoming alarms after normalization. During an alarm storm, use the cluster view: hundreds of alarms collapse into a few incidents while every original stays available."
        right={<div className="flex gap-1">{(["clusters", "raw"] as const).map((v) => <button key={v} className={`btn ${view === v ? "btn-primary" : ""}`} onClick={() => setView(v)}>{v === "clusters" ? "Incident clusters" : "All alarms"}</button>)}</div>} />
      {view === "clusters" ? (
        <div className="grid md:grid-cols-2 gap-4">
          {!clusters?.length && <Empty>No active alarms.</Empty>}
          {clusters?.map((c) => (
            <Panel key={c.incident_id} title={c.incident_id === "uncorrelated" ? "Uncorrelated" : <Link to={`/incidents/${c.incident_id}`} className="text-sig id">{c.incident_id}</Link>}
              right={c.storm ? <Badge v="critical" /> : null}>
              <div className="text-sm mb-2">{c.storm && <span className="text-crit font-medium">Alarm storm: </span>}
                <span className="text-2xl font-semibold">{c.total}</span> alarms, {c.unique} unique, {c.duplicates} duplicates</div>
              <div className="text-sm mb-2"><span className="text-mute">Primary suspected: </span>{c.primary || "pending analysis"}</div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div><div className="text-mute mb-1">By device</div>{Object.entries(c.by_device).map(([k, v]: any) => <div key={k} className="flex justify-between"><span className="id">{k}</span><span>{v}</span></div>)}</div>
                <div><div className="text-mute mb-1">By type</div>{Object.entries(c.by_type).map(([k, v]: any) => <div key={k} className="flex justify-between"><span>{k}</span><span>{v}</span></div>)}</div>
              </div>
            </Panel>
          ))}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 mb-3">
            <select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">any status</option><option>active</option><option>cleared</option></select>
            <select className="input" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}><option value="">any severity</option>{["critical", "major", "minor", "warning"].map((s) => <option key={s}>{s}</option>)}</select>
            <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="">any role</option>{["primary", "consequential", "duplicate", "independent"].map((s) => <option key={s}>{s}</option>)}</select>
            <input className="input" placeholder="device e.g. AR-01" value={f.device} onChange={(e) => setF({ ...f, device: e.target.value })} />
            <span className="text-sm text-mute self-center">{alarms?.length ?? 0} alarms</span>
          </div>
          <div className="grid lg:grid-cols-[1fr_360px] gap-4">
            <div className="panel overflow-x-auto max-h-[70vh]">
              <table className="w-full min-w-[820px]"><thead className="sticky top-0 bg-panel"><tr>{["Time", "Event ID", "Device", "Alarm", "Severity", "Interface", "Source", "Role", "Incident", "Status"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>{alarms?.map((a) => (
                  <tr key={a.id} className={`cursor-pointer hover:bg-line/30 ${a.role === "duplicate" ? "opacity-60" : ""}`} onClick={async () => setRaw(await get(`/api/alarms/${a.id}/raw`))}>
                    <td className="td id">{fmtTime(a.timestamp)}</td><td className="td id text-mute">{a.id}</td><td className="td id">{a.device}</td><td className="td">{a.alarm_type}</td>
                    <td className="td"><Badge v={a.severity} /></td><td className="td id text-xs">{a.interface}</td><td className="td text-xs text-mute">{a.source_format}</td>
                    <td className="td text-xs">{a.role}</td><td className="td id text-xs">{a.incident_id}</td><td className="td"><Badge kind="status" v={a.status} /></td></tr>))}</tbody></table>
            </div>
            <Panel title="Original event (audit)">{raw ? <pre className="text-xs whitespace-pre-wrap break-all id">{JSON.stringify(raw, null, 2)}</pre> : <Empty>Click an alarm to see the raw vendor payload and its normalized form</Empty>}</Panel>
          </div>
        </>
      )}
    </div>
  );
}
