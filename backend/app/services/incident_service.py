"""
services/incident_service.py
----------------------------
WHAT IT DOES:
    The EVENT-DRIVEN WORKFLOW engine (business logic behind the API).

    ingest_events(raw_events)
        -> normalize + validate every event (Intake) -> store raw alarms (audit)
        -> clear alarms on "interface_up" events
        -> correlate all unassigned recent alarms into groups
        -> each group either JOINS an active related incident (=> DYNAMIC REASSESSMENT)
           or CREATES a new incident
        -> returns the incident ids that must be (re)analyzed by the agents

    analyze_incident(id)  -> runs the LangGraph multi-agent workflow, saves every result,
                             creates restoration actions, detects MATERIAL CHANGES vs the
                             previous revision and notifies the engineer.
    ingest_telemetry(points) -> stores metrics, scores them with the anomaly model and
                             raises "performance_anomaly" alarms automatically
                             (the ML model is part of the operational workflow).
    validate_incident(id) -> post-restoration validation, then resolve or escalate.
"""
import uuid
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import select
from .. import models
from ..config import settings
from ..db import SessionLocal
from ..engines.normalizer import normalize
from ..engines.correlation import correlate
from ..engines.topology import Topology
from ..agents.graph import run_workflow
from ..agents.restoration_agent import verify_restoration
from .toolbox import Toolbox, Tracer, anomaly_model

ACTIVE = ("open", "analyzing", "awaiting_approval", "restoring")


def _alarm_dict(a: models.Alarm) -> dict:
    return {"id": a.id, "timestamp": a.timestamp, "device": a.device, "device_type": a.device_type,
            "alarm_type": a.alarm_type, "severity": a.severity, "interface": a.interface,
            "description": a.description, "source_format": a.source_format, "status": a.status,
            "issues": (a.raw or {}).get("validation_issues", []), "role": "unassigned"}


def _next_incident_id(db) -> str:
    n = db.query(models.Incident).count()
    return f"INC-NET-{101 + n}"


def _topology(db) -> Topology:
    return Topology(list(db.scalars(select(models.Device))), list(db.scalars(select(models.Link))))


# ------------------------------------------------------------------ ingestion
def ingest_events(db, raw_events: list) -> dict:
    known = {d.id: d.device_type for d in db.scalars(select(models.Device))}
    stored, issues, cleared = [], [], 0
    for raw in raw_events:
        n = normalize(raw, known)
        if n["issues"]:
            issues.append({"event": n["id"], "issues": n["issues"]})
        if n["alarm_type"] == "interface_up":                       # clear matching active alarms
            for a in db.scalars(select(models.Alarm).where(models.Alarm.device == n["device"],
                                                           models.Alarm.status == "active")):
                if not n["interface"] or a.interface == n["interface"]:
                    a.status = "cleared"
                    cleared += 1
            continue
        if db.get(models.Alarm, n["id"]):
            n["id"] = f"{n['id']}-{uuid.uuid4().hex[:4]}"
        n.pop("issues")
        db.add(models.Alarm(**n))
        stored.append(n["id"])
    db.flush()

    topo = _topology(db)
    horizon = datetime.utcnow() - timedelta(hours=6)
    pending = list(db.scalars(select(models.Alarm).where(models.Alarm.incident_id.is_(None),
                                                         models.Alarm.status == "active",
                                                         models.Alarm.timestamp >= horizon)))
    pending += [a for a in db.scalars(select(models.Alarm).where(models.Alarm.id.in_(stored))) if a not in pending]
    to_analyze, created, reassess = [], [], []
    if pending:
        groups = correlate([_alarm_dict(a) for a in pending], topo)
        active = list(db.scalars(select(models.Incident).where(models.Incident.status.in_(ACTIVE))))
        by_id = {a.id: a for a in pending}
        for g in groups:
            target = None
            for inc in active:
                if (g["first_time"] - (inc.updated_at or inc.created_at)).total_seconds() > 1800:
                    continue                       # only join incidents active in the last 30 min
                inc_devs = set((inc.correlation or {}).get("devices", []))
                inc_devs |= {a.device for a in db.scalars(select(models.Alarm).where(models.Alarm.incident_id == inc.id))}
                if any(topo.related(d, x) for d in g["devices"] for x in inc_devs):
                    target = inc
                    break
            if target:
                for aid in g["alarm_ids"]:
                    by_id[aid].incident_id = target.id
                target.timeline = (target.timeline or []) + [{"time": datetime.utcnow().isoformat(timespec="seconds"),
                                                              "event": f"New alarm(s) joined incident: {', '.join(g['devices'])} -> dynamic reassessment"}]
                reassess.append(target.id)
            else:
                inc = models.Incident(id=_next_incident_id(db), status="open", severity=g["severity"],
                                      title=f"{g['primary_device']} {g['primary_type'].replace('_', ' ')}"
                                            + (f" + {len(g['devices']) - 1} related device(s)" if len(g["devices"]) > 1 else ""),
                                      primary_alarm_id=g["primary_id"], created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                                      timeline=[{"time": g["first_time"].isoformat(), "event": "First alarm received"},
                                                {"time": datetime.utcnow().isoformat(timespec="seconds"), "event": "Incident created by correlation engine"}])
                db.add(inc)
                db.flush()
                for aid in g["alarm_ids"]:
                    by_id[aid].incident_id = inc.id
                active.append(inc)
                created.append(inc.id)
        to_analyze = list(dict.fromkeys(created + reassess))
    db.commit()
    return {"stored": len(stored), "cleared": cleared, "validation_issues": issues,
            "incidents_created": created, "incidents_reassessed": list(dict.fromkeys(reassess)), "to_analyze": to_analyze}


