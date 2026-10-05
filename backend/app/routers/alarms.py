"""
routers/alarms.py
-----------------
WHAT IT DOES:
    API for Requirement 3 (Alarm Ingestion), 5 (Alarm Storm Handling) and 6/7 (Telemetry).
      POST /api/alarms/ingest     receive raw events (json/snmp/syslog) -> event-driven pipeline:
                                  normalize -> correlate -> create/attach incident -> agents run
                                  in the BACKGROUND (?sync=true runs them inline, used by tests)
      GET  /api/alarms            alarm console (filters: status, severity, device, incident, role)
      GET  /api/alarms/clusters   alarm storm view: alarms grouped per incident/device/type
      POST /api/alarms/{id}/clear manually clear an alarm
      POST /api/telemetry/ingest  receive metrics -> anomaly model -> auto alarms
      GET  /api/telemetry/{dev}   time-series for charts (with anomaly scores)
      GET  /api/anomalies         currently anomalous devices
      GET  /api/model/metrics     anomaly model evaluation results
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, schemas
from ..engines.anomaly import METRICS_PATH
from ..services import incident_service as svc
from ..services.toolbox import anomaly_model
import pandas as pd

router = APIRouter(prefix="/api", tags=["alarms & telemetry"])


def alarm_dict(a):
    return {c.name: getattr(a, c.name) for c in a.__table__.columns if c.name != "raw"} | \
           {"validation_issues": (a.raw or {}).get("validation_issues", [])}


def schedule(bg: BackgroundTasks, res: dict, sync: bool):
    created, reassess = res.get("incidents_created", []), res.get("incidents_reassessed", [])
    if sync:
        svc.analyze_many(created, reassess)
    elif created or reassess:
        bg.add_task(svc.analyze_many, created, reassess)


@router.post("/alarms/ingest")
def ingest(body: schemas.EventsIn, bg: BackgroundTasks, sync: bool = False, db: Session = Depends(get_db)):
    res = svc.ingest_events(db, body.events)
    schedule(bg, res, sync)
    return res


@router.get("/alarms")
def list_alarms(status: str | None = None, severity: str | None = None, device: str | None = None,
                incident_id: str | None = None, role: str | None = None, limit: int = 500, db: Session = Depends(get_db)):
    q = select(models.Alarm)
    for col, val in [(models.Alarm.status, status), (models.Alarm.severity, severity), (models.Alarm.device, device),
                     (models.Alarm.incident_id, incident_id), (models.Alarm.role, role)]:
        if val:
            q = q.where(col == val)
    return [alarm_dict(a) for a in db.scalars(q.order_by(models.Alarm.timestamp.desc()).limit(limit))]


@router.get("/alarms/{alarm_id}/raw")
def alarm_raw(alarm_id: str, db: Session = Depends(get_db)):
    a = db.get(models.Alarm, alarm_id)
    if not a:
        raise HTTPException(404)
    return {"normalized": alarm_dict(a), "raw": a.raw}


@router.get("/alarms/clusters")
def clusters(db: Session = Depends(get_db)):
    """Alarm-storm friendly view: one row per incident with counts instead of a flat list."""
    groups = defaultdict(list)
    for a in db.scalars(select(models.Alarm).where(models.Alarm.status == "active")):
        groups[a.incident_id or "uncorrelated"].append(a)
    out = []
    for inc_id, al in groups.items():
        primary = next((a for a in al if a.role == "primary"), None)
        out.append({"incident_id": inc_id, "total": len(al),
                    "unique": sum(a.role != "duplicate" for a in al), "duplicates": sum(a.role == "duplicate" for a in al),
                    "primary": f"{primary.device} {primary.alarm_type}" if primary else None,
                    "by_device": dict(Counter(a.device for a in al).most_common()),
                    "by_type": dict(Counter(a.alarm_type for a in al).most_common()),
                    "storm": len(al) >= 50,
                    "first": min(a.timestamp for a in al), "last": max(a.timestamp for a in al)})
    return sorted(out, key=lambda x: -x["total"])


@router.post("/alarms/{alarm_id}/clear")
def clear_alarm(alarm_id: str, db: Session = Depends(get_db)):
    a = db.get(models.Alarm, alarm_id)
    if not a:
        raise HTTPException(404)
    a.status = "cleared"
    db.commit()
    return {"ok": True}


@router.post("/telemetry/ingest")
def telemetry_ingest(body: schemas.TelemetryIn, bg: BackgroundTasks, sync: bool = False, db: Session = Depends(get_db)):
    res = svc.ingest_telemetry(db, body.points)
    schedule(bg, res, sync)
    return res


@router.get("/telemetry/{device}")
def telemetry(device: str, minutes: int = 360, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    rows = db.scalars(select(models.Telemetry).where(models.Telemetry.device == device, models.Telemetry.timestamp >= since)
                      .order_by(models.Telemetry.timestamp)).all()
    if not rows:
        return []
    cols = ["timestamp", "device", "latency_ms", "packet_loss_pct", "jitter_ms", "throughput_mbps", "utilization_pct",
            "cpu_pct", "memory_pct", "interface_errors", "link_up"]
    df = pd.DataFrame([{c: getattr(r, c) for c in cols} for r in rows])
    s = anomaly_model().score(df)
    s["timestamp"] = s["timestamp"].astype(str)
    s["top_metrics"] = s["top_metrics"].apply(lambda x: [list(t) for t in x])
    keep = cols + ["anomaly", "anomaly_score", "pattern", "top_metrics"]
    return json.loads(s[keep].to_json(orient="records"))


@router.get("/anomalies")
def anomalies(minutes: int = 30, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    rows = db.scalars(select(models.Telemetry).where(models.Telemetry.timestamp >= since)).all()
    if not rows:
        return []
    cols = ["timestamp", "device", "latency_ms", "packet_loss_pct", "jitter_ms", "throughput_mbps", "utilization_pct",
            "cpu_pct", "memory_pct", "interface_errors", "link_up"]
    s = anomaly_model().score(pd.DataFrame([{c: getattr(r, c) for c in cols} for r in rows]))
    out = []
    for dev, g in s[s.anomaly].groupby("device"):
        w = g.sort_values("anomaly_score").iloc[-1]
        out.append({"device": dev, "points": int(len(g)), "score": float(w.anomaly_score), "pattern": w.pattern,
                    "top_metrics": [list(t) for t in w.top_metrics], "last_seen": str(g.timestamp.max())})
    return sorted(out, key=lambda x: -x["score"])


@router.get("/model/metrics")
def model_metrics():
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
