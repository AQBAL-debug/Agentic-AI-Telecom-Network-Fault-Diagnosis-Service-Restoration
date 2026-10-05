// pages/RCA.tsx - Root Cause Analysis page: pick an incident and see the matching agent output
// (same component as the incident detail tab: components/IncidentViews.tsx -> RCAView).
import { Link } from "react-router-dom";
import { useIncidentId, usePoll } from "../hooks";
import { IncidentPicker, PageHeader, Empty } from "../components/ui";
import { RCAView } from "../components/IncidentViews";

export default function RCA() {
  const [id, setId, list] = useIncidentId();
  const { data: inc } = usePoll<any>(id ? `/api/incidents/${id}` : null, 5000);
  return (
    <div>
      <PageHeader title="Root Cause Analysis" sub="Evidence-based hypotheses with supporting and contradicting evidence. Every cause stays suspected until an engineer confirms it."
        right={<div className="flex gap-2 items-center"><IncidentPicker id={id} setId={setId} list={list} />{id && <Link className="btn" to={`/incidents/${id}`}>Open incident</Link>}</div>} />
      {!id ? <Empty>No incidents yet. Run a scenario from the dashboard.</Empty> : inc ? <RCAView inc={inc} /> : <Empty>Loading...</Empty>}
    </div>
  );
}
