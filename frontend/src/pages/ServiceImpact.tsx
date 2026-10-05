// pages/ServiceImpact.tsx - Service Impact page: pick an incident and see the matching agent output
// (same component as the incident detail tab: components/IncidentViews.tsx -> ImpactView).
import { Link } from "react-router-dom";
import { useIncidentId, usePoll } from "../hooks";
import { IncidentPicker, PageHeader, Empty } from "../components/ui";
import { ImpactView } from "../components/IncidentViews";

export default function ServiceImpact() {
  const [id, setId, list] = useIncidentId();
  const { data: inc } = usePoll<any>(id ? `/api/incidents/${id}` : null, 5000);
  return (
    <div>
      <PageHeader title="Service Impact" sub="Unavailable versus degraded services, redundancy status and scope. Customer counts are shown only where source data exists."
        right={<div className="flex gap-2 items-center"><IncidentPicker id={id} setId={setId} list={list} />{id && <Link className="btn" to={`/incidents/${id}`}>Open incident</Link>}</div>} />
      {!id ? <Empty>No incidents yet. Run a scenario from the dashboard.</Empty> : inc ? <ImpactView inc={inc} /> : <Empty>Loading...</Empty>}
    </div>
  );
}
