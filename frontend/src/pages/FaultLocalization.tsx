// pages/FaultLocalization.tsx - Fault Localization page: pick an incident and see the matching agent output
// (same component as the incident detail tab: components/IncidentViews.tsx -> FaultView).
import { Link } from "react-router-dom";
import { useIncidentId, usePoll } from "../hooks";
import { IncidentPicker, PageHeader, Empty } from "../components/ui";
import { FaultView } from "../components/IncidentViews";

export default function FaultLocalization() {
  const [id, setId, list] = useIncidentId();
  const { data: inc } = usePoll<any>(id ? `/api/incidents/${id}` : null, 5000);
  return (
    <div>
      <PageHeader title="Fault Localization" sub="Ranked fault locations from the topology agent: suspected device or link, supporting alarms, topology and telemetry evidence, confidence and alternatives."
        right={<div className="flex gap-2 items-center"><IncidentPicker id={id} setId={setId} list={list} />{id && <Link className="btn" to={`/incidents/${id}`}>Open incident</Link>}</div>} />
      {!id ? <Empty>No incidents yet. Run a scenario from the dashboard.</Empty> : inc ? <FaultView inc={inc} /> : <Empty>Loading...</Empty>}
    </div>
  );
}
