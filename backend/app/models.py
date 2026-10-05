"""
models.py
---------
WHAT IT DOES:
    Defines every database table (SQLAlchemy ORM). This IS the database design.

    devices              -> network inventory (routers, switches, base stations ...)
    links                -> physical/logical connections between devices (topology edges)
    services             -> customer / network services and which devices they depend on
    alarms               -> every raw alarm ever received (never deleted = audit trail)
    telemetry            -> time-series performance metrics per device
    incidents            -> correlated groups of alarms + all agent analysis results
    actions              -> restoration actions + approval / tracking status
    agent_logs           -> step-by-step trace of every agent run (agent visibility page)
    historical_incidents -> past resolved incidents used for similarity retrieval
"""
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # e.g. AR-01
    name: Mapped[str] = mapped_column(String(120))
    device_type: Mapped[str] = mapped_column(String(40))                   # core_router / aggregation_router / switch / base_station / enterprise_gw
    layer: Mapped[int] = mapped_column(Integer, default=0)                  # 0=core,1=aggregation,2=access/edge (for drawing)
    region: Mapped[str] = mapped_column(String(60))
    ip_address: Mapped[str] = mapped_column(String(40))
    vendor: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="up")           # up / down / degraded
    interfaces: Mapped[list] = mapped_column(JSON, default=list)            # ["GE-0/0/1", ...]
    services: Mapped[list] = mapped_column(JSON, default=list)              # service ids hosted here


class Link(Base):
    __tablename__ = "links"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # e.g. L-CR01-AR01
    source: Mapped[str] = mapped_column(ForeignKey("devices.id"))           # upstream device
    target: Mapped[str] = mapped_column(ForeignKey("devices.id"))           # downstream device
    source_interface: Mapped[str] = mapped_column(String(40), default="")
    target_interface: Mapped[str] = mapped_column(String(40), default="")
    link_type: Mapped[str] = mapped_column(String(30), default="fiber")     # fiber / microwave / copper
    capacity_mbps: Mapped[int] = mapped_column(Integer, default=10000)
    status: Mapped[str] = mapped_column(String(20), default="up")
    is_backup: Mapped[bool] = mapped_column(Boolean, default=False)         # redundant path?


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # e.g. SVC-BS-101 / E-101
    name: Mapped[str] = mapped_column(String(120))
    service_type: Mapped[str] = mapped_column(String(40))                   # mobile_access / enterprise_link / core_transport
    region: Mapped[str] = mapped_column(String(60))
    depends_on: Mapped[list] = mapped_column(JSON, default=list)            # device ids this service needs
    customers: Mapped[int | None] = mapped_column(Integer, nullable=True)   # None = unknown (never invented)
    status: Mapped[str] = mapped_column(String(20), default="available")


class Alarm(Base):
    __tablename__ = "alarms"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # EVT-xxxxx
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    device: Mapped[str] = mapped_column(String(40), index=True)
    device_type: Mapped[str] = mapped_column(String(40), default="")
    alarm_type: Mapped[str] = mapped_column(String(60))                     # normalized: interface_down, backhaul_lost ...
    severity: Mapped[str] = mapped_column(String(20))                       # critical / major / minor / warning
    interface: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")       # active / cleared
    source_format: Mapped[str] = mapped_column(String(20), default="json")  # snmp / syslog / json (before normalization)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)                   # original vendor payload (audit)
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="unassigned")     # primary / consequential / duplicate / independent
    duplicate_of: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Telemetry(Base):
    __tablename__ = "telemetry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    device: Mapped[str] = mapped_column(String(40), index=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    packet_loss_pct: Mapped[float] = mapped_column(Float)
    jitter_ms: Mapped[float] = mapped_column(Float)
    throughput_mbps: Mapped[float] = mapped_column(Float)
    utilization_pct: Mapped[float] = mapped_column(Float)
    cpu_pct: Mapped[float] = mapped_column(Float)
    memory_pct: Mapped[float] = mapped_column(Float)
    interface_errors: Mapped[float] = mapped_column(Float)
    link_up: Mapped[float] = mapped_column(Float, default=1.0)               # 1 = available, 0 = down
    label: Mapped[int] = mapped_column(Integer, default=0)                   # ground truth 1=anomaly (synthetic, for evaluation)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # INC-NET-101
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(30), default="open")         # open / analyzing / awaiting_approval / restoring / resolved / escalated / closed
    severity: Mapped[str] = mapped_column(String(20), default="major")
    primary_alarm_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correlation_confirmed: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed / rejected
    # every agent writes its result into one of these JSON columns
    correlation: Mapped[dict] = mapped_column(JSON, default=dict)
    fault_localization: Mapped[dict] = mapped_column(JSON, default=dict)
    performance: Mapped[dict] = mapped_column(JSON, default=dict)
    service_impact: Mapped[dict] = mapped_column(JSON, default=dict)
    rca: Mapped[dict] = mapped_column(JSON, default=dict)
    historical: Mapped[list] = mapped_column(JSON, default=list)
    knowledge: Mapped[list] = mapped_column(JSON, default=list)
    restoration_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    review: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[list] = mapped_column(JSON, default=list)               # engineer comments
    timeline: Mapped[list] = mapped_column(JSON, default=list)               # [{time, event}]
    notifications: Mapped[list] = mapped_column(JSON, default=list)          # material changes (dynamic reassessment)
    revision: Mapped[int] = mapped_column(Integer, default=1)                # increments on each reassessment


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # ACT-xxxx
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    step: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))                       # diagnostic / non_disruptive / potentially_disruptive / escalation
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    procedure_ref: Mapped[str] = mapped_column(String(120), default="")
    assigned_to: Mapped[str] = mapped_column(String(80), default="NOC Tier-1")
    status: Mapped[str] = mapped_column(String(20), default="proposed")     # proposed / approved / rejected / in_progress / completed / verified
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    remarks: Mapped[str] = mapped_column(Text, default="")


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    agent: Mapped[str] = mapped_column(String(60))
    step_type: Mapped[str] = mapped_column(String(30))                      # input / tool_call / llm / output / review / human
    content: Mapped[dict] = mapped_column(JSON, default=dict)


class HistoricalIncident(Base):
    __tablename__ = "historical_incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # INC-NET-032
    date: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    device_type: Mapped[str] = mapped_column(String(40))
    alarm_pattern: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    root_cause_category: Mapped[str] = mapped_column(String(60))
    resolution: Mapped[str] = mapped_column(Text)
    downstream_impact: Mapped[int] = mapped_column(Integer, default=0)
    mttr_minutes: Mapped[int] = mapped_column(Integer, default=0)


class ChangeRecord(Base):
    """Configuration-change and maintenance history (used by the RCA agent)."""
    __tablename__ = "changes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)          # CHG-xxxx / MNT-xxxx
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    device: Mapped[str] = mapped_column(String(40), index=True)
    change_type: Mapped[str] = mapped_column(String(20))                    # configuration / maintenance
    description: Mapped[str] = mapped_column(Text)
    performed_by: Mapped[str] = mapped_column(String(80), default="")
