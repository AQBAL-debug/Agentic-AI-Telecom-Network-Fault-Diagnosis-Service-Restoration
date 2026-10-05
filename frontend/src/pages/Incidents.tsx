// pages/Incidents.tsx - Incident Center: every correlated incident with status, fault location,
// confidence, alarm count, affected services and unread reassessment notifications.
import { Link } from "react-router-dom";
import { usePoll } from "../hooks";
import { Badge, PageHeader, Empty, fmtDate } from "../components/ui";

export default function Incidents() {
  const { data } = usePoll<any[]>("/api/incidents", 4000);
  return (
    <div>
      <PageHeader title="Incident Center" sub="Correlated incidents. Open one to review the agents' analysis, confirm or reject the correlation, and drive restoration." />
      <div className="panel overflow-x-auto">
        {!data?.length ? <Empty>No incidents yet. Run a scenario from the dashboard.</Empty> :
          <table className="w-full min-w-[900px]"><thead><tr>{["Incident", "Title", "Severity", "Status", "Alarms", "Fault location", "Confidence", "Services hit", "Rev", "Created"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{data.map((i) => (
              <tr key={i.id} className="hover:bg-line/30">
                <td className="td id"><Link className="text-sig" to={`/incidents/${i.id}`}>{i.id}</Link>{i.unread_notifications > 0 && <span className="ml-2 text-[11px] bg-major text-ink rounded px-1">updated</span>}</td>
                <td className="td">{i.title}{i.storm && <span className="ml-2 text-xs text-crit">alarm storm</span>}</td>
                <td className="td"><Badge v={i.severity} /></td><td className="td"><Badge kind="status" v={i.status} /></td>
                <td className="td">{i.alarm_count}</td><td className="td id">{i.fault_location || "-"}</td><td className="td"><Badge v={i.confidence} /></td>
                <td className="td">{i.affected_services}</td><td className="td">{i.revision}</td><td className="td text-xs text-mute">{fmtDate(i.created_at)}</td>
              </tr>))}</tbody></table>}
      </div>
    </div>
  );
}
