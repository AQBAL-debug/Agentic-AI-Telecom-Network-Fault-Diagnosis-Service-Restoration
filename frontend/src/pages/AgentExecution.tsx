// pages/AgentExecution.tsx - Agent Execution Visibility (Requirement 19). Shows the LangGraph
// pipeline and, step by step, for the chosen incident: which agent ran, its input, tool calls
// (topology queries, anomaly model, RAG retrieval), LLM calls, agent-to-agent messages,
// outputs, the critic's review and human decisions. Also lists every agent's system prompt.
import { useState } from "react";
import { useIncidentId, usePoll } from "../hooks";
import { IncidentPicker, Panel, PageHeader, Empty, fmtTime } from "../components/ui";

const TYPE_COLOR: Record<string, string> = { input: "text-mute", tool_call: "text-sig", llm: "text-[#C4A1FF]", output: "text-ok", message: "text-major", review: "text-crit", human: "text-txt" };
const STAGES = ["1-Intake", "2-Correlation", "4-Performance", "3-Topology", "5-Impact", "6-RCA", "7-Restoration", "8-Critic"];

export function AgentTrace({ incidentId }: { incidentId: string }) {
  const [run, setRun] = useState<string>("");
  const { data } = usePoll<any>(`/api/incidents/${incidentId}/agent-logs${run ? `?run_id=${run}` : ""}`, 5000);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  if (!data) return <Empty>Loading...</Empty>;
  const steps = data.steps.filter((s: any) => !filter || s.step_type === filter);
  const ran = new Set(data.steps.map((s: any) => s.agent));
  const current = [...data.steps].reverse().find((s: any) => s.agent.match(/^\d/))?.agent;
  return (
    <div className="space-y-4">
      <div className="panel p-3 flex flex-wrap items-center gap-1 text-xs">
        {STAGES.map((s, i) => <span key={s} className="flex items-center gap-1"><span className={`px-2 py-1 rounded border ${s === current ? "border-sig text-sig" : ran.has(s) ? "border-ok/50 text-ok" : "border-line text-mute"}`}>{s}</span>{i < STAGES.length - 1 && <span className="text-mute">&gt;</span>}</span>)}
        <span className="text-mute ml-1">&gt; human approval</span>
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        <select className="input" value={run || data.run_id || ""} onChange={(e) => setRun(e.target.value)} aria-label="Run">{data.runs.map((r: string) => <option key={r}>{r}</option>)}</select>
        <select className="input" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Step type"><option value="">all steps</option>{Object.keys(TYPE_COLOR).map((t) => <option key={t}>{t}</option>)}</select>
        <span className="text-sm text-mute">{steps.length} steps. Runs are re-created on every reassessment.</span>
      </div>
      <div className="panel divide-y divide-line/60">
        {steps.map((s: any) => (
          <div key={s.id} className="px-4 py-2">
            <button className="w-full text-left flex flex-wrap gap-3 items-baseline" onClick={() => setOpen(open === s.id ? null : s.id)}>
              <span className="id text-xs text-mute w-20">{fmtTime(s.timestamp)}</span><span className="text-sm w-32">{s.agent}</span>
              <span className={`text-xs w-20 ${TYPE_COLOR[s.step_type]}`}>{s.step_type}</span>
              <span className="text-xs text-mute truncate flex-1 min-w-0">{s.step_type === "tool_call" ? s.content.tool : s.step_type === "message" ? `to ${s.content.to}: ${s.content.content}` : JSON.stringify(s.content).slice(0, 140)}</span>
            </button>
            {open === s.id && <pre className="text-xs id whitespace-pre-wrap break-all mt-2 bg-ink p-3 rounded max-h-96 overflow-auto">{JSON.stringify(s.content, null, 2)}</pre>}
          </div>))}
      </div>
    </div>
  );
}

export default function AgentExecution() {
  const [id, setId, list] = useIncidentId();
  const { data: agents } = usePoll<any>("/api/agents", 0);
  return (
    <div>
      <PageHeader title="Agent Execution" sub="Every step of the multi-agent workflow: inputs, tool calls, retrieved documents, model results, hypotheses, reviewer feedback and human decisions."
        right={<IncidentPicker id={id} setId={setId} list={list} />} />
      {id ? <AgentTrace incidentId={id} /> : <Empty>No incidents yet.</Empty>}
      <Panel title="Agent system prompts" className="mt-6">
        {agents && Object.entries(agents.prompts).map(([k, v]: any) => <details key={k} className="py-1.5 border-b border-line/60"><summary className="text-sm cursor-pointer">{k} agent</summary><pre className="text-xs whitespace-pre-wrap text-mute mt-1">{v}</pre></details>)}
      </Panel>
    </div>
  );
}
