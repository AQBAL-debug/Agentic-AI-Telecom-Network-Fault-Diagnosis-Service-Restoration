// pages/Inventory.tsx - Network Inventory (Requirement 1): list, add and delete network elements
// with id, name, type, region, IP, vendor, model, status, interfaces, connected devices, services.
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { del, post } from "../api";
import { usePoll } from "../hooks";
import { Badge, Panel, PageHeader } from "../components/ui";

const EMPTY = { id: "", name: "", device_type: "base_station", layer: 2, region: "", ip_address: "", vendor: "", model: "", interfaces: "", services: "", connected_to: "" };

export default function Inventory() {
  const { data, reload } = usePoll<any[]>("/api/devices", 10000);
  const [f, setF] = useState<any>(EMPTY);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  async function save() {
    setErr("");
    try {
      await post("/api/devices", { ...f, layer: Number(f.layer), interfaces: split(f.interfaces), services: split(f.services), connected_to: split(f.connected_to) });
      setF(EMPTY); setOpen(false); reload();
    } catch (e: any) { setErr(e.message); }
  }
  async function remove(id: string) { if (confirm(`Delete ${id} and its links?`)) { await del(`/api/devices/${id}`); reload(); } }
  const field = (k: string, label: string, ph = "") => (
    <label className="text-xs text-mute flex flex-col gap-1">{label}<input className="input text-txt" value={f[k]} placeholder={ph} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );

  return (
    <div>
      <PageHeader title="Network Inventory" sub="Network elements the agents reason about. Connected devices define the topology used for correlation and fault localization."
        right={<button className="btn btn-primary" onClick={() => setOpen(!open)}><Plus size={14} />Add device</button>} />
      {open && (
        <Panel title="New network element" className="mb-4">
          <div className="grid sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {field("id", "Device ID", "BS-105")}{field("name", "Name", "Base Station 105")}
            <label className="text-xs text-mute flex flex-col gap-1">Type
              <select className="input text-txt" value={f.device_type} onChange={(e) => setF({ ...f, device_type: e.target.value, layer: ["core_router", "internet_gateway"].includes(e.target.value) ? 0 : e.target.value === "aggregation_router" ? 1 : 2 })}>
                {["core_router", "aggregation_router", "switch", "base_station", "enterprise_gw"].map((t) => <option key={t}>{t}</option>)}
              </select></label>
            {field("region", "Region", "North")}{field("ip_address", "IP / identifier", "10.2.0.50")}{field("vendor", "Vendor")}{field("model", "Model")}
            {field("interfaces", "Interfaces (comma separated)", "eth0, eth1")}{field("connected_to", "Upstream devices (comma separated)", "AR-01")}{field("services", "Supported services", "SVC-BS-105")}
          </div>
          {err && <p className="text-crit text-sm mt-2">{err}</p>}
          <button className="btn btn-primary mt-3" onClick={save}>Save device</button>
        </Panel>
      )}
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[900px]">
          <thead><tr>{["ID", "Name", "Type", "Region", "IP", "Vendor / model", "Status", "Interfaces", "Connected", "Services", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{data?.map((d) => (
            <tr key={d.id}>
              <td className="td id">{d.id}</td><td className="td">{d.name}</td><td className="td text-mute">{d.device_type.replace(/_/g, " ")}</td><td className="td">{d.region}</td>
              <td className="td id text-mute">{d.ip_address}</td><td className="td">{d.vendor} {d.model}</td><td className="td"><Badge kind="status" v={d.status} /></td>
              <td className="td text-xs id text-mute">{d.interfaces.join(", ")}</td><td className="td text-xs id">{d.connected_devices.join(", ")}</td>
              <td className="td text-xs id">{d.services.join(", ")}</td>
              <td className="td"><button className="text-mute hover:text-crit" aria-label={`Delete ${d.id}`} onClick={() => remove(d.id)}><Trash2 size={14} /></button></td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}
