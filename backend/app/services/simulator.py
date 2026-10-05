"""
services/simulator.py
---------------------
WHAT IT DOES:
    Simulates the network feeds (no real hardware needed). Each scenario generates
    alarms in MIXED vendor formats (SNMP traps, syslog lines, JSON events) and matching
    telemetry, then pushes them through the normal ingestion pipeline exactly like
    real feeds would. Scenarios map to the assignment's test cases:

      single_interface_down   TC-01  one device, one interface-down alarm
      ar01_uplink_failure     TC-02/05/06  the assignment example (AR-01 + BS-101/102 + E-101)
      alarm_storm             TC-03  AR-03 restart -> ~200 flapping alarms + 1 independent alarm
      congestion              TC-04  latency 180 ms, loss 8.5 %, util 96 %, jitter 42 ms (telemetry only,
                                     the anomaly model raises the alarm itself)
      config_change_ar02      extra  config commit on AR-02 followed by downstream failures
      new_alarm_during_incident TC-08  CR-01 side of the AR-01 uplink goes down while incident active
      restore(incident)       TC-07  clears alarms + normal telemetry -> validation
"""
import random
from datetime import datetime, timedelta
import numpy as np
from sqlalchemy import select
from .. import models
from ..data_gen_helpers import normal_point

SCENARIOS = {
    "single_interface_down": "TC-01: ENT-GW-201 reports a single interface-down alarm",
    "ar01_uplink_failure": "TC-02/05/06: AR-01 uplink down, BS-101, BS-102 and ENT-GW-101 lose connectivity (assignment example)",
    "alarm_storm": "TC-03: AR-03 crashes and restarts -> ~200 flapping alarms from 5 devices + 1 unrelated alarm",
    "congestion": "TC-04: AR-02 uplink congestion - latency 180 ms, loss 8.5 %, utilization 96 %, jitter 42 ms",
    "config_change_ar02": "Config commit on AR-02 followed by BS-201/BS-202 backhaul loss",
    "new_alarm_during_incident": "TC-08: CR-01 interface towards AR-01 goes down while the AR-01 incident is active",
}


def _t(base, sec):
    return (base + timedelta(seconds=sec)).isoformat(timespec="seconds")


