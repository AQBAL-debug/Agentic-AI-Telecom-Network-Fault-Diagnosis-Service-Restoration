"""
routers/operations.py
---------------------
WHAT IT DOES:
    API for the knowledge base, simulator and dashboard.
      GET  /api/kb/documents         list SOP / manual documents
      GET  /api/kb/search?q=         RAG retrieval (document, section, procedure, score)
      POST /api/kb/ask               RAG question answering: retrieve -> LLM answer with citations
      GET  /api/historical           historical incident records
      GET  /api/historical/similar   similar historical incidents for a free-text pattern
      GET  /api/simulate/scenarios   list demo scenarios
      POST /api/simulate/{scenario}  inject a scenario (alarms + telemetry) into the pipeline
      POST /api/simulate/restore/{incident_id}  simulate the fix, then run validation
      POST /api/reset                wipe and re-seed the demo database
      GET  /api/dashboard            NOC dashboard numbers (Requirement 18)
      GET  /api/agents               agent list + prompts + graph (architecture view)
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, schemas
from ..agents.prompts import ALL_PROMPTS
from ..agents.graph import AGENT_ORDER
from ..llm import chat_text, llm_available
from ..config import settings
from ..engines.rag import HistoricalIndex
from ..services import incident_service as svc, simulator
from ..services.toolbox import knowledge_base
from ..seed import reset_and_seed

router = APIRouter(prefix="/api", tags=["knowledge, simulator, dashboard"])


@router.get("/kb/documents")
def kb_documents():
    return knowledge_base().documents()


@router.get("/kb/search")
def kb_search(q: str, k: int = 5):
    return knowledge_base().search(q, k=k)


@router.post("/kb/ask")
def kb_ask(body: schemas.AskIn, db: Session = Depends(get_db)):
    query = body.question
    if body.incident_id and (inc := db.get(models.Incident, body.incident_id)):
        p = (inc.correlation or {}).get("primary", {})
        query += f" {p.get('type', '')} {(inc.rca or {}).get('top_suspected', '')}"
    hits = knowledge_base().search(query, k=4)
    context = "\n\n".join(f"[{h['reference']}]\n{h['text']}" for h in hits)
    answer, meta = chat_text(
        "You are a NOC assistant. Answer ONLY from the provided procedure excerpts. Cite references in [brackets]. "
        "If the excerpts do not contain the answer, say so. Mark disruptive steps as requiring approval.",
        f"Question: {body.question}\n\nProcedure excerpts:\n{context}")
    if not answer:
        answer = ("Retrieved procedures (LLM unavailable, showing the most relevant section):\n\n" +
                  (f"[{hits[0]['reference']}]\n{hits[0]['text']}" if hits else "No matching procedure found."))
    return {"answer": answer, "sources": hits, "llm": meta}


@router.get("/historical")
def historical(db: Session = Depends(get_db)):
    return [{c.name: getattr(h, c.name) for c in h.__table__.columns} for h in db.scalars(select(models.HistoricalIncident))]


@router.get("/historical/similar")
def historical_similar(q: str, device_type: str = "", downstream: int = 0, db: Session = Depends(get_db)):
    return HistoricalIndex(list(db.scalars(select(models.HistoricalIncident)))).similar(q, device_type, downstream, k=5)


@router.get("/simulate/scenarios")
def scenarios():
    return [{"id": k, "description": v} for k, v in simulator.SCENARIOS.items()]


@router.post("/simulate/{scenario}")
def simulate(scenario: str, bg: BackgroundTasks, sync: bool = False, db: Session = Depends(get_db)):
    if scenario not in simulator.SCENARIOS:
        raise HTTPException(404, "unknown scenario")
    events, telemetry, changes = simulator.build(db, scenario)
    for c in changes:
        db.add(c)
    db.commit()
    tel = svc.ingest_telemetry(db, telemetry, raise_alarms=(scenario == "congestion"))
    res = svc.ingest_events(db, events) if events else tel
    created = list(dict.fromkeys(res.get("incidents_created", []) + tel.get("incidents_created", [])))
    reassess = list(dict.fromkeys(res.get("incidents_reassessed", []) + tel.get("incidents_reassessed", [])))
    if sync:
        svc.analyze_many(created, reassess)
    else:
        bg.add_task(svc.analyze_many, created, reassess)
    return {"scenario": scenario, "events_sent": len(events), "telemetry_points": len(telemetry),
            "incidents_created": created, "incidents_reassessed": reassess, "validation_issues": res.get("validation_issues", [])}


@router.post("/simulate/restore/{incident_id}")
def simulate_restore(incident_id: str, db: Session = Depends(get_db)):
    inc = db.get(models.Incident, incident_id)
    if not inc:
        raise HTTPException(404)
    restored_at = datetime.utcnow()
    tel, _ = simulator.restore(db, incident_id)
    svc.ingest_telemetry(db, tel, raise_alarms=False)
    inc.timeline = (inc.timeline or []) + [{"time": datetime.utcnow().isoformat(timespec="seconds"),
                                            "event": "Restoration performed (simulated field/NOC fix) - alarms cleared"}]
    db.commit()
    return svc.validate_incident(db, incident_id, restored_at)


@router.post("/reset")
def reset():
    reset_and_seed()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    alarms = list(db.scalars(select(models.Alarm).where(models.Alarm.status == "active")))
    incidents = list(db.scalars(select(models.Incident)))
    devices = list(db.scalars(select(models.Device)))
    actions = list(db.scalars(select(models.Action)))
    active_inc = [i for i in incidents if i.status in svc.ACTIVE]
    affected = set()
    for i in active_inc:
        imp = i.service_impact or {}
        affected |= set(imp.get("unavailable_devices", [])) | set(imp.get("degraded_devices", [])) | set((i.correlation or {}).get("devices", []))
    from .alarms import anomalies
    an = anomalies(30, db)
    up = sum(d.status == "up" for d in devices)
    return {
        "active_alarms": len(alarms),
        "critical_alarms": sum(a.severity == "critical" for a in alarms),
        "correlated_incidents": len(active_inc),
        "alarm_reduction": f"{len(alarms)} alarms -> {len(active_inc)} incidents" if alarms else "no active alarms",
        "network_health_pct": round(100 * up / max(1, len(devices)), 1),
        "device_status": {s: sum(d.status == s for d in devices) for s in ("up", "degraded", "down")},
        "affected_elements": sorted(affected),
        "service_impact_incidents": sum(bool((i.service_impact or {}).get("affected_services")) for i in active_inc),
        "active_anomalies": an,
        "restoration_actions": {s: sum(a.status == s for a in actions) for s in ("proposed", "approved", "in_progress", "completed", "verified", "rejected")},
        "pending_approvals": sum(a.status == "proposed" and a.requires_approval for a in actions),
        "open_escalations": [{"id": i.id, "title": i.title} for i in incidents if i.status == "escalated"],
        "recently_resolved": [{"id": i.id, "title": i.title, "status": i.status} for i in incidents if i.status in ("resolved", "closed")][-5:],
        "incidents": [{"id": i.id, "title": i.title, "status": i.status, "severity": i.severity} for i in active_inc],
        "llm": {"enabled": llm_available(), "model": settings.OPENROUTER_MODEL},
    }


@router.get("/agents")
def agents():
    return {"order": AGENT_ORDER, "prompts": ALL_PROMPTS,
            "edges": [[a, b] for a, b in zip(AGENT_ORDER[:-1], AGENT_ORDER[1:])] + [["critic", "restoration (if needs_rework)"], ["critic", "END -> human approval"]]}
