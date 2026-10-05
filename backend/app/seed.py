"""
seed.py
-------
WHAT IT DOES:
    Creates all database tables and loads the synthetic dataset:
      topology (devices + links), services, historical incidents, change/maintenance
      history and 24 h of telemetry (timestamps shifted so the history ends "now").
    Also trains the anomaly model if it does not exist yet.
    Run:  python -m app.seed            (safe to re-run; use --reset to wipe everything)
    The API also calls reset_and_seed() from the "Reset demo" button.
"""
import json
import sys
from datetime import datetime, timedelta
import pandas as pd
from .db import Base, engine, SessionLocal
from .config import DATA_DIR
from . import models
from .engines.anomaly import MODEL_PATH, train_and_evaluate
from .services.toolbox import reset_model_cache


def seed(db):
    if db.query(models.Device).count():
        return False
    topo = json.loads((DATA_DIR / "topology.json").read_text())
    for d in topo["devices"]:
        db.add(models.Device(**d, status="up"))
    db.flush()
    for l in topo["links"]:
        db.add(models.Link(**l, status="up"))
    for s in json.loads((DATA_DIR / "services.json").read_text()):
        db.add(models.Service(**s, status="available"))
    for h in json.loads((DATA_DIR / "historical_incidents.json").read_text()):
        db.add(models.HistoricalIncident(**h))

    now = datetime.utcnow().replace(microsecond=0)
    for cid, dev, typ, hours_ago, desc, by in [
        ("CHG-2201", "AR-01", "configuration", 20, "Added SNMP community for new collector (no data-plane impact)", "j.rao"),
        ("MNT-0911", "CR-02", "maintenance", 12, "Line card firmware upgrade completed in window", "field-team-2"),
        ("CHG-2207", "AR-03", "configuration", 6, "QoS policy update on access-facing ports", "s.kumar"),
    ]:
        db.add(models.ChangeRecord(id=cid, device=dev, change_type=typ, timestamp=now - timedelta(hours=hours_ago),
                                   description=desc, performed_by=by))

    df = pd.read_csv(DATA_DIR / "telemetry_history.csv", parse_dates=["timestamp"])
    shift = now - timedelta(minutes=5) - df["timestamp"].max()
    df["timestamp"] = df["timestamp"] + shift
    df = df.drop(columns=["anomaly_kind"])
    # convert numpy / pandas types to plain Python (psycopg2 cannot adapt numpy.int64)
    records = [{"timestamp": r.timestamp.to_pydatetime(), "device": r.device, "label": int(r.label),
                **{m: float(getattr(r, m)) for m in ("latency_ms", "packet_loss_pct", "jitter_ms", "utilization_pct",
                                                      "throughput_mbps", "cpu_pct", "memory_pct", "interface_errors", "link_up")}}
               for r in df.itertuples(index=False)]
    db.bulk_insert_mappings(models.Telemetry, records)
    db.commit()
    return True


def reset_and_seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


def init():
    Base.metadata.create_all(bind=engine)
    if not MODEL_PATH.exists():
        train_and_evaluate()
        reset_model_cache()
    db = SessionLocal()
    try:
        return seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_and_seed()
        print("database reset and seeded")
    else:
        print("seeded" if init() else "already seeded")
