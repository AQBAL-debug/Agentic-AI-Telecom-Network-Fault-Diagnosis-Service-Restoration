"""
routers/incidents.py
--------------------
WHAT IT DOES:
    API for incidents, human-in-the-loop approval, action tracking, validation & reports
    (Requirements 4, 8, 9, 12-17, 19, 20).
      GET  /api/incidents                      incident center list
      GET  /api/incidents/{id}                 full analysis of one incident
      GET  /api/incidents/{id}/agent-logs      agent execution trace (current agent, inputs, tool calls...)
      POST /api/incidents/{id}/reanalyze       re-run the multi-agent workflow
      POST /api/incidents/{id}/correlation     engineer confirms / rejects the correlation
      POST /api/incidents/{id}/comment         engineering comments
      POST /api/incidents/{id}/escalate        escalate incident
      POST /api/incidents/{id}/validate        post-restoration validation
      POST /api/incidents/{id}/root-cause      engineer CONFIRMS the root cause (suspected -> confirmed)
      POST /api/incidents/{id}/close           close incident (only after validation passed)
      POST /api/incidents/{id}/notifications/ack  acknowledge reassessment notification
      GET  /api/incidents/{id}/report.pdf      download PDF report
      GET  /api/actions                        action tracker
      POST /api/actions/{id}/decision          approve / reject / modify (explicit approval)
      POST /api/actions/{id}/status            in_progress / completed (+ result)
"""
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, schemas
from ..report import build_report
from ..services import incident_service as svc

router = APIRouter(prefix="/api", tags=["incidents & approvals"])


