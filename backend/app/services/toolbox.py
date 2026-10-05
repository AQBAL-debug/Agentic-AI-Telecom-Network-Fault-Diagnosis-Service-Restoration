"""
services/toolbox.py
-------------------
WHAT IT DOES:
    The set of TOOLS the agents are allowed to call (tool calling), bundled in one object.
    Each tool is a plain Python function that queries the database or an engine:
      get_topology, get_telemetry, score_anomalies, search_procedures (RAG),
      similar_incidents, get_changes, get_device_logs, get_services ...
    Heavy objects (knowledge base, anomaly model) are loaded once and cached.
    A Tracer records every agent step (input / tool call / LLM call / output) into the
    agent_logs table - this powers the "Agent Execution" visibility page.
"""
from datetime import datetime, timedelta
from functools import lru_cache
import pandas as pd
from sqlalchemy import select
from .. import models
from ..engines.topology import Topology
from ..engines.rag import KnowledgeBase, HistoricalIndex
from ..engines.anomaly import AnomalyModel


@lru_cache(maxsize=1)
def knowledge_base() -> KnowledgeBase:
    return KnowledgeBase()


_model_cache = {}


def anomaly_model() -> AnomalyModel:
    if "m" not in _model_cache:
        _model_cache["m"] = AnomalyModel.load()
    return _model_cache["m"]


def reset_model_cache():
    _model_cache.clear()


def _jsonable(v, depth=0):
    """Make tool outputs safe to store as JSON (datetimes, sets, long lists)."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (set, tuple)):
        v = list(v)
    if isinstance(v, list):
        return [_jsonable(x, depth + 1) for x in v[:40]]
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, float):
        return round(v, 3)
    if v is None or isinstance(v, (str, int, bool)):
        return v
    if hasattr(v, "item"):                       # numpy scalar
        return v.item()
    return f"<{type(v).__name__}>"               # topology objects, dataframes ...


class Tracer:
    def __init__(self, db, incident_id: str, run_id: str):
        self.db, self.incident_id, self.run_id = db, incident_id, run_id

    def log(self, agent: str, step_type: str, content: dict):
        self.db.add(models.AgentLog(incident_id=self.incident_id, run_id=self.run_id, agent=agent,
                                    step_type=step_type, content=_jsonable(content), timestamp=datetime.utcnow()))
        self.db.flush()


class Toolbox:
    def __init__(self, db, tracer: Tracer):
        self.db, self.tracer = db, tracer
        self.devices = {d.id: d for d in db.scalars(select(models.Device))}
        self.links = list(db.scalars(select(models.Link)))
        self.services = list(db.scalars(select(models.Service)))
        self.topology = Topology(list(self.devices.values()), self.links)
        self.kb = knowledge_base()
        self.history = HistoricalIndex(list(db.scalars(select(models.HistoricalIncident))))
        self.model = anomaly_model()

    # ---------- tool wrapper: every call is traced ----------
    def call(self, agent: str, tool: str, fn, summary=None, **kwargs):
        result = fn(**kwargs)
        self.tracer.log(agent, "tool_call", {"tool": tool, "args": kwargs,
                                             "result": summary(result) if summary else result})
        return result

    # ---------- tools ----------
    def get_telemetry(self, devices: list, start: datetime, end: datetime | None = None) -> pd.DataFrame:
        q = select(models.Telemetry).where(models.Telemetry.device.in_(devices), models.Telemetry.timestamp >= start)
        if end:
            q = q.where(models.Telemetry.timestamp <= end)
        rows = self.db.scalars(q.order_by(models.Telemetry.timestamp)).all()
        cols = ["timestamp", "device", "latency_ms", "packet_loss_pct", "jitter_ms", "throughput_mbps",
                "utilization_pct", "cpu_pct", "memory_pct", "interface_errors", "link_up"]
        return pd.DataFrame([{c: getattr(r, c) for c in cols} for r in rows], columns=cols)

    def get_changes(self, devices: list, since: datetime):
        rows = self.db.scalars(select(models.ChangeRecord).where(models.ChangeRecord.device.in_(devices),
                                                                  models.ChangeRecord.timestamp >= since)).all()
        return [{"id": r.id, "time": r.timestamp.isoformat(), "device": r.device, "type": r.change_type,
                 "description": r.description, "by": r.performed_by} for r in rows]

    def get_device_logs(self, devices: list, since: datetime):
        """Syslog-style evidence = alarms received in syslog/snmp format for these devices."""
        rows = self.db.scalars(select(models.Alarm).where(models.Alarm.device.in_(devices),
                                                          models.Alarm.timestamp >= since)
                               .order_by(models.Alarm.timestamp)).all()
        return [{"time": r.timestamp.isoformat(), "device": r.device, "format": r.source_format,
                 "message": r.description} for r in rows if r.source_format in ("syslog", "snmp")][:30]

    def search_procedures(self, query: str, k: int = 4):
        return self.kb.search(query, k=k)

    def similar_incidents(self, query: str, device_type: str, downstream_count: int):
        return self.history.similar(query, device_type, downstream_count)