def _telemetry(db, device, start, minutes, kind="normal", step=60):
    d = db.get(models.Device, device)
    pts = []
    for i in range(minutes * 60 // step):
        ts = start + timedelta(seconds=i * step)
        p = normal_point(d.device_type, ts.hour + ts.minute / 60)
        if kind == "down":
            p.update(link_up=0.0, utilization_pct=0.0, throughput_mbps=0.0, packet_loss_pct=100.0)
        elif kind == "congestion":
            p.update(latency_ms=random.uniform(170, 190), packet_loss_pct=random.uniform(8, 9), utilization_pct=random.uniform(95, 97),
                     jitter_ms=random.uniform(40, 44), throughput_mbps=9600)
        elif kind == "cpu":
            p.update(cpu_pct=random.uniform(93, 99), latency_ms=random.uniform(60, 100))
        pts.append({"timestamp": ts, "device": device, **p})
    return pts


def build(db, scenario: str):
    """returns (raw_events, telemetry_points, change_records)"""
    now = datetime.utcnow().replace(microsecond=0)
    ev, tel, chg = [], [], []
    pre = now - timedelta(minutes=30)

    if scenario == "single_interface_down":
        ev.append({"format": "snmp", "agent": "ENT-GW-201", "trap_oid": "1.3.6.1.6.3.1.1.5.3", "time": _t(now, 0),
                   "varbinds": {"ifName": "ge-0/0/0", "ifOperStatus": "down"}})
        tel += _telemetry(db, "ENT-GW-201", pre, 30) + _telemetry(db, "ENT-GW-201", now, 3, "down")

    elif scenario == "ar01_uplink_failure":
        ev += [
            {"format": "syslog", "timestamp": _t(now, 1), "message": "<187>AR-01 %LINK-3-UPDOWN: Interface GE-0/0/24, changed state to down"},
            {"format": "json", "device": "BS-101", "alarm": "Backhaul Connectivity Lost", "timestamp": _t(now, 4), "interface": "eth0"},
            {"format": "json", "device": "BS-102", "alarm": "Backhaul Connectivity Lost", "timestamp": _t(now, 5), "interface": "eth0"},
            {"format": "json", "device": "ENT-GW-101", "alarm": "Link Down", "timestamp": _t(now, 6), "interface": "Gi0/0/0"},
            {"format": "json", "device": "BS-101", "alarm": "Service Unavailable", "timestamp": _t(now, 7)},
            {"format": "json", "device": "BS-102", "alarm": "Service Unavailable", "timestamp": _t(now, 8)},
            {"format": "json", "device": "BS-101", "alarm": "Backhaul Connectivity Lost", "timestamp": _t(now, 20), "interface": "eth0"},  # duplicate
        ]
        for d in ("AR-01", "BS-101", "BS-102", "ENT-GW-101", "CR-01"):
            tel += _telemetry(db, d, pre, 30)
        for d in ("AR-01", "BS-101", "BS-102", "ENT-GW-101"):
            tel += _telemetry(db, d, now, 3, "down")
        tel += _telemetry(db, "CR-01", now, 3)

    elif scenario == "new_alarm_during_incident":
        ev.append({"format": "syslog", "timestamp": _t(now, 30),
                   "message": "<187>CR-01 %LINK-3-UPDOWN: Interface Te0/0/0/1, changed state to down"})
        tel += _telemetry(db, "CR-01", now, 2)

    elif scenario == "alarm_storm":
        devs = ["AR-03", "SW-301", "BS-301", "BS-302", "BS-304"]
        ev.append({"format": "snmp", "agent": "AR-03", "trap_oid": "1.3.6.1.6.3.1.1.5.1", "time": _t(now, 0), "varbinds": {}})
        ev.append({"format": "json", "device": "AR-03", "alarm": "Node Unreachable", "timestamp": _t(now, 1)})
        k = 2
        for rep in range(40):                                  # flapping -> repeated alarms
            for d in devs[1:]:
                typ = "Backhaul Connectivity Lost" if d.startswith("BS") else "Link Down"
                ev.append({"format": "json", "device": d, "alarm": typ, "timestamp": _t(now, k + rep // 2), "interface": "eth0" if d.startswith("BS") else "XGE0/0/1"})
            ev.append({"format": "syslog", "timestamp": _t(now, k + rep // 2), "message": f"<187>AR-03 %LINK-3-UPDOWN: Interface GE0/2/{rep % 2}, changed state to down"})
        for d in ("BS-301", "BS-302", "BS-304"):
            ev.append({"format": "json", "device": d, "alarm": "Service Unavailable", "timestamp": _t(now, 30)})
        ev.append({"format": "json", "device": "BS-201", "alarm": "Power Failure", "timestamp": _t(now, 15),
                   "description": "Mains failure at site 201 (unrelated)"})       # independent incident
        for d in devs:
            tel += _telemetry(db, d, pre, 30) + _telemetry(db, d, now, 3, "down")

    elif scenario == "congestion":
        tel += _telemetry(db, "AR-02", pre, 30) + _telemetry(db, "AR-02", now, 5, "congestion")
        tel += _telemetry(db, "BS-203", now - timedelta(minutes=1), 5, "congestion")

    elif scenario == "config_change_ar02":
        chg.append(models.ChangeRecord(id=f"CHG-{random.randint(3000, 3999)}", device="AR-02", change_type="configuration",
                                       timestamp=now - timedelta(minutes=8), performed_by="m.ali",
                                       description="VLAN re-numbering on access-facing ports 1/2/1-1/2/2"))
        ev += [
            {"format": "syslog", "timestamp": _t(now, 0), "message": "<187>AR-02 %LINK-3-UPDOWN: Interface 1/2/1, changed state to down"},
            {"format": "syslog", "timestamp": _t(now, 1), "message": "<187>AR-02 %LINK-3-UPDOWN: Interface 1/2/2, changed state to down"},
            {"format": "json", "device": "BS-201", "alarm": "Backhaul Lost", "timestamp": _t(now, 4)},
            {"format": "json", "device": "BS-202", "alarm": "Backhaul Lost", "timestamp": _t(now, 5)},
        ]
        for d in ("AR-02", "BS-201", "BS-202"):
            tel += _telemetry(db, d, pre, 30)
        tel += _telemetry(db, "BS-201", now, 3, "down") + _telemetry(db, "BS-202", now, 3, "down")
    else:
        raise ValueError(f"unknown scenario {scenario}")
    return ev, tel, chg


def restore(db, incident_id: str):
    """Simulates the field/NOC fix: clear the incident's alarms and send normal telemetry."""
    inc = db.get(models.Incident, incident_id)
    devices = sorted(set((inc.correlation or {}).get("devices", [])))
    now = datetime.utcnow().replace(microsecond=0)
    events = []
    # simulated 'fault' samples that lie in the future are superseded by the fix
    db.query(models.Telemetry).filter(models.Telemetry.device.in_(devices), models.Telemetry.timestamp > now).delete(synchronize_session=False)
    for a in db.scalars(select(models.Alarm).where(models.Alarm.incident_id == incident_id, models.Alarm.status == "active")):
        a.status = "cleared"
    for d in devices:
        dev = db.get(models.Device, d)
        if dev:
            dev.status = "up"
    for s in db.scalars(select(models.Service)):
        if set(s.depends_on) & set(devices):
            s.status = "available"
    tel = []
    for d in devices:
        tel += _telemetry(db, d, now + timedelta(seconds=30), 5)
    db.commit()
    return tel, events
