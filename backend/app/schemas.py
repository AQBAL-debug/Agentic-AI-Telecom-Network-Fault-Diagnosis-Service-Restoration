"""
schemas.py
----------
WHAT IT DOES:
    Pydantic models that VALIDATE the JSON bodies sent to the API
    (FastAPI shows them in the auto-generated docs at /docs).
"""
from typing import Any, Optional
from pydantic import BaseModel, Field


class DeviceIn(BaseModel):
    id: str
    name: str
    device_type: str
    layer: int = 2
    region: str = ""
    ip_address: str = ""
    vendor: str = ""
    model: str = ""
    status: str = "up"
    interfaces: list[str] = []
    services: list[str] = []
    connected_to: list[str] = Field(default=[], description="upstream device ids - links are created automatically")


class LinkIn(BaseModel):
    source: str
    target: str
    source_interface: str = ""
    target_interface: str = ""
    link_type: str = "fiber"
    capacity_mbps: int = 1000
    is_backup: bool = False


class EventsIn(BaseModel):
    events: list[dict[str, Any]] = Field(..., description="raw events in json / snmp / syslog format")


class TelemetryIn(BaseModel):
    points: list[dict[str, Any]]


class DecisionIn(BaseModel):
    decision: str = Field(..., description="approve | reject | modify")
    engineer: str = "noc.engineer"
    remarks: str = ""
    new_description: Optional[str] = None
    assigned_to: Optional[str] = None


class StatusIn(BaseModel):
    status: str = Field(..., description="in_progress | completed")
    result: str = ""
    remarks: str = ""


class CommentIn(BaseModel):
    author: str = "noc.engineer"
    text: str


class CorrelationDecisionIn(BaseModel):
    decision: str = Field(..., description="confirm | reject")
    engineer: str = "noc.engineer"
    remarks: str = ""


class RootCauseIn(BaseModel):
    root_cause: str
    engineer: str = "noc.engineer"


class AskIn(BaseModel):
    question: str
    incident_id: Optional[str] = None
