"""
routers/inventory.py
--------------------
WHAT IT DOES:
    API for Requirement 1 (Network Inventory) and 2 (Network Topology).
      GET/POST/PUT/DELETE /api/devices      manage network elements
      GET/POST/DELETE     /api/links        manage transmission links
      GET                 /api/services     services + dependencies
      GET                 /api/topology     nodes + edges (+ live status) for the interactive map
      GET                 /api/topology/node/{id}  operational details of one node
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, schemas
from ..engines.topology import Topology

router = APIRouter(prefix="/api", tags=["inventory & topology"])


def dev_dict(d):
    return {c.name: getattr(d, c.name) for c in d.__table__.columns}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    links = list(db.scalars(select(models.Link)))
    out = []
    for d in db.scalars(select(models.Device).order_by(models.Device.layer, models.Device.id)):
        x = dev_dict(d)
        x["connected_devices"] = sorted({l.source for l in links if l.target == d.id} | {l.target for l in links if l.source == d.id})
        out.append(x)
    return out


@router.post("/devices")
def create_device(body: schemas.DeviceIn, db: Session = Depends(get_db)):
    if db.get(models.Device, body.id):
        raise HTTPException(400, "device id already exists")
    data = body.model_dump(exclude={"connected_to"})
    db.add(models.Device(**data))
    db.flush()
    for up in body.connected_to:
        if db.get(models.Device, up):
            db.add(models.Link(id=f"L-{up}-{body.id}", source=up, target=body.id))
    db.commit()
    return {"ok": True, "id": body.id}


@router.put("/devices/{device_id}")
def update_device(device_id: str, body: schemas.DeviceIn, db: Session = Depends(get_db)):
    d = db.get(models.Device, device_id)
    if not d:
        raise HTTPException(404, "device not found")
    for k, v in body.model_dump(exclude={"connected_to", "id"}).items():
        setattr(d, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, db: Session = Depends(get_db)):
    d = db.get(models.Device, device_id)
    if not d:
        raise HTTPException(404, "device not found")
    for l in db.scalars(select(models.Link).where((models.Link.source == device_id) | (models.Link.target == device_id))):
        db.delete(l)
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/links")
def list_links(db: Session = Depends(get_db)):
    return [dev_dict(l) for l in db.scalars(select(models.Link))]


@router.post("/links")
def create_link(body: schemas.LinkIn, db: Session = Depends(get_db)):
    lid = f"L-{body.source}-{body.target}"
    if db.get(models.Link, lid):
        raise HTTPException(400, "link exists")
    db.add(models.Link(id=lid, **body.model_dump()))
    db.commit()
    return {"ok": True, "id": lid}


@router.delete("/links/{link_id}")
def delete_link(link_id: str, db: Session = Depends(get_db)):
    l = db.get(models.Link, link_id)
    if l:
        db.delete(l)
        db.commit()
    return {"ok": True}


@router.get("/services")
def list_services(db: Session = Depends(get_db)):
    return [dev_dict(s) for s in db.scalars(select(models.Service))]


@router.get("/topology")
def topology(db: Session = Depends(get_db)):
    devices = list(db.scalars(select(models.Device)))
    links = list(db.scalars(select(models.Link)))
    active = {}
    for a in db.scalars(select(models.Alarm).where(models.Alarm.status == "active")):
        active[a.device] = active.get(a.device, 0) + 1
    down_devs = {d.id for d in devices if d.status == "down"}
    return {
        "nodes": [{**dev_dict(d), "active_alarms": active.get(d.id, 0)} for d in devices],
        "edges": [{**dev_dict(l), "status": "down" if (l.source in down_devs or l.target in down_devs or l.status == "down") else l.status}
                  for l in links],
        "services": [{"id": s.id, "name": s.name, "depends_on": s.depends_on, "status": s.status} for s in db.scalars(select(models.Service))],
    }


@router.get("/topology/node/{device_id}")
def node_detail(device_id: str, db: Session = Depends(get_db)):
    d = db.get(models.Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    topo = Topology(list(db.scalars(select(models.Device))), list(db.scalars(select(models.Link))))
    last = db.scalars(select(models.Telemetry).where(models.Telemetry.device == device_id)
                      .order_by(models.Telemetry.timestamp.desc()).limit(1)).first()
    alarms = db.scalars(select(models.Alarm).where(models.Alarm.device == device_id)
                        .order_by(models.Alarm.timestamp.desc()).limit(10)).all()
    return {
        "device": dev_dict(d),
        "upstream": sorted(topo.upstream(device_id)), "downstream": sorted(topo.downstream(device_id)),
        "path_to_core": topo.path_to_core(device_id),
        "if_failed_isolates": sorted(topo.isolated_if_failed([device_id])),
        "services": [s.id for s in db.scalars(select(models.Service)) if device_id in s.depends_on],
        "latest_telemetry": {c: getattr(last, c) for c in ("timestamp", "latency_ms", "packet_loss_pct", "jitter_ms",
                                                            "utilization_pct", "cpu_pct", "memory_pct", "link_up")} if last else None,
        "recent_alarms": [{"id": a.id, "time": a.timestamp, "type": a.alarm_type, "severity": a.severity, "status": a.status} for a in alarms],
    }