# ------------------------------------------------------------------ telemetry
def ingest_telemetry(db, points: list, raise_alarms: bool = True) -> dict:
    rows = []
    for p in points:
        ts = p["timestamp"] if isinstance(p["timestamp"], datetime) else datetime.fromisoformat(str(p["timestamp"]))
        r = models.Telemetry(timestamp=ts, device=p["device"], latency_ms=p["latency_ms"], packet_loss_pct=p["packet_loss_pct"],
                             jitter_ms=p["jitter_ms"], throughput_mbps=p.get("throughput_mbps", 0), utilization_pct=p["utilization_pct"],
                             cpu_pct=p["cpu_pct"], memory_pct=p["memory_pct"], interface_errors=p.get("interface_errors", 0),
                             link_up=p.get("link_up", 1.0), label=p.get("label", 0))
        db.add(r)
        rows.append(p | {"timestamp": ts})
    db.commit()
    events = []
    if raise_alarms and rows:
        scored = anomaly_model().score(pd.DataFrame(rows))
        for dev, g in scored[scored.anomaly].groupby("device"):
            w = g.sort_values("anomaly_score").iloc[-1]
            if w.pattern in ("link_down",):
                continue                                    # link-down already reported by device alarms
            events.append({"format": "json", "device": dev, "alarm": "performance_anomaly", "severity": "major",
                           "timestamp": w.timestamp.isoformat(),
                           "description": f"Anomaly model: {w.pattern} score={w.anomaly_score} metrics={w.top_metrics}"})
    result = {"stored": len(rows), "anomaly_alarms": len(events)}
    if events:
        result.update(ingest_events(db, events))
    return result


