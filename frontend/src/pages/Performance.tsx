// pages/Performance.tsx - Performance Monitoring + Anomaly Detection (Requirements 6 and 7):
// pick a device, see latency / loss / jitter / utilization / CPU / memory / errors over time
// with anomaly points marked by the model, plus the model's documented evaluation results.
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis } from "recharts";
import { usePoll } from "../hooks";
import { Panel, PageHeader, Empty } from "../components/ui";

const METRICS = [["latency_ms", "Latency (ms)"], ["packet_loss_pct", "Packet loss (%)"], ["jitter_ms", "Jitter (ms)"], ["utilization_pct", "Utilization (%)"],
  ["cpu_pct", "CPU (%)"], ["memory_pct", "Memory (%)"], ["interface_errors", "Interface errors"], ["throughput_mbps", "Throughput (Mbps)"]];

export default function Performance() {
  const { data: devices } = usePoll<any[]>("/api/devices", 0);
  const [dev, setDev] = useState("AR-02");
  const [mins, setMins] = useState(360);
  const { data } = usePoll<any[]>(`/api/telemetry/${dev}?minutes=${mins}`, 10000);
  const { data: an } = usePoll<any[]>("/api/anomalies?minutes=60", 8000);
  const { data: mm } = usePoll<any>("/api/model/metrics", 0);
  const rows = (data || []).map((r) => ({ ...r, t: new Date(r.timestamp + "Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }));
  const anomalies = rows.filter((r) => r.anomaly).length;

  return (
    <div>
      <PageHeader title="Performance Monitoring" sub="Telemetry with anomaly detection. Each device is compared with its own baseline, so a 25 ms base station and an 8 ms core router are judged fairly."
        right={<div className="flex gap-2"><select className="input" value={dev} onChange={(e) => setDev(e.target.value)} aria-label="Device">{devices?.map((d) => <option key={d.id}>{d.id}</option>)}</select>
          <select className="input" value={mins} onChange={(e) => setMins(Number(e.target.value))} aria-label="Time range">{[[60, "1 h"], [360, "6 h"], [1440, "24 h"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>} />
      <p className="text-sm text-mute mb-3">{rows.length} samples, <span className={anomalies ? "text-major" : ""}>{anomalies} flagged anomalous</span> (orange dots).</p>
      {!rows.length ? <Empty>No telemetry in this range.</Empty> :
        <div className="grid md:grid-cols-2 gap-4 mb-6">
          {METRICS.map(([k, label]) => (
            <Panel key={k} title={label}>
              <div className="h-44"><ResponsiveContainer>
                <ComposedChart data={rows}>
                  <CartesianGrid stroke="#24344F" strokeDasharray="3 3" /><XAxis dataKey="t" tick={{ fill: "#8597B0", fontSize: 10 }} minTickGap={40} /><YAxis tick={{ fill: "#8597B0", fontSize: 10 }} width={45} />
                  <Tooltip contentStyle={{ background: "#16233A", border: "1px solid #24344F" }} />
                  <Line type="monotone" dataKey={k} stroke="#4CC3E8" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Scatter data={rows.filter((r) => r.anomaly)} dataKey={k} fill="#F59E0B" isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer></div>
            </Panel>))}
        </div>}
      <div className="grid lg:grid-cols-2 gap-4">
        <Panel title="Active anomalies (last 60 min)">
          {an?.length ? <table className="w-full"><thead><tr>{["Device", "Pattern", "Score", "Deviating metrics (sigma)"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{an.map((a) => <tr key={a.device}><td className="td id">{a.device}</td><td className="td">{a.pattern.replace(/_/g, " ")}</td><td className="td text-major">{a.score}</td>
              <td className="td text-xs">{a.top_metrics.map((m: any) => `${m[0]} ${m[1]}`).join(", ")}</td></tr>)}</tbody></table> : <Empty>No active anomalies</Empty>}
        </Panel>
        <Panel title="Anomaly model evaluation">
          {mm?.hybrid ? <>
            <p className="text-xs text-mute mb-2">{mm.method}. Dataset: {mm.dataset.rows} rows, {mm.dataset.devices} devices, {mm.dataset.labelled_anomalies} labelled anomalies (labels used only for evaluation).</p>
            <table className="w-full"><thead><tr>{["Method", "Precision", "Recall", "F1"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{["isolation_forest", "zscore_threshold", "hybrid"].map((k) => <tr key={k}><td className="td">{k.replace(/_/g, " ")}</td><td className="td">{mm[k].precision}</td><td className="td">{mm[k].recall}</td><td className="td font-medium">{mm[k].f1}</td></tr>)}</tbody></table>
            <div className="text-xs text-mute mt-3">Recall per anomaly type: {Object.entries(mm.recall_per_anomaly_type).map(([k, v]) => `${k} ${v}`).join(", ")}</div></> : <Empty>Model not trained</Empty>}
        </Panel>
      </div>
    </div>
  );
}
