// pages/Restoration.tsx - Restoration Planning page: pick an incident and see the matching agent output
// (same component as the incident detail tab: components/IncidentViews.tsx -> PlanView).
import { Link } from "react-router-dom";
import { useIncidentId, usePoll } from "../hooks";
import { IncidentPicker, PageHeader, Empty } from "../components/ui";
import { PlanView } from "../components/IncidentViews";

export default function Restoration() {
  const [id, setId, list] = useIncidentId();
  const { data: inc } = usePoll<any>(id ? `/api/incidents/${id}` : null, 5000);
  return (
    <div>
      <PageHeader title="Restoration Planning" sub="Actions ordered from read-only diagnostics to escalation, each tied to an approved procedure. Disruptive steps need explicit approval."
        right={<div className="flex gap-2 items-center"><IncidentPicker id={id} setId={setId} list={list} />{id && <Link className="btn" to={`/incidents/${id}`}>Open incident</Link>}</div>} />
      {!id ? <Empty>No incidents yet. Run a scenario from the dashboard.</Empty> : inc ? <PlanView inc={inc} /> : <Empty>Loading...</Empty>}
    </div>
  );
}
