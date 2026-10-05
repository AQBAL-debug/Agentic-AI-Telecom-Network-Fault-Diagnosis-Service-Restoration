"""
agents/restoration_agent.py  -  AGENT 7: Service Restoration & Action Planning Agent
------------------------------------------------------------------------------------
WHAT IT DOES:
    plan:   * retrieves approved SOP sections for the alarm + suspected cause (RAG)
            * builds a step-by-step action plan from a playbook per root-cause category,
              DIAGNOSTIC steps first, then non-disruptive, then potentially disruptive,
              then escalation; each step cites its SOP reference
            * adds redundancy actions when the impact agent found backup paths
            * classifies every action and marks requires_approval for disruptive ones
            * asks the LLM for a rationale/briefing (+ max 2 extra actions, which the
              Critic re-checks)
    verify: post-restoration validation (alarm clearance, interface/link status,
            latency, packet loss, jitter, utilization, service status: before vs after).
    The system NEVER executes actions on devices - it only proposes and tracks them.
"""
import json
from datetime import datetime, timedelta
from .base import BaseAgent
from . import prompts

DISRUPTIVE_WORDS = ("reset", "restart", "reboot", "reload", "shut", "rollback", "roll back", "replace", "power cycle", "switchover", "change routing")

PLAYBOOK = {
    "physical_link_failure": [
        ("Verify current interface state on both link ends", "diagnostic"),
        ("Review interface error counters and optical Rx/Tx power (last 60 min)", "diagnostic"),
        ("Check recent configuration changes on affected devices", "diagnostic"),
        ("Verify upstream connectivity and routing adjacency on the core side", "diagnostic"),
        ("Confirm physical/link status using available monitoring (DOM, remote end)", "diagnostic"),
        ("Administrative shut / no-shut of the affected interface", "potentially_disruptive"),
        ("Dispatch field engineering for fiber/physical inspection and OTDR test", "escalation"),
    ],
    "interface_failure": [
        ("Verify current interface state and error counters", "diagnostic"),
        ("Check SFP DOM (optical power, temperature)", "diagnostic"),
        ("Move traffic to redundant path if available", "non_disruptive"),
        ("Replace SFP module under approved MOP", "potentially_disruptive"),
        ("Escalate to field engineering if hardware replacement fails", "escalation"),
    ],
    "configuration_issue": [
        ("Retrieve change record and configuration diff", "diagnostic"),
        ("Compare running configuration with last known good", "diagnostic"),
        ("Roll back to last known good configuration (NOC lead + change owner approval)", "potentially_disruptive"),
        ("Escalate to network engineering if rollback is not possible", "escalation"),
    ],
    "power_or_device_failure": [
        ("Check out-of-band reachability and site power alarms", "diagnostic"),
        ("Collect device logs / crash information once reachable", "diagnostic"),
        ("Remote power cycle through intelligent PDU", "potentially_disruptive"),
        ("Dispatch field engineer / open vendor TAC case", "escalation"),
    ],
    "network_congestion": [
        ("Check top talkers and traffic matrix on congested link", "diagnostic"),
        ("Check for traffic shifted from failed parallel links", "diagnostic"),
        ("Validate telemetry against interface counters", "diagnostic"),
        ("Apply traffic engineering to move load to underutilized path", "non_disruptive"),
        ("Apply QoS prioritisation for critical services", "non_disruptive"),
        ("Change routing metrics to rebalance traffic", "potentially_disruptive"),
        ("Raise capacity-planning ticket if recurring", "escalation"),
    ],
    "software_or_cpu_failure": [
        ("Check process CPU table and control-plane protocol counters", "diagnostic"),
        ("Review syslog for crash / watchdog events", "diagnostic"),
        ("Apply control-plane policing adjustment", "non_disruptive"),
        ("Switch over to redundant routing engine", "potentially_disruptive"),
        ("Open vendor TAC case", "escalation"),
    ],
    "routing_issue": [
        ("Check routing table and neighbor state", "diagnostic"),
        ("Check provider/peer status", "diagnostic"),
        ("Apply route dampening / prefer alternate path", "non_disruptive"),
        ("Escalate to network engineering / provider", "escalation"),
    ],
    "telemetry_issue": [
        ("Cross-check metric against interface counters / second probe", "diagnostic"),
        ("Mark data point as suspect and suppress alert", "non_disruptive"),
        ("Reconfigure probe (monitoring system only)", "non_disruptive"),
    ],
}
PLAYBOOK["upstream_connectivity"] = PLAYBOOK["physical_link_failure"][:4] + [("Escalate to core network team", "escalation")]
PLAYBOOK["maintenance_activity"] = [("Confirm maintenance window with field team", "diagnostic"), ("Escalate to change manager if unplanned", "escalation")]
PLAYBOOK["undetermined"] = [("Manual investigation by NOC Tier-2", "diagnostic"), ("Escalate to network engineering", "escalation")]