def row(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def get_inc(db, iid):
    inc = db.get(models.Incident, iid)
    if not inc:
        raise HTTPException(404, "incident not found")
    return inc


@router.get("/incidents")
def list_incidents(status: str | None = None, db: Session = Depends(get_db)):
    q = select(models.Incident).order_by(models.Incident.created_at.desc())
    if status:
        q = q.where(models.Incident.status == status)
    out = []
    for i in db.scalars(q):
        n = db.query(models.Alarm).filter(models.Alarm.incident_id == i.id).count()
        top = (i.fault_localization or {}).get("primary") or {}
        out.append({"id": i.id, "title": i.title, "status": i.status, "severity": i.severity, "created_at": i.created_at,
                    "updated_at": i.updated_at, "alarm_count": n, "fault_location": top.get("location"),
                    "confidence": top.get("confidence"), "storm": (i.correlation or {}).get("storm", False),
                    "affected_services": len((i.service_impact or {}).get("affected_services", [])),
                    "revision": i.revision, "unread_notifications": sum(not x.get("acknowledged") for x in i.notifications or [])})
    return out


@router.get("/incidents/{iid}")
def incident(iid: str, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    actions = db.scalars(select(models.Action).where(models.Action.incident_id == iid).order_by(models.Action.step)).all()
    alarms = db.scalars(select(models.Alarm).where(models.Alarm.incident_id == iid).order_by(models.Alarm.timestamp)).all()
    return row(inc) | {"actions": [row(a) for a in actions],
                       "alarms": [{k: v for k, v in row(a).items() if k != "raw"} for a in alarms]}


@router.get("/incidents/{iid}/agent-logs")
def agent_logs(iid: str, run_id: str | None = None, db: Session = Depends(get_db)):
    q = select(models.AgentLog).where(models.AgentLog.incident_id == iid)
    logs = db.scalars(q.order_by(models.AgentLog.id)).all()
    runs = list(dict.fromkeys(l.run_id for l in logs))
    target = run_id or (runs[-1] if runs else None)
    return {"runs": runs, "run_id": target, "steps": [row(l) for l in logs if l.run_id == target or l.run_id.startswith("VAL")]}


@router.post("/incidents/{iid}/reanalyze")
def reanalyze(iid: str, bg: BackgroundTasks, sync: bool = False, db: Session = Depends(get_db)):
    get_inc(db, iid)
    if sync:
        svc.analyze_incident(iid, "manual reassessment")
    else:
        bg.add_task(svc.analyze_incident, iid, "manual reassessment")
    return {"ok": True}


@router.post("/incidents/{iid}/correlation")
def correlation_decision(iid: str, body: schemas.CorrelationDecisionIn, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    inc.correlation_confirmed = "confirmed" if body.decision == "confirm" else "rejected"
    inc.comments = (inc.comments or []) + [{"time": now(), "author": body.engineer, "text": f"Correlation {inc.correlation_confirmed}. {body.remarks}"}]
    inc.timeline = (inc.timeline or []) + [{"time": now(), "event": f"Engineer {body.engineer} {inc.correlation_confirmed} the alarm correlation"}]
    if body.decision != "confirm":
        inc.status = "open"
    db.commit()
    return {"ok": True}


@router.post("/incidents/{iid}/comment")
def comment(iid: str, body: schemas.CommentIn, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    inc.comments = (inc.comments or []) + [{"time": now(), "author": body.author, "text": body.text}]
    db.commit()
    return {"ok": True}


@router.post("/incidents/{iid}/escalate")
def escalate(iid: str, body: schemas.CommentIn, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    inc.status = "escalated"
    inc.timeline = (inc.timeline or []) + [{"time": now(), "event": f"Escalated by {body.author}: {body.text}"}]
    db.commit()
    return {"ok": True}


@router.post("/incidents/{iid}/validate")
def validate(iid: str, db: Session = Depends(get_db)):
    get_inc(db, iid)
    return svc.validate_incident(db, iid)


@router.post("/incidents/{iid}/root-cause")
def confirm_root_cause(iid: str, body: schemas.RootCauseIn, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    inc.confirmed_root_cause = f"{body.root_cause} (confirmed by {body.engineer} at {now()})"
    inc.timeline = (inc.timeline or []) + [{"time": now(), "event": f"Root cause CONFIRMED by {body.engineer}: {body.root_cause}"}]
    db.commit()
    return {"ok": True}


@router.post("/incidents/{iid}/close")
def close(iid: str, body: schemas.CommentIn, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    if not (inc.validation or {}).get("passed"):
        raise HTTPException(400, "Incident can only be closed after post-restoration validation has passed - escalate instead")
    inc.status = "closed"
    inc.timeline = (inc.timeline or []) + [{"time": now(), "event": f"Incident closed by {body.author}: {body.text}"}]
    db.commit()
    return {"ok": True}


@router.post("/incidents/{iid}/notifications/ack")
def ack(iid: str, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    inc.notifications = [n | {"acknowledged": True} for n in inc.notifications or []]
    db.commit()
    return {"ok": True}


@router.get("/incidents/{iid}/report.pdf")
def report(iid: str, db: Session = Depends(get_db)):
    inc = get_inc(db, iid)
    alarms = db.scalars(select(models.Alarm).where(models.Alarm.incident_id == iid).order_by(models.Alarm.timestamp)).all()
    actions = db.scalars(select(models.Action).where(models.Action.incident_id == iid).order_by(models.Action.step)).all()
    pdf = build_report(inc, alarms, actions)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{iid}-report.pdf"'})


# ---------------------------------------------------------------- actions
@router.get("/actions")
def actions(status: str | None = None, db: Session = Depends(get_db)):
    q = select(models.Action).order_by(models.Action.incident_id.desc(), models.Action.step)
    if status:
        q = q.where(models.Action.status == status)
    return [row(a) for a in db.scalars(q)]


@router.post("/actions/{aid}/decision")
def decision(aid: str, body: schemas.DecisionIn, db: Session = Depends(get_db)):
    a = db.get(models.Action, aid)
    if not a:
        raise HTTPException(404)
    inc = db.get(models.Incident, a.incident_id)
    if body.decision == "approve":
        a.status, a.approved_by = "approved", body.engineer
    elif body.decision == "reject":
        a.status, a.approved_by = "rejected", body.engineer
    elif body.decision == "modify":
        if body.new_description:
            a.description = body.new_description
            from ..agents.restoration_agent import classify
            a.category = classify(a.description, a.category)            # safety: re-classify edited text
            a.requires_approval = a.category in ("potentially_disruptive", "escalation")
        if body.assigned_to:
            a.assigned_to = body.assigned_to
    a.remarks = (a.remarks + " | " if a.remarks else "") + f"{body.decision} by {body.engineer}: {body.remarks}".strip()
    inc.timeline = (inc.timeline or []) + [{"time": now(), "event": f"Action {a.step} '{a.description[:50]}' {body.decision}d by {body.engineer}"}]
    if body.decision == "approve" and inc.status == "awaiting_approval":
        inc.status = "restoring"
    db.add(models.AgentLog(incident_id=a.incident_id, run_id="HUMAN", agent="NOC Engineer", step_type="human",
                           content={"action": a.id, "decision": body.decision, "by": body.engineer, "remarks": body.remarks}))
    db.commit()
    return row(a)


@router.post("/actions/{aid}/status")
def action_status(aid: str, body: schemas.StatusIn, db: Session = Depends(get_db)):
    a = db.get(models.Action, aid)
    if not a:
        raise HTTPException(404)
    if a.requires_approval and a.status not in ("approved", "in_progress"):
        raise HTTPException(400, "This action is potentially disruptive / escalation and needs explicit approval first")
    if a.status == "rejected":
        raise HTTPException(400, "Rejected actions cannot be executed")
    if body.status == "in_progress":
        a.status, a.started_at = "in_progress", datetime.utcnow()
    elif body.status == "completed":
        a.status, a.completed_at = "completed", datetime.utcnow()
        a.started_at = a.started_at or a.completed_at
    a.result = body.result or a.result
    a.remarks = (a.remarks + " | " if a.remarks else "") + body.remarks if body.remarks else a.remarks
    db.commit()
    return row(a)
