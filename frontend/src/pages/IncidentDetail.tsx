// pages/IncidentDetail.tsx - one incident end-to-end (Requirements 4, 12-17):
// overview + correlation (confirm/reject), performance, fault, impact, RCA, plan, timeline,
// agent trace, plus the engineer controls: re-analyze, comment, escalate, simulate restoration,
// validate, confirm root cause, close, download PDF. Shows dynamic-reassessment notifications.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { API, post } from "../api";
import { usePoll } from "../hooks";
import { Badge, Evidence, Panel, PageHeader, Empty, fmtTime, KV } from "../components/ui";
import { FaultView, ImpactView, PerfView, PlanView, RCAView } from "../components/IncidentViews";
import { AgentTrace } from "./AgentExecution";

const TABS = ["Overview", "Performance", "Fault", "Impact", "RCA", "Plan", "Timeline", "Agents"] as const;

export default function IncidentDetail() {
  const { id } = useParams();
  const { data: inc, reload } = usePoll<any>(`/api/incidents/${id}`, 4000);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [note, setNote] = useState("");
  const [rc, setRc] = useState("");
  const [msg, setMsg] = useState("");

  async function act(path: string, body?: any, ok = "Done") {
    setMsg("");
    try { await post(path, body); setMsg(ok); reload(); } catch (e: any) { setMsg(e.message); }
  }
  if (!inc) return <Empty>Loading...</Empty>;
  const c = inc.correlation || {};
  const unread = (inc.notifications || []).filter((n: any) => !n.acknowledged);

  return (
    <div>
      <PageHeader title={`${inc.id}`} sub={inc.title}
        right={<div className="flex flex-wrap gap-2">
          <Badge v={inc.severity} /><span className="panel px-2 py-1 text-xs">status: <Badge kind="status" v={inc.status} /></span>
          <span className="panel px-2 py-1 text-xs">revision {inc.revision}</span>
          <a className="btn" href={`${API}/api/incidents/${inc.id}/report.pdf`}>Download PDF</a>
        </div>} />
      {inc.status === "analyzing" && <div className="panel px-4 py-2 mb-4 text-sm text-sig">Agents are analyzing this incident...</div>}
      {unread.length > 0 && (
        <div className="panel border-major px-4 py-3 mb-4">
          <div className="text-sm font-medium text-major mb-1">Incident reassessed - new alarm(s) arrived while it was active</div>
          {unread.map((n: any, i: number) => <div key={i} className="text-sm">Rev {n.revision}: {n.material_changes.join("; ")}</div>)}
          <button className="btn mt-2" onClick={() => act(`/api/incidents/${inc.id}/notifications/ack`)}>Acknowledge</button>
        </div>
      )}
      <div className="flex flex-wrap gap-1 mb-4 border-b border-line">
        {TABS.map((t) => <button key={t} onClick={() => setTab(t)} className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === t ? "border-sig text-sig" : "border-transparent text-mute hover:text-txt"}`}>{t}</button>)}
      </div>

      {tab === "Overview" && (
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <Panel title="Alarm correlation" right={<span className="text-xs">engineer decision: <Badge kind="status" v={inc.correlation_confirmed === "confirmed" ? "approved" : inc.correlation_confirmed === "rejected" ? "rejected" : "proposed"} /></span>}>
              {c.primary ? <>
                <p className="text-sm mb-2"><span className="text-mute">Primary suspected event: </span><span className="id">{c.primary.device}</span> {c.primary.type} {c.primary.interface} at {fmtTime(c.primary.time)}</p>
                <div className="grid md:grid-cols-2 gap-4">
                  <div><h2 className="text-sm mb-1">Consequential ({c.consequential.length})</h2>{c.consequential.slice(0, 12).map((a: any) => <div key={a.id} className="text-xs id">{fmtTime(a.time)} {a.device} {a.type}</div>)}</div>
                  <div><h2 className="text-sm mb-1">Reasoning</h2><Evidence items={c.reasoning} tone="sig" />
                    <p className="text-xs text-mute mt-2">Duplicates suppressed: {c.duplicate_count}. Independent: {c.independent.length}. {c.storm && <span className="text-crit">Alarm storm: {c.storm_summary?.total_alarms} alarms.</span>}</p></div>
                </div>
                <div className="flex gap-2 mt-3">
                  <button className="btn" onClick={() => act(`/api/incidents/${inc.id}/correlation`, { decision: "confirm" }, "Correlation confirmed")}>Confirm correlation</button>
                  <button className="btn btn-danger" onClick={() => act(`/api/incidents/${inc.id}/correlation`, { decision: "reject", remarks: note }, "Correlation rejected")}>Reject correlation</button>
                </div></> : <Empty>Analysis pending</Empty>}
            </Panel>
            <Panel title="Diagnosis at a glance">
              <KV items={[["Fault location", inc.fault_localization?.headline], ["Suspected root cause", inc.rca?.top_suspected], ["Service impact", inc.service_impact?.summary],
                ["Anomalies", inc.performance?.summary], ["Reviewer verdict", inc.review?.verdict], ["Reviewer comments", (inc.review?.comments || []).join("; ") || "none"]]} />
            </Panel>
            <Panel title="Raw alarms in this incident (audit)">
              <div className="max-h-64 overflow-y-auto">{inc.alarms.map((a: any) => <div key={a.id} className={`text-xs id py-0.5 ${a.role === "duplicate" ? "opacity-50" : ""}`}>{fmtTime(a.timestamp)} {a.device} {a.alarm_type} [{a.role}] ({a.source_format}) {a.status}</div>)}</div>
            </Panel>
          </div>
          <div className="space-y-4">
            <Panel title="Engineer controls">
              <div className="flex flex-col gap-2">
                <button className="btn" onClick={() => act(`/api/incidents/${inc.id}/reanalyze`, undefined, "Re-analysis started")}>Re-run agents</button>
                <Link className="btn justify-center" to="/approvals">Review and approve actions</Link>
                <button className="btn" onClick={() => act(`/api/simulate/restore/${inc.id}`, undefined, "Restoration simulated and validated")}>Simulate restoration + validate</button>
                <button className="btn" onClick={() => act(`/api/incidents/${inc.id}/validate`, undefined, "Validation complete")}>Run validation only</button>
                <textarea className="input" rows={2} placeholder="Comment / escalation reason" value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="flex gap-2">
                  <button className="btn flex-1 justify-center" onClick={() => note && act(`/api/incidents/${inc.id}/comment`, { text: note }, "Comment added")}>Comment</button>
                  <button className="btn btn-danger flex-1 justify-center" onClick={() => act(`/api/incidents/${inc.id}/escalate`, { text: note || "escalated" }, "Escalated")}>Escalate</button>
                </div>
                <input className="input" placeholder="Confirmed root cause" value={rc} onChange={(e) => setRc(e.target.value)} />
                <button className="btn" onClick={() => rc && act(`/api/incidents/${inc.id}/root-cause`, { root_cause: rc }, "Root cause confirmed")}>Confirm root cause</button>
                <button className="btn btn-primary" onClick={() => act(`/api/incidents/${inc.id}/close`, { author: "noc.engineer", text: note || "restored and verified" }, "Incident closed")}>Close incident</button>
              </div>
              {msg && <p className="text-xs text-sig mt-2">{msg}</p>}
            </Panel>
            <Panel title="Post-restoration validation">
              {inc.validation?.summary ? <>
                <p className={`text-sm mb-2 ${inc.validation.passed ? "text-ok" : "text-crit"}`}>{inc.validation.summary}</p>
                {inc.validation.metrics.map((m: any) => <div key={m.device} className="text-xs py-1 border-b border-line/50"><span className="id">{m.device}</span>
                  {["latency_ms", "packet_loss_pct", "jitter_ms"].map((k) => <div key={k} className="flex justify-between"><span className="text-mute">{k}</span><span>{m[k].baseline} / {m[k].during ?? "-"} / <b className={m[k].pass ? "text-ok" : "text-crit"}>{m[k].after}</b></span></div>)}</div>)}
                <p className="text-[11px] text-mute mt-1">baseline / during incident / after restoration</p></> : <Empty>Not run yet</Empty>}
            </Panel>
            <Panel title="Comments">{inc.comments?.length ? inc.comments.map((c: any, i: number) => <div key={i} className="text-xs py-1"><span className="text-mute">{fmtTime(c.time)} {c.author}:</span> {c.text}</div>) : <Empty>None</Empty>}</Panel>
          </div>
        </div>
      )}
      {tab === "Performance" && <PerfView inc={inc} />}
      {tab === "Fault" && <FaultView inc={inc} />}
      {tab === "Impact" && <ImpactView inc={inc} />}
      {tab === "RCA" && <RCAView inc={inc} />}
      {tab === "Plan" && <PlanView inc={inc} />}
      {tab === "Timeline" && <Panel title="Incident timeline"><ol className="border-l border-line ml-2">{inc.timeline.map((t: any, i: number) => <li key={i} className="pl-4 py-1.5 relative text-sm"><span className="absolute -left-[5px] top-3 w-2.5 h-2.5 rounded-full bg-sig" /><span className="id text-mute mr-2">{fmtTime(t.time)}</span>{t.event}</li>)}</ol></Panel>}
      {tab === "Agents" && <AgentTrace incidentId={inc.id} />}
    </div>
  );
}