# ------------------------------------------------------------------ analysis
def analyze_incident(incident_id: str, reason: str = "initial") -> dict:
    db = SessionLocal()
    try:
        inc = db.get(models.Incident, incident_id)
        if not inc:
            return {}
        prev = {"fault": ((inc.fault_localization or {}).get("primary") or {}).get("location"),
                "impact": len((inc.service_impact or {}).get("affected_services", [])),
                "top_rca": (inc.rca or {}).get("top_suspected"), "revision": inc.revision}
        inc.status = "analyzing"
        db.commit()
        alarms = [_alarm_dict(a) for a in db.scalars(select(models.Alarm).where(models.Alarm.incident_id == incident_id)
                                                     .order_by(models.Alarm.timestamp))]
        if not alarms:
            inc.status = "open"
            db.commit()
            return {}
        run_id = f"RUN-{uuid.uuid4().hex[:6]}"
        tools = Toolbox(db, Tracer(db, incident_id, run_id))
        final = run_workflow(tools, incident_id, run_id, alarms)

        # persist alarm roles
        roles = {a["id"]: (a.get("role"), a.get("duplicate_of")) for a in final["alarms"]}
        for a in db.scalars(select(models.Alarm).where(models.Alarm.incident_id == incident_id)):
            if a.id in roles:
                a.role, a.duplicate_of = roles[a.id][0] or "consequential", roles[a.id][1]
        # persist service status
        down = {s["service_id"]: s["status"] for s in final["service_impact"].get("affected_services", [])}
        for s in tools.services:
            if s.id in down:
                s.status = down[s.id]

        inc.correlation = _clean(final["correlation"])
        inc.performance = _clean(final["performance"])
        inc.fault_localization = _clean(final["fault_localization"])
        inc.service_impact = _clean(final["service_impact"])
        inc.rca = _clean(final["rca"])
        inc.historical = _clean(final.get("historical", []))
        inc.knowledge = _clean(final.get("knowledge", []))
        inc.restoration_plan = _clean(final["restoration_plan"])
        inc.review = _clean(final["review"] | {"messages": final.get("messages", [])})
        inc.severity = "critical" if any(a["severity"] == "critical" for a in alarms) else "major"
        top = (final["fault_localization"].get("primary") or {})
        inc.title = f"Suspected: {final['rca']['top_suspected']}"[:200]

        # actions: keep approved/in-progress ones, replace only still-proposed ones
        existing = list(db.scalars(select(models.Action).where(models.Action.incident_id == incident_id)))
        kept = {a.description for a in existing if a.status != "proposed"}
        for a in existing:
            if a.status == "proposed":
                db.delete(a)
        for a in final["restoration_plan"]["actions"]:
            if a["description"] in kept:
                continue
            db.add(models.Action(id=f"ACT-{uuid.uuid4().hex[:6].upper()}", incident_id=incident_id, step=a["step"],
                                 description=a["description"], category=a["category"], requires_approval=a["requires_approval"],
                                 procedure_ref=a["procedure_ref"], assigned_to=a["assigned_to"], status="proposed"))

        now = datetime.utcnow().isoformat(timespec="seconds")
        if reason != "initial":
            inc.revision = (inc.revision or 1) + 1
            changes = []
            if prev["fault"] != top.get("location"):
                changes.append(f"Fault location changed: {prev['fault']} -> {top.get('location')}")
            if prev["impact"] != len(final["service_impact"].get("affected_services", [])):
                changes.append(f"Affected services changed: {prev['impact']} -> {len(final['service_impact'].get('affected_services', []))}")
            if prev["top_rca"] != final["rca"]["top_suspected"]:
                changes.append(f"Top root-cause hypothesis changed: {prev['top_rca']} -> {final['rca']['top_suspected']}")
            inc.notifications = (inc.notifications or []) + [{"time": now, "revision": inc.revision, "reason": reason,
                                                              "material_changes": changes or ["No material change - analysis confirmed"],
                                                              "material": bool(changes), "acknowledged": False}]
        inc.timeline = (inc.timeline or []) + (final.get("timeline", []) if reason == "initial" else []) + \
                       [{"time": now, "event": f"Multi-agent analysis completed (rev {inc.revision}, {reason}); awaiting engineer approval"}]
        inc.status = "awaiting_approval"
        inc.updated_at = datetime.utcnow()
        db.commit()
        return {"incident": incident_id, "run_id": run_id}
    except Exception as e:
        db.rollback()
        inc = db.get(models.Incident, incident_id)
        if inc:
            inc.status = "open"
            inc.timeline = (inc.timeline or []) + [{"time": datetime.utcnow().isoformat(timespec="seconds"), "event": f"Analysis error: {e}"}]
            db.commit()
        raise
    finally:
        db.close()


def analyze_many(created: list, reassess: list):
    """Background task entry point."""
    for i in created:
        analyze_incident(i, "initial")
    for i in reassess:
        if i not in created:
            analyze_incident(i, "new alarm during active incident")


def validate_incident(db, incident_id: str, restored_at: datetime | None = None) -> dict:
    inc = db.get(models.Incident, incident_id)
    tools = Toolbox(db, Tracer(db, incident_id, f"VAL-{uuid.uuid4().hex[:5]}"))
    active = list(db.scalars(select(models.Alarm).where(models.Alarm.incident_id == incident_id, models.Alarm.status == "active")))
    result = verify_restoration(tools, inc, active, restored_at)
    tools.tracer.log("7-Restoration", "output", {"post_restoration_validation": result["summary"], "passed": result["passed"]})
    inc.validation = _clean(result)
    now = datetime.utcnow().isoformat(timespec="seconds")
    if result["passed"]:
        inc.status = "resolved"
        for a in db.scalars(select(models.Action).where(models.Action.incident_id == incident_id, models.Action.status == "completed")):
            a.status = "verified"
    else:
        inc.status = "escalated"
    inc.timeline = (inc.timeline or []) + [{"time": now, "event": f"Post-restoration validation: {result['summary']}"}]
    db.commit()
    return result


def _clean(v):
    """Convert datetimes / numpy types to JSON-safe values."""
    import numpy as np
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x) for x in v]
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v
