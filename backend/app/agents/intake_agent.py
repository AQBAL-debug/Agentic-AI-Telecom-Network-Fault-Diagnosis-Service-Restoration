"""
agents/intake_agent.py  -  AGENT 1: Network Telemetry & Alarm Intake Agent
---------------------------------------------------------------------------
WHAT IT DOES:
    First node of the workflow. Receives the incident's raw alarms (already normalized
    by engines/normalizer.py at ingestion) and:
      * reports source formats received (snmp / syslog / json)
      * validates timestamps and reports missing information / validation issues
      * identifies duplicate alarms
      * updates the CURRENT NETWORK-ELEMENT STATE (devices.status = down/degraded)
    Then sends a message to the Correlation Agent.
"""
from collections import Counter
from .base import BaseAgent
from . import prompts
from ..engines.correlation import mark_duplicates

DOWN_TYPES = {"node_unreachable", "power_failure", "backhaul_lost", "service_unavailable"}
DEGRADED_TYPES = {"interface_down", "high_cpu", "high_utilization", "high_latency", "packet_loss",
                  "crc_errors", "high_jitter", "performance_anomaly", "device_restart", "bgp_neighbor_down"}


class IntakeAgent(BaseAgent):
    name = "1-Intake"
    prompt = prompts.INTAKE

    def run(self, state):
        alarms = state["alarms"]
        self.log("input", {"alarm_count": len(alarms), "incident": state["incident_id"]})
        mark_duplicates(alarms)
        issues = [{"event": a["id"], "issues": a.get("issues", [])} for a in alarms if a.get("issues")]
        missing = [a["id"] for a in alarms if not a.get("interface") and a["alarm_type"] == "interface_down"]

        # maintain network element state
        new_state = {}
        for a in alarms:
            if a.get("status") == "cleared":
                continue
            cur = new_state.get(a["device"], "up")
            if a["alarm_type"] in DOWN_TYPES:
                new_state[a["device"]] = "down"
            elif a["alarm_type"] in DEGRADED_TYPES and cur != "down":
                new_state[a["device"]] = "degraded"
        for dev, st in new_state.items():
            if dev in self.tools.devices:
                self.tools.devices[dev].status = st
        self.tool("update_device_state", lambda states: states, states=new_state)

        result = {
            "total_alarms": len(alarms),
            "unique_alarms": sum(a.get("role") != "duplicate" for a in alarms),
            "duplicates": sum(a.get("role") == "duplicate" for a in alarms),
            "source_formats": dict(Counter(a.get("source_format", "json") for a in alarms)),
            "validation_issues": issues,
            "missing_information": [f"{x}: interface not provided" for x in missing],
            "device_states": new_state,
            "time_span_sec": (max(a["timestamp"] for a in alarms) - min(a["timestamp"] for a in alarms)).total_seconds() if alarms else 0,
        }
        self.log("output", result)
        msgs = self.send(state, "2-Correlation",
                         f"{result['unique_alarms']} unique alarms ({result['duplicates']} duplicates) from "
                         f"{len(set(a['device'] for a in alarms))} devices ready for correlation.")
        return {"intake": result, "alarms": alarms, "messages": msgs}