ORDER = {"diagnostic": 0, "non_disruptive": 1, "potentially_disruptive": 2, "escalation": 3}
TEAM = {"diagnostic": "NOC Tier-1", "non_disruptive": "NOC Tier-2", "potentially_disruptive": "NOC Lead (approval)", "escalation": "Field / Network Engineering"}


def classify(desc: str, proposed: str) -> str:
    """Safety net: wording that implies disruption is always potentially_disruptive."""
    d = desc.lower()
    if proposed != "escalation" and any(w in d for w in DISRUPTIVE_WORDS):
        return "potentially_disruptive"
    return proposed if proposed in ORDER else "diagnostic"


class RestorationAgent(BaseAgent):
    name = "7-Restoration"
    prompt = prompts.RESTORATION

    def run(self, state):
        rca = state["rca"]
        top = rca["hypotheses"][0] if rca["hypotheses"] else {"category": "undetermined"}
        fl = state["fault_localization"].get("primary") or {}
        primary_type = state["correlation"]["primary"]["type"]
        rework = state.get("review", {}).get("verdict") == "needs_rework"
        self.log("input", {"top_hypothesis": top["category"], "fault": fl.get("location"), "rework": rework,
                           "critic_feedback": state.get("review", {}).get("comments") if rework else None})

        sops = self.tool("search_procedures(RAG)", self.tools.search_procedures,
                         summary=lambda r: [f"{x['reference']} ({x['score']})" for x in r],
                         query=f"{primary_type.replace('_', ' ')} {top['category'].replace('_', ' ')} restoration procedure", k=4)
        ref = sops[0]["reference"] if sops else "SOP-007 / Action Classification"
        steps = list(PLAYBOOK.get(top["category"], PLAYBOOK["undetermined"]))
        # second hypothesis contributes its diagnostics (cheap, safe, helps confirm/deny)
        if len(rca["hypotheses"]) > 1:
            for d, c in PLAYBOOK.get(rca["hypotheses"][1]["category"], [])[:2]:
                if c == "diagnostic" and (d, c) not in steps:
                    steps.insert(1, (d + f" (to test alternative: {rca['hypotheses'][1]['category']})", c))
        if state["service_impact"].get("degraded_devices"):
            steps.insert(0, (f"Verify traffic is flowing on redundant path for {', '.join(state['service_impact']['degraded_devices'][:4])}", "non_disruptive"))

        llm, meta = self.ask_llm(json.dumps({"fault": state["fault_localization"].get("headline"), "suspected_cause": top,
                                             "redundancy": state["service_impact"]["redundancy"],
                                             "procedures": [{"ref": s["reference"], "text": s["text"][:600]} for s in sops],
                                             "draft_plan": [d for d, _ in steps]}, default=str))
        extra = []
        if llm and isinstance(llm.get("additional_actions"), list):
            for a in llm["additional_actions"][:2]:
                if isinstance(a, dict) and a.get("description"):
                    extra.append((str(a["description"])[:200], str(a.get("category", "diagnostic")), "LLM suggestion"))
        actions = []
        for d, c in steps:
            actions.append({"description": d, "category": c, "source": "playbook"})
        for d, c, src in extra:
            # on rework, critic feedback is applied: classification enforced by safety net
            actions.append({"description": d, "category": classify(d, c) if rework else c, "source": src})
        for a in actions:
            if a["source"] == "playbook":
                a["category"] = classify(a["description"], a["category"])
        actions.sort(key=lambda a: ORDER.get(a["category"], 0))
        for i, a in enumerate(actions, 1):
            a.update(step=i, requires_approval=a["category"] in ("potentially_disruptive", "escalation"),
                     assigned_to=TEAM.get(a["category"], "NOC Tier-1"),
                     procedure_ref=next((s["reference"] for s in sops if a["category"].split("_")[0] in s["text"].lower()), ref))
        plan = {
            "target": fl.get("location"), "suspected_cause": top.get("hypothesis"),
            "actions": actions,
            "procedures": [{"reference": s["reference"], "document": s["document"], "section": s["section"], "text": s["text"]} for s in sops],
            "rationale": (llm or {}).get("rationale") or f"Diagnostic, read-only steps first to confirm '{top.get('hypothesis')}'; disruptive steps only after explicit NOC approval, per {ref}.",
            "engineer_briefing": (llm or {}).get("engineer_briefing", ""),
            "redundancy_available": bool(state["service_impact"].get("degraded_devices")),
            "llm": meta, "revision_after_review": rework,
        }
        self.log("output", {"actions": [f"{a['step']}. [{a['category']}] {a['description']}" for a in actions]})
        msgs = self.send(state, "8-Critic", f"Plan with {len(actions)} actions ready for review")
        return {"restoration_plan": plan, "knowledge": sops or state.get("knowledge", []), "messages": msgs,
                "rework_count": state.get("rework_count", 0) + (1 if rework else 0)}


