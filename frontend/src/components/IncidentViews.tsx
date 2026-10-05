// components/IncidentViews.tsx - the analysis blocks of one incident, shared between the
// Incident Detail page and the dedicated Fault Localization / Service Impact / RCA /
// Restoration pages, so both show exactly the same agent output.
import { Badge, Category, Evidence, KV, Panel, Empty } from "./ui";

export function FaultView({ inc }: { inc: any }) {
  const fl = inc.fault_localization || {};
  const top = fl.primary;
  if (!top) return <Empty>Analysis pending</Empty>;
  return (
    <div className="space-y-4">
      <Panel title="Primary suspected fault location" right={<Badge v={top.confidence} />}>
        <p className="text-lg mb-1"><span className="id">{top.location}</span> <span className="text-mute text-sm">({top.type}{top.interfaces ? `: ${top.interfaces.join(" <-> ")}` : ""})</span></p>
        <p className="text-sm text-mute mb-3">Score {top.score} - explains {top.explained_devices.length} device(s). Path to core: {fl.path_to_core?.join(" > ")}</p>
        <div className="grid md:grid-cols-2 gap-4">
          <div><h2 className="mb-2 text-sm">Topology evidence</h2><Evidence items={top.evidence} /></div>
          <div><h2 className="mb-2 text-sm">Contradicting evidence</h2><Evidence items={top.contradicting_evidence} tone="crit" /></div>
          <div><h2 className="mb-2 text-sm">Supporting alarms</h2><Evidence items={top.supporting_alarms} tone="sig" /></div>
          <div><h2 className="mb-2 text-sm">Telemetry evidence</h2><Evidence items={top.telemetry_evidence} tone="sig" /></div>
        </div>
        <p className="text-xs text-mute mt-3">The engineer must still verify this location; it is a ranked hypothesis, not a confirmed fault.</p>
      </Panel>
      <Panel title="Alternative hypotheses">
        <table className="w-full"><thead><tr>{["Location", "Type", "Score", "Confidence", "Why not first"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{fl.alternatives?.map((h: any) => <tr key={h.location}><td className="td id">{h.location}</td><td className="td">{h.type}</td><td className="td">{h.score}</td>
            <td className="td"><Badge v={h.confidence} /></td><td className="td text-xs">{h.contradicting_evidence?.join("; ") || "lower score"}</td></tr>)}</tbody></table>
      </Panel>
    </div>
  );
}

export function ImpactView({ inc }: { inc: any }) {
  const im = inc.service_impact || {};
  if (!im.summary) return <Empty>Analysis pending</Empty>;
  return (
    <div className="space-y-4">
      <Panel title="Impact summary"><p className="text-sm">{im.summary}</p>
        <div className="mt-3"><KV items={[["Unavailable devices", im.unavailable_devices?.join(", ") || "none"], ["Degraded devices", im.degraded_devices?.join(", ") || "none"],
          ["Affected base stations", im.affected_base_stations?.join(", ") || "none"], ["Service groups", im.service_groups?.join(", ") || "none"],
          ["Regions", im.regions?.join(", ") || "none"], ["Known customers", im.customers_known_total],
          ["Unknown customer counts", im.services_with_unknown_customers?.join(", ") || "none"]]} /></div></Panel>
      <Panel title="Affected services">
        <table className="w-full"><thead><tr>{["Service", "Name", "Status", "Region", "Customers", "Reason"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{im.affected_services?.map((s: any) => <tr key={s.service_id}><td className="td id">{s.service_id}</td><td className="td">{s.name}</td><td className="td"><Badge kind="status" v={s.status} /></td>
            <td className="td">{s.region}</td><td className="td">{s.customers}</td><td className="td text-xs text-mute">{s.reason}</td></tr>)}</tbody></table>
      </Panel>
      <div className="grid md:grid-cols-2 gap-4">
        <Panel title="Redundancy status"><Evidence items={im.redundancy} tone="sig" /></Panel>
        <Panel title="Affected links">{im.affected_links?.map((l: any) => <div key={l.link} className="text-sm id">{l.link} {l.backup && <span className="text-mute">(backup)</span>}</div>)}</Panel>
      </div>
    </div>
  );
}

export function RCAView({ inc }: { inc: any }) {
  const r = inc.rca || {};
  if (!r.hypotheses) return <Empty>Analysis pending</Empty>;
  return (
    <div className="space-y-4">
      <Panel title="Root cause status" right={inc.confirmed_root_cause ? <Badge v="high" /> : <Badge v="medium" />}>
        <p className="text-sm">{inc.confirmed_root_cause ? <><b>Confirmed:</b> {inc.confirmed_root_cause}</> : <><b>Suspected</b> (not confirmed): {r.summary}</>}</p>
        <p className="text-xs text-mute mt-2">LLM: {r.llm?.used ? `used (${r.llm.model}, ${r.llm.latency_s}s)` : r.llm?.reason}</p>
      </Panel>
      {r.hypotheses.map((h: any) => (
        <Panel key={h.category} title={`${h.rank}. ${h.hypothesis}`} right={<span className="text-sm">confidence <b>{h.confidence}</b></span>}>
          <div className="grid md:grid-cols-3 gap-4">
            <div><h2 className="text-sm mb-2">Supporting evidence</h2><Evidence items={h.supporting_evidence} /></div>
            <div><h2 className="text-sm mb-2">Contradicting evidence</h2><Evidence items={h.contradicting_evidence} tone="crit" /></div>
            <div><h2 className="text-sm mb-2">Required verification</h2><Evidence items={h.required_verification} tone="sig" /></div>
          </div>
          {h.llm_reasoning && <p className="text-xs text-mute mt-3">LLM reasoning: {h.llm_reasoning}</p>}
        </Panel>
      ))}
      <Panel title="Similar historical incidents (evidence, not proof)">
        {inc.historical?.length ? inc.historical.map((h: any) => (
          <div key={h.id} className="text-sm py-2 border-b border-line/60 last:border-0"><span className="id text-sig">{h.id}</span> {h.title} <span className="text-mute">- similarity {h.similarity}</span>
            <div className="text-xs text-mute">Root cause: {h.root_cause}. Resolution: {h.resolution}. MTTR {h.mttr_minutes} min.</div></div>)) : <Empty>None found</Empty>}
      </Panel>
      {r.evidence_sources?.changes?.length > 0 && <Panel title="Change / maintenance history">{r.evidence_sources.changes.map((c: any) => <div key={c.id} className="text-sm">{c.id} {c.time} {c.description}</div>)}</Panel>}
    </div>
  );
}

export function PlanView({ inc }: { inc: any }) {
  const p = inc.restoration_plan || {};
  if (!p.actions) return <Empty>Analysis pending</Empty>;
  return (
    <div className="space-y-4">
      <Panel title="Plan rationale"><p className="text-sm">{p.rationale}</p>{p.engineer_briefing && <p className="text-sm text-mute mt-2">{p.engineer_briefing}</p>}
        {p.revision_after_review && <p className="text-xs text-major mt-2">Plan was revised after the critic agent requested rework.</p>}</Panel>
      <Panel title="Recommended actions">
        <table className="w-full"><thead><tr>{["Step", "Action", "Class", "Approval", "Team", "Procedure", "Status"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{(inc.actions || []).map((a: any) => <tr key={a.id}><td className="td">{a.step}</td><td className="td">{a.description}</td><td className="td"><Category v={a.category} /></td>
            <td className="td text-xs">{a.requires_approval ? <span className="text-crit">explicit</span> : "not required"}</td><td className="td text-xs">{a.assigned_to}</td>
            <td className="td text-xs text-mute">{a.procedure_ref}</td><td className="td"><Badge kind="status" v={a.status} /></td></tr>)}</tbody></table>
      </Panel>
      <Panel title="Retrieved approved procedures (RAG)">
        {p.procedures?.map((s: any) => <details key={s.reference} className="py-2 border-b border-line/60 last:border-0"><summary className="text-sm cursor-pointer"><span className="text-sig">{s.reference}</span> <span className="text-mute">- {s.document}</span></summary>
          <pre className="text-xs whitespace-pre-wrap mt-2 text-mute">{s.text}</pre></details>)}
      </Panel>
    </div>
  );
}

export function PerfView({ inc }: { inc: any }) {
  const pf = inc.performance || {};
  if (!pf.devices_analyzed) return <Empty>Analysis pending</Empty>;
  return (
    <div className="space-y-4">
      <Panel title="Anomaly findings"><p className="text-sm mb-3">{pf.summary}</p>
        {pf.anomalies?.map((a: any, i: number) => <div key={i} className="text-sm py-1"><span className="id">{a.device}</span> - {a.pattern.replace(/_/g, " ")}, score {a.max_score}, {a.detected_by} <span className="text-mute text-xs">{JSON.stringify(a.top_metrics)}</span></div>)}</Panel>
      <Panel title="Investigation before blaming utilization">
        {pf.investigation?.map((c: any) => <div key={c.check} className="py-1.5 text-sm flex gap-3"><span className="w-64 shrink-0">{c.check}</span>
          <span className={c.result === "supported" || c.result === "suspected" ? "text-major" : c.result === "possible" ? "text-sig" : "text-mute"}>{c.result}</span>
          <span className="text-xs text-mute">{c.evidence.join("; ")}</span></div>)}
      </Panel>
      <Panel title="Before vs current">
        <div className="overflow-x-auto"><table className="w-full min-w-[640px]"><thead><tr>{["Device", "Latency ms", "Loss %", "Jitter ms", "Util %", "CPU %", "Link"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{Object.entries(pf.comparison || {}).map(([d, m]: any) => <tr key={d}><td className="td id">{d}</td>
            {["latency_ms", "packet_loss_pct", "jitter_ms", "utilization_pct", "cpu_pct", "link_up"].map((k) => <td key={k} className="td text-xs">{m[k].before ?? "-"} &gt; <b className={Math.abs(m[k].change_pct || 0) > 50 ? "text-major" : ""}>{m[k].current}</b></td>)}</tr>)}</tbody></table></div>
      </Panel>
    </div>
  );
}
