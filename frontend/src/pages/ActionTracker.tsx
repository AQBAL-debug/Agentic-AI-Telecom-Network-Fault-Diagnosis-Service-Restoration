// pages/ActionTracker.tsx - Action Tracker (Requirement 15): every restoration action with
// incident, assigned team, approval status, start/completion time, result and remarks.
// Status flow: Proposed -> Approved -> In Progress -> Completed -> Verified (after validation).
import { useState } from "react";
import { post } from "../api";
import { usePoll } from "../hooks";
import { Badge, Category, PageHeader, Empty, fmtTime } from "../components/ui";

const FLOW = ["proposed", "approved", "in_progress", "completed", "verified"];

export default function ActionTracker() {
  const { data, reload } = usePoll<any[]>("/api/actions", 4000);
  const [result, setResult] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  async function setStatus(a: any, status: string) {
    try { await post(`/api/actions/${a.id}/status`, { status, result: result[a.id] || "" }); reload(); setMsg(""); } catch (e: any) { setMsg(e.message); }
  }
  return (
    <div>
      <PageHeader title="Action Tracker" sub="Proposed, approved, in progress, completed, verified. Diagnostic steps can start without approval; disruptive steps cannot." />
      <div className="flex gap-2 mb-3 text-xs">{FLOW.map((s, i) => <span key={s} className="flex items-center gap-2"><Badge kind="status" v={s} />{i < FLOW.length - 1 && <span className="text-mute">&gt;</span>}</span>)}</div>
      {msg && <p className="text-sm text-crit mb-3">{msg}</p>}
      <div className="panel overflow-x-auto">
        {!data?.length ? <Empty>No actions yet.</Empty> :
          <table className="w-full min-w-[1100px]"><thead><tr>{["Action", "Incident", "Step", "Recommended action", "Class", "Assigned", "Status", "Approved by", "Started", "Completed", "Result", "Update"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{data.map((a) => (
              <tr key={a.id}>
                <td className="td id text-xs">{a.id}</td><td className="td id text-xs">{a.incident_id}</td><td className="td">{a.step}</td><td className="td text-sm">{a.description}</td>
                <td className="td"><Category v={a.category} /></td><td className="td text-xs">{a.assigned_to}</td><td className="td"><Badge kind="status" v={a.status} /></td>
                <td className="td text-xs">{a.approved_by || "-"}</td><td className="td text-xs">{fmtTime(a.started_at)}</td><td className="td text-xs">{fmtTime(a.completed_at)}</td>
                <td className="td text-xs">{a.result}{a.remarks && <div className="text-mute">{a.remarks}</div>}</td>
                <td className="td">
                  {["proposed", "approved"].includes(a.status) && <button className="btn text-xs" onClick={() => setStatus(a, "in_progress")}>Start</button>}
                  {a.status === "in_progress" && <div className="flex gap-1"><input className="input w-32 text-xs" placeholder="result" value={result[a.id] ?? ""} onChange={(e) => setResult({ ...result, [a.id]: e.target.value })} />
                    <button className="btn text-xs" onClick={() => setStatus(a, "completed")}>Complete</button></div>}
                </td>
              </tr>))}</tbody></table>}
      </div>
    </div>
  );
}
