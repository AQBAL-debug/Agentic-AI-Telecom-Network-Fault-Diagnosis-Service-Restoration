"""
engines/normalizer.py
---------------------
WHAT IT DOES:
    Turns alarms arriving in DIFFERENT vendor formats into ONE standard format.
    Supported inputs (simulated equivalents of real NOC feeds):
      * "json"   - REST/streaming JSON event  {"device":..,"alarm":..,"severity":..}
      * "snmp"   - SNMP trap  {"agent":..,"trap_oid":..,"varbinds":{...}}
      * "syslog" - raw syslog line  "<187>Oct 3 10:02:01 AR-01 %LINK-3-UPDOWN: Interface GE-0/0/24, changed state to down"
    It also VALIDATES each event (timestamp, known device, missing fields)
    and reports the problems instead of silently dropping the event.
    Used by the Telemetry & Alarm Intake Agent / ingestion service.
"""
import re
import uuid
from datetime import datetime, timedelta

# vendor wording  ->  canonical alarm type
ALARM_SYNONYMS = {
    "interface down": "interface_down", "link down": "interface_down", "linkdown": "interface_down",
    "port down": "interface_down", "if_down": "interface_down", "updown_down": "interface_down",
    "interface up": "interface_up", "link up": "interface_up", "linkup": "interface_up",
    "backhaul connectivity lost": "backhaul_lost", "backhaul lost": "backhaul_lost", "s1 link down": "backhaul_lost",
    "service unavailable": "service_unavailable", "cell down": "service_unavailable",
    "node unreachable": "node_unreachable", "device unreachable": "node_unreachable",
    "device restart": "device_restart", "cold start": "device_restart", "coldstart": "device_restart",
    "power failure": "power_failure", "mains failure": "power_failure",
    "high cpu": "high_cpu", "cpu threshold": "high_cpu",
    "high latency": "high_latency", "latency threshold": "high_latency",
    "packet loss": "packet_loss", "high packet loss": "packet_loss",
    "high utilization": "high_utilization", "link congestion": "high_utilization",
    "crc errors": "crc_errors", "interface errors": "crc_errors",
    "bgp neighbor down": "bgp_neighbor_down", "ospf neighbor down": "ospf_neighbor_down",
    "high jitter": "high_jitter", "config change": "config_change",
}

DEFAULT_SEVERITY = {
    "interface_down": "critical", "backhaul_lost": "critical", "service_unavailable": "critical",
    "node_unreachable": "critical", "power_failure": "critical", "device_restart": "major",
    "bgp_neighbor_down": "major", "ospf_neighbor_down": "major", "high_utilization": "major",
    "high_latency": "major", "packet_loss": "major", "high_jitter": "minor", "high_cpu": "major",
    "crc_errors": "minor", "interface_up": "cleared", "config_change": "warning",
}

SNMP_OIDS = {  # standard IF-MIB / SNMPv2 trap OIDs
    "1.3.6.1.6.3.1.1.5.3": "interface_down",   # linkDown
    "1.3.6.1.6.3.1.1.5.4": "interface_up",     # linkUp
    "1.3.6.1.6.3.1.1.5.1": "device_restart",   # coldStart
    "1.3.6.1.6.3.1.1.5.2": "device_restart",   # warmStart
}

SYSLOG_PATTERNS = [
    (re.compile(r"(?P<dev>[\w\-]+) %LINK-\d-UPDOWN: Interface (?P<if>[\w\-/\.]+), changed state to (?P<st>down|up)", re.I), "link"),
    (re.compile(r"(?P<dev>[\w\-]+) %BGP-\d-ADJCHANGE: neighbor (?P<if>[\d\.]+) Down", re.I), "bgp_neighbor_down"),
    (re.compile(r"(?P<dev>[\w\-]+) %SYS-\d-CPUHOG", re.I), "high_cpu"),
    (re.compile(r"(?P<dev>[\w\-]+) %SYS-\d-RESTART", re.I), "device_restart"),
    (re.compile(r"(?P<dev>[\w\-]+) %ENV-\d-POWER", re.I), "power_failure"),
]


def canonical_type(text: str) -> str:
    t = (text or "").strip().lower().replace("_", " ")
    if t.replace(" ", "_") in DEFAULT_SEVERITY:
        return t.replace(" ", "_")
    return ALARM_SYNONYMS.get(t, t.replace(" ", "_") or "unknown")


def _parse_ts(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value).replace("Z", ""), fmt)
        except ValueError:
            continue
    return None


def normalize(raw: dict, known_devices: dict) -> dict:
    """
    raw            -> one event in any supported format
    known_devices  -> {device_id: device_type} from inventory
    returns a dict ready to become an Alarm row, plus 'issues' (validation problems)
    """
    fmt = (raw.get("format") or "json").lower()
    issues, device, alarm_type, interface, description = [], None, None, "", raw.get("description", "")
    ts = _parse_ts(raw.get("timestamp") or raw.get("time"))

    if fmt == "snmp":
        device = raw.get("agent")
        alarm_type = SNMP_OIDS.get(raw.get("trap_oid", ""), "unknown")
        vb = raw.get("varbinds", {})
        interface = vb.get("ifName", "")
        description = description or f"SNMP trap {raw.get('trap_oid')} ifName={interface} status={vb.get('ifOperStatus','')}"
    elif fmt == "syslog":
        msg = raw.get("message", "")
        description = description or msg
        for pat, kind in SYSLOG_PATTERNS:
            m = pat.search(msg)
            if m:
                device = m.group("dev")
                interface = m.groupdict().get("if") or ""
                alarm_type = ("interface_down" if m.group("st").lower() == "down" else "interface_up") if kind == "link" else kind
                break
        if not device:
            issues.append("syslog message could not be parsed")
            alarm_type = "unknown"
            device = raw.get("device")
    else:  # json / vendor REST
        device = raw.get("device")
        alarm_type = canonical_type(raw.get("alarm") or raw.get("alarm_type") or raw.get("event_type", ""))
        interface = raw.get("interface", "") or ""

    # ---------------- validation ----------------
    if not device:
        issues.append("missing device")
        device = "UNKNOWN"
    elif device not in known_devices:
        issues.append(f"device {device} not in inventory")
    if ts is None:
        issues.append("missing/invalid timestamp - receive time used")
        ts = datetime.utcnow()
    elif ts > datetime.utcnow() + timedelta(minutes=5):
        issues.append("timestamp in the future - possible clock skew")
    if alarm_type in (None, "", "unknown"):
        issues.append("unknown alarm type")
        alarm_type = "unknown"

    severity = (raw.get("severity") or DEFAULT_SEVERITY.get(alarm_type, "minor")).lower()
    return {
        "id": raw.get("event_id") or f"EVT-{uuid.uuid4().hex[:8].upper()}",
        "timestamp": ts,
        "device": device,
        "device_type": known_devices.get(device, "unknown"),
        "alarm_type": alarm_type,
        "severity": severity,
        "interface": interface,
        "description": description or f"{alarm_type.replace('_', ' ')} on {device} {interface}".strip(),
        "status": "cleared" if alarm_type == "interface_up" else "active",
        "source_format": fmt,
        "raw": {**raw, "validation_issues": issues},
        "issues": issues,
    }
