// pages/Reports.tsx - Incident Reports (Requirement 20): download the 16-section PDF report
// for any incident (timeline, alarms, topology, performance, impact, RCA, actions, approvals,
// validation, confirmed root cause, closure summary).
import { API } from "../api";
import { usePoll } from "../hooks";
import { Badge, PageHeader, Empty, fmtDate } from "../components/ui";

export default function Reports() {
  const { data } = usePoll<any[]>("/api/incidents", 8000);
  return (
    <div>
      <PageHeader title="Incident Reports" sub="Structured PDF report per incident, generated from the stored analysis, approvals and validation results." />
      <div className="panel">
        {!data?.length ? <Empty>No incidents yet.</Empty> :
          <table className="w-full"><thead><tr>{["Incident", "Title", "Status", "Created", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{data.map((i) => <tr key={i.id}><td className="td id">{i.id}</td><td className="td">{i.title}</td><td className="td"><Badge kind="status" v={i.status} /></td>
              <td className="td text-xs text-mute">{fmtDate(i.created_at)}</td>
              <td className="td"><a className="btn" href={`${API}/api/incidents/${i.id}/report.pdf`}>Download PDF</a></td></tr>)}</tbody></table>}
      </div>
    </div>
  );
}