def verify_restoration(tools, incident, alarms_active: list, restored_at: datetime | None = None) -> dict:
    """Post-restoration validation: compares pre-incident baseline, during-incident and post-restoration."""
    devices = sorted(set((incident.correlation or {}).get("devices", [])))
    start = datetime.fromisoformat((incident.correlation or {})["primary"]["time"])
    df = tools.get_telemetry(devices, start - timedelta(minutes=60))
    checks, ok = [], True
    if restored_at is None:   # manual validation: restoration time = last completed action
        restored_at = max((a.completed_at for a in incident_actions(tools, incident.id) if a.completed_at),
                          default=datetime.utcnow() - timedelta(minutes=5))
    for dev in devices:
        d = df[df.device == dev]
        pre = d[d.timestamp < start - timedelta(seconds=30)]
        during = d[(d.timestamp >= start - timedelta(seconds=30)) & (d.timestamp < restored_at)]
        post = d[d.timestamp >= restored_at]
        if post.empty or pre.empty:
            continue
        row = {"device": dev}
        for m, tol in [("latency_ms", 1.5), ("packet_loss_pct", 2.0), ("jitter_ms", 1.6), ("utilization_pct", 1.3)]:
            b, p = float(pre[m].mean()), float(post[m].mean())
            dv = float(during[m].mean()) if len(during) else None
            passed = p <= b * tol + (0.5 if m == "packet_loss_pct" else 2)
            ok &= passed
            row[m] = {"baseline": round(b, 2), "during": round(dv, 2) if dv is not None else None, "after": round(p, 2), "pass": passed}
        row["link_up"] = {"after": float(post["link_up"].min()), "pass": bool(post["link_up"].min() >= 1)}
        ok &= row["link_up"]["pass"]
        checks.append(row)
    alarms_ok = len(alarms_active) == 0
    svc_down = [s.id for s in tools.services if s.status != "available" and set(s.depends_on) & set(devices)]
    result = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "alarm_clearance": {"active_alarms_remaining": len(alarms_active), "pass": alarms_ok},
        "interface_status": {d: tools.devices[d].status for d in devices if d in tools.devices},
        "metrics": checks,
        "service_status": {"services_not_available": svc_down, "pass": not svc_down},
        "passed": bool(ok and alarms_ok and not svc_down and checks),
    }
    result["summary"] = ("Network performance returned to baseline, alarms cleared, services available"
                         if result["passed"] else "Validation FAILED - metrics/alarms not back to normal; escalation recommended")
    return result


def incident_actions(tools, incident_id):
    from sqlalchemy import select
    from .. import models
    return tools.db.scalars(select(models.Action).where(models.Action.incident_id == incident_id)).all()
