// pages/Approvals.tsx - Approval Center (Requirement 14): engineer authorization.
// Approve, reject or modify each proposed action (modified text is re-classified for safety);
// potentially disruptive actions and escalations are highlighted and cannot run without approval.
import { useState } from "react";
import { Link } from "react-router-dom";
import { post } from "../api";
import { usePoll } from "../hooks";
import { Category, PageHeader, Empty } from "../components/ui";

export default function Approvals() {
  const { data, reload } = usePoll<any[]>("/api/actions?status=proposed", 4000);
  const [engineer, setEngineer] = useState("noc.lead");
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [remarks, setRemarks] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  async function decide(a: any, decision: string) {
    try {
      await post(`/api/actions/${a.id}/decision`, { decision, engineer, remarks: remarks[a.id] || "", new_description: decision === "modify" ? edit[a.id] : undefined });
      setMsg(`Action ${a.step} of ${a.incident_id} ${decision}d`); reload();
    } catch (e: any) { setMsg(e.message); }
  }
  const groups: Record<string, any[]> = {};
  (data || []).forEach((a) => (groups[a.incident_id] ||= []).push(a));

  return (
    <div>
      <PageHeader title="Approval Center" sub="Nothing is executed on the network without a person deciding. Red actions are potentially disruptive and require explicit approval."
        right={<label className="text-sm text-mute flex items-center gap-2">Approving as <input className="input text-txt" value={engineer} onChange={(e) => setEngineer(e.target.value)} /></label>} />
      {msg && <p className="text-sm text-sig mb-3">{msg}</p>}
      {!data?.length && <Empty>No actions awaiting a decision.</Empty>}
      {Object.entries(groups).map(([inc, acts]) => (
        <section key={inc} className="panel mb-4">
          <header className="px-4 py-2.5 border-b border-line flex justify-between"><Link to={`/incidents/${inc}`} className="id text-sig">{inc}</Link><span className="text-xs text-mute">{acts.length} proposed</span></header>
          {acts.map((a) => (
            <div key={a.id} className={`px-4 py-3 border-b border-line/60 last:border-0 ${a.category === "potentially_disruptive" ? "border-l-2 border-l-crit" : ""}`}>
              <div className="flex flex-wrap items-center gap-2 mb-2"><span className="text-mute text-sm">{a.step}.</span><span className="text-sm">{a.description}</span><Category v={a.category} />
                {a.requires_approval && <span className="text-xs text-crit">explicit approval required</span>}<span className="text-xs text-mute ml-auto">{a.procedure_ref}</span></div>
              <div className="flex flex-wrap gap-2">
                <input className="input flex-1 min-w-[14rem]" placeholder="Edit action text (then Modify)" value={edit[a.id] ?? ""} onChange={(e) => setEdit({ ...edit, [a.id]: e.target.value })} />
                <input className="input w-56" placeholder="Remarks" value={remarks[a.id] ?? ""} onChange={(e) => setRemarks({ ...remarks, [a.id]: e.target.value })} />
                <button className="btn btn-primary" onClick={() => decide(a, "approve")}>Approve</button>
                <button className="btn" onClick={() => edit[a.id] && decide(a, "modify")} disabled={!edit[a.id]}>Modify</button>
                <button className="btn btn-danger" onClick={() => decide(a, "reject")}>Reject</button>
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
