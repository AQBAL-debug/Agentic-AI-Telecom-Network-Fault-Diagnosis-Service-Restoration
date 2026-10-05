"""
agents/impact_agent.py  -  AGENT 5: Service Impact Analysis Agent
-----------------------------------------------------------------
WHAT IT DOES:
    Takes the top fault hypothesis (device or link) and the devices actually observed
    down, and calls engines/impact.py to compute:
      affected devices / links / base stations, unavailable vs degraded services,
      service groups, regions, redundancy status and known customer impact
      (unknown customer counts stay "unknown" - never invented).
"""
from .base import BaseAgent
from . import prompts
from ..engines.impact import analyze_impact


class ImpactAgent(BaseAgent):
    name = "5-Impact"
    prompt = prompts.IMPACT

    def run(self, state):
        top = state["fault_localization"].get("primary")
        observed_down = [d for d, s in state["intake"]["device_states"].items() if s == "down"]
        nodes, edges = [], []
        if top and top["type"] == "link":
            edges = [tuple(top["endpoints"])]
        elif top and top["confidence"] != "low" and any(t in ("interface_down", "node_unreachable", "power_failure", "device_restart")
                                                        for a in state["alarms"] if a["device"] == top["location"] for t in [a["alarm_type"]]):
            nodes = [top["location"]]
        self.log("input", {"failed_nodes": nodes, "failed_edges": edges, "observed_down": observed_down})
        res = self.tool("impact.analyze", analyze_impact, summary=lambda r: r["summary"], topo=self.tools.topology,
                        services=self.tools.services, failed_nodes=nodes, failed_edges=edges, observed_down=observed_down)
        if not nodes and not edges:
            # performance-type incident: services degraded where anomalies are
            degraded_devs = {a["device"] for a in state.get("performance", {}).get("anomalies", [])}
            for s in self.tools.services:
                hit = set(s.depends_on) & degraded_devs
                if hit and s.id not in {r["service_id"] for r in res["affected_services"]}:
                    res["affected_services"].append({"service_id": s.id, "name": s.name, "type": s.service_type,
                                                     "region": s.region, "status": "degraded",
                                                     "reason": f"performance anomaly on {', '.join(sorted(hit))}",
                                                     "customers": s.customers if s.customers is not None else "unknown"})
            res["degraded_devices"] = sorted(set(res["degraded_devices"]) | degraded_devs)
            res["summary"] = (f"Performance impact: {len(res['affected_services'])} service(s) potentially degraded "
                              f"on {', '.join(sorted(degraded_devs)) or 'no devices'}; no outage detected")
        self.log("output", {"summary": res["summary"]})
        msgs = self.send(state, "6-RCA", res["summary"])
        return {"service_impact": res, "messages": msgs}
