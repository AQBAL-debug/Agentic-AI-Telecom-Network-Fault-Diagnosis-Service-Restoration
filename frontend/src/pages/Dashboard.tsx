// pages/Dashboard.tsx - NOC Dashboard (Requirement 18): network health, active/critical alarms,
// correlated incidents, affected elements, anomalies, restoration actions, escalations,
// recently resolved incidents + the SCENARIO SIMULATOR used in the demo.
import { useState } from "react";
import { Link } from "react-router-dom";
import { Play, RotateCcw } from "lucide-react";
import { post } from "../api";
import { usePoll } from "../hooks";
import { Badge, Panel, PageHeader, Empty } from "../components/ui";

export default function Dashboard() {
  const { data: d, reload } = usePoll<any>("/api/dashboard", 4000);
  const { data: scenarios } = usePoll<any[]>("/api/simulate/scenarios", 0);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string>("");

  async function run(id: string) {
    setBusy(id); setMsg("");
    try {
      const r = await post(`/api/simulate/${id}`);
      setMsg(`${r.events_sent} events + ${r.telemetry_points} telemetry points sent. ` +
        (r.incidents_created.length ? `New incident(s): ${r.incidents_created.join(", ")}. ` : "") +
        (r.incidents_reassessed.length ? `Reassessing: ${r.incidents_reassessed.join(", ")}. ` : "") + "Agents are analyzing...");
      reload();
    } catch (e: any) { setMsg(e.message); } finally { setBusy(null); }
  }
  async function reset() {
    if (!confirm("Reset all demo data?")) return;
    setBusy("reset"); await post("/api/reset"); setBusy(null); setMsg("Demo data reset."); reload();
  }

  const stat = (label: string, value: any, tone = "text-txt") => (
    <div className="panel px-4 py-3"><div className={`text-2xl font-semibold ${tone}`}>{value ?? "-"}</div><div className="text-xs text-mute mt-0.5">{label}</div></div>
  );

  return (
    <div>
      <PageHeader title="NOC Dashboard" sub="Live view of network health. Alarms are grouped into incidents by the correlation agent, so engineers work on causes rather than symptoms." />
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-5">
        {stat("Network health", d ? `${d.network_health_pct}%` : "-", d?.network_health_pct < 90 ? "text-major" : "text-ok")}
        {stat("Active alarms", d?.active_alarms)}
        {stat("Critical alarms", d?.critical_alarms, d?.critical_alarms ? "text-crit" : "text-txt")}
        {stat("Correlated incidents", d?.correlated_incidents)}
        {stat("Pending approvals", d?.pending_approvals, d?.pending_approvals ? "text-major" : "text-txt")}
        {stat("Active anomalies", d?.active_anomalies?.length)}
      </div>
      {d?.active_alarms > 0 && <p className="text-sm text-mute mb-4">Alarm reduction: <span className="text-txt">{d.alarm_reduction}</span></p>}

      <div className="grid lg:grid-cols-3 gap-4">
        <Panel title="Active incidents" className="lg:col-span-2">
          {!d?.incidents?.length ? <Empty>No active incidents. Run a scenario on the right to generate network events.</Empty> :
            <table className="w-full"><thead><tr><th className="th">Incident</th><th className="th">Title</th><th className="th">Severity</th><th className="th">Status</th></tr></thead>
              <tbody>{d.incidents.map((i: any) => (
                <tr key={i.id}><td className="td id"><Link className="text-sig" to={`/incidents/${i.id}`}>{i.id}</Link></td><td className="td">{i.title}</td>
                  <td className="td"><Badge v={i.severity} /></td><td className="td"><Badge kind="status" v={i.status} /></td></tr>))}</tbody></table>}
        </Panel>

        <Panel title="Scenario simulator" right={<button className="btn btn-danger" onClick={reset} disabled={!!busy}><RotateCcw size={14} />Reset</button>}>
          <p className="text-xs text-mute mb-3">Injects simulated SNMP traps, syslog lines and telemetry into the real ingestion pipeline.</p>
          <div className="space-y-2">
            {scenarios?.map((s) => (
              <button key={s.id} onClick={() => run(s.id)} disabled={!!busy} className="w-full text-left panel px-3 py-2 hover:border-sig disabled:opacity-50">
                <div className="flex items-center gap-2 text-sm font-medium"><Play size={13} className="text-sig" />{s.id.replace(/_/g, " ")}{busy === s.id && <span className="text-xs text-mute">sending...</span>}</div>
                <div className="text-xs text-mute mt-0.5">{s.description}</div>
              </button>
            ))}
          </div>
          {msg && <p className="text-xs mt-3 text-sig">{msg}</p>}
        </Panel>

        <Panel title="Affected network elements">
          {d?.affected_elements?.length ? <div className="flex flex-wrap gap-1.5">{d.affected_elements.map((x: string) => <span key={x} className="id px-1.5 py-0.5 border border-major/40 text-major rounded">{x}</span>)}</div> : <Empty>None</Empty>}
          <div className="mt-4 text-sm text-mute">Devices: <span className="text-ok">{d?.device_status?.up} up</span> / <span className="text-major">{d?.device_status?.degraded} degraded</span> / <span className="text-crit">{d?.device_status?.down} down</span></div>
          <div className="text-sm text-mute mt-1">Service-impacting incidents: <span className="text-txt">{d?.service_impact_incidents}</span></div>
        </Panel>

        <Panel title="Active anomalies (last 30 min)">
          {d?.active_anomalies?.length ? <ul className="space-y-1.5">{d.active_anomalies.slice(0, 8).map((a: any) => (
            <li key={a.device} className="text-sm flex justify-between gap-2"><span className="id">{a.device}</span><span className="text-mute">{a.pattern.replace(/_/g, " ")}</span><span className="text-major">{a.score}</span></li>))}</ul> : <Empty>No anomalies</Empty>}
        </Panel>

        <Panel title="Restoration actions">
          {d && Object.entries(d.restoration_actions).map(([k, v]: any) => <div key={k} className="flex justify-between text-sm py-0.5"><Badge kind="status" v={k} /><span>{v}</span></div>)}
          <div className="mt-3 text-sm"><span className="text-mute">Open escalations:</span> {d?.open_escalations?.length ? d.open_escalations.map((e: any) => <Link key={e.id} to={`/incidents/${e.id}`} className="id text-crit mr-2">{e.id}</Link>) : "none"}</div>
          <div className="mt-1 text-sm"><span className="text-mute">Recently resolved:</span> {d?.recently_resolved?.length ? d.recently_resolved.map((e: any) => <Link key={e.id} to={`/incidents/${e.id}`} className="id text-ok mr-2">{e.id}</Link>) : "none"}</div>
        </Panel>
      </div>
    </div>
  );
}
