// pages/Topology.tsx - interactive Network Topology (Requirement 2) built with React Flow.
// Nodes are laid out by depth from the internet gateway (core -> aggregation -> access);
// colour = live status, dashed edges = backup/redundant links, red edges = down.
// Clicking a node shows its operational details (upstream/downstream, services, telemetry, alarms);
// clicking a link shows interfaces, medium, capacity and status.
import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, Edge, MarkerType, Node } from "reactflow";
import "reactflow/dist/style.css";
import { get } from "../api";
import { usePoll } from "../hooks";
import { Badge, KV, Panel, PageHeader, Empty, fmtTime } from "../components/ui";

const COLOR: Record<string, string> = { up: "#34D399", degraded: "#F59E0B", down: "#F0525B" };

function layout(nodes: any[], edges: any[]) {
  const parents: Record<string, string[]> = {};
  edges.forEach((e) => { (parents[e.target] ||= []).push(e.source); });
  const depth: Record<string, number> = {};
  const roots = nodes.filter((n) => !parents[n.id]).map((n) => n.id);
  const queue = [...roots]; roots.forEach((r) => (depth[r] = 0));
  while (queue.length) {
    const cur = queue.shift()!;
    edges.filter((e) => e.source === cur && !e.is_backup).forEach((e) => {
      if (depth[e.target] === undefined) { depth[e.target] = depth[cur] + 1; queue.push(e.target); }
    });
  }
  const rows: Record<number, any[]> = {};
  nodes.forEach((n) => (rows[depth[n.id] ?? 4] ||= []).push(n));
  const x: Record<string, number> = {};
  Object.keys(rows).map(Number).sort().forEach((d) => {
    rows[d].sort((a, b) => {
      const pa = (parents[a.id] || []).map((p) => x[p] ?? 0), pb = (parents[b.id] || []).map((p) => x[p] ?? 0);
      return (Math.min(...pa, 1e9) - Math.min(...pb, 1e9)) || a.id.localeCompare(b.id);
    });
    const w = 150;
    rows[d].forEach((n, i) => (x[n.id] = (i - (rows[d].length - 1) / 2) * w));
  });
  return { x, depth };
}

export default function Topology() {
  const { data } = usePoll<any>("/api/topology", 5000);
  const [sel, setSel] = useState<any>(null);
  const [link, setLink] = useState<any>(null);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] };
    const { x, depth } = layout(data.nodes, data.edges);
    const nodes: Node[] = data.nodes.map((n: any) => ({
      id: n.id, position: { x: x[n.id], y: (depth[n.id] ?? 4) * 120 },
      data: { label: <div className="text-center leading-tight"><div className="font-mono text-[12px]">{n.id}</div><div className="text-[10px] opacity-70">{n.device_type.replace(/_/g, " ")}</div>{n.active_alarms > 0 && <div className="text-[10px] text-[#F0525B]">{n.active_alarms} alarms</div>}</div> },
      style: { background: "#16233A", color: "#DCE6F2", border: `2px solid ${COLOR[n.status] || "#8597B0"}`, borderRadius: 6, width: 120, padding: 6,
               boxShadow: n.status !== "up" ? `0 0 14px ${COLOR[n.status]}66` : "none" },
    }));
    const edges: Edge[] = data.edges.map((e: any) => ({
      id: e.id, source: e.source, target: e.target, data: e,
      style: { stroke: e.status === "down" ? "#F0525B" : e.is_backup ? "#8597B0" : "#4CC3E8", strokeWidth: 2, strokeDasharray: e.is_backup ? "6 4" : undefined },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#4CC3E8" },
    }));
    return { nodes, edges };
  }, [data]);

  return (
    <div>
      <PageHeader title="Network Topology" sub="Select a device or link to see its operational state. Dashed lines are redundant backup paths; red means down." />
      <div className="grid lg:grid-cols-[1fr_340px] gap-4">
        <div className="panel h-[640px]">
          <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
            onNodeClick={async (_, n) => { setLink(null); setSel(await get(`/api/topology/node/${n.id}`)); }}
            onEdgeClick={(_, e) => { setSel(null); setLink(e.data); }}>
            <Background color="#24344F" gap={24} /><Controls />
          </ReactFlow>
        </div>
        <Panel title={sel ? sel.device.id : link ? link.id : "Details"}>
          {!sel && !link && <Empty>Click a node or a link</Empty>}
          {sel && (
            <div className="space-y-4">
              <KV items={[["Name", sel.device.name], ["Type", sel.device.device_type], ["Status", <Badge kind="status" v={sel.device.status} />],
                ["Region", sel.device.region], ["IP", <span className="id">{sel.device.ip_address}</span>], ["Vendor", `${sel.device.vendor} ${sel.device.model}`],
                ["Upstream", sel.upstream.join(", ") || "-"], ["Downstream", sel.downstream.join(", ") || "-"], ["Path to core", sel.path_to_core.join(" > ")],
                ["Services", sel.services.join(", ") || "-"], ["If it fails, isolates", sel.if_failed_isolates.join(", ") || "nothing (redundant)"]]} />
              {sel.latest_telemetry && <div><h2 className="mb-2">Latest telemetry</h2>
                <KV items={[["Latency", `${sel.latest_telemetry.latency_ms.toFixed(1)} ms`], ["Packet loss", `${sel.latest_telemetry.packet_loss_pct.toFixed(2)} %`],
                  ["Jitter", `${sel.latest_telemetry.jitter_ms.toFixed(1)} ms`], ["Utilization", `${sel.latest_telemetry.utilization_pct.toFixed(0)} %`],
                  ["CPU / memory", `${sel.latest_telemetry.cpu_pct.toFixed(0)} % / ${sel.latest_telemetry.memory_pct.toFixed(0)} %`], ["Link", sel.latest_telemetry.link_up ? "up" : "down"]]} /></div>}
              <div><h2 className="mb-2">Recent alarms</h2>
                {sel.recent_alarms.length ? sel.recent_alarms.map((a: any) => <div key={a.id} className="text-xs flex justify-between py-0.5"><span>{fmtTime(a.time)} {a.type}</span><Badge kind="status" v={a.status} /></div>) : <p className="text-xs text-mute">None</p>}</div>
            </div>
          )}
          {link && <KV items={[["From", `${link.source} (${link.source_interface})`], ["To", `${link.target} (${link.target_interface})`], ["Medium", link.link_type],
            ["Capacity", `${link.capacity_mbps} Mbps`], ["Backup path", link.is_backup ? "yes" : "no"], ["Status", <Badge kind="status" v={link.status} />]]} />}
        </Panel>
      </div>
    </div>
  );
}
