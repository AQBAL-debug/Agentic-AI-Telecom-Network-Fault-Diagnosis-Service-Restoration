"""
agents/topology_agent.py  -  AGENT 3: Network Topology & Fault Localization Agent
---------------------------------------------------------------------------------
WHAT IT DOES:
    * builds {device: alarm types} and {device: alarmed interfaces} for the incident
    * calls Topology.localize() -> ranked device AND link candidates scored by
      coverage, precision (would it wrongly take down healthy devices?), own alarm,
      earliest alarm, exact-interface match
    * adds TELEMETRY EVIDENCE from the Performance Agent and SIBLING evidence
      (e.g. "base stations behind AR-02 are still healthy")
    Output = suspected device/link, supporting alarms, topology evidence, telemetry
    evidence, confidence and alternative hypotheses (Requirement 8).
"""
from collections import defaultdict
from .base import BaseAgent
from . import prompts


class TopologyAgent(BaseAgent):
    name = "3-Topology"
    prompt = prompts.TOPOLOGY

    def run(self, state):
        topo = self.tools.topology
        alarms = [a for a in state["alarms"] if a.get("role") not in ("duplicate", "independent")]
        alarmed, ifaces = defaultdict(list), defaultdict(set)
        for a in alarms:
            alarmed[a["device"]].append(a["alarm_type"])
            if a.get("interface"):
                ifaces[a["device"]].add(a["interface"])
        first = min(alarms, key=lambda a: a["timestamp"])["device"]
        self.log("input", {"alarmed_devices": dict(alarmed), "first_alarm_device": first})

        hyps = self.tool("topology.localize", topo.localize,
                         summary=lambda hs: [f"{h['type']}:{h['location']} score={round(h['score'], 2)}" for h in hs],
                         alarmed=dict(alarmed), first_alarm_device=first, alarm_ifaces=dict(ifaces))

        perf = {a["device"]: a for a in state.get("performance", {}).get("anomalies", [])}
        for h in hyps:
            devs = h.get("endpoints", [h["location"]]) + h["explained_devices"]
            h["telemetry_evidence"] = [f"{d}: {perf[d]['pattern']} (score {perf[d]['max_score']})" for d in dict.fromkeys(devs) if d in perf]
            h["supporting_alarms"] = [f"{a['device']} {a['alarm_type']} {a.get('interface', '')}".strip()
                                      for a in alarms if a["device"] in devs][:12]
            if h["type"] == "device" and h["location"] in topo.g:
                parents = list(topo.g.predecessors(h["location"]))
                siblings = {s for p in parents for s in topo.g.successors(p)} - {h["location"]} - set(alarmed)
                if siblings:
                    h["evidence"].append(f"Peer devices on the same parent are healthy: {', '.join(sorted(siblings))}")
                unaffected = [x for x in topo.g.nodes if topo.g.nodes[x]["layer"] == topo.g.nodes[h["location"]]["layer"]
                              and x not in alarmed and x != h["location"]]
                if unaffected and h["location"].startswith("AR"):
                    h["evidence"].append(f"Other aggregation routers operational: {', '.join(sorted(u for u in unaffected if u.startswith('AR')))}")

        top = hyps[0] if hyps else None
        result = {
            "primary": top,
            "alternatives": hyps[1:5],
            "path_to_core": topo.path_to_core(top["endpoints"][1] if top and top["type"] == "link" else top["location"]) if top else [],
            "fault_domain": sorted({top["location"], *top["explained_devices"]}) if top else [],
            "method": "single-point-of-failure scoring over NetworkX dependency graph",
        }
        if top:
            result["headline"] = (f"Primary suspected fault location: {top['location']} "
                                  f"({'link ' + ' <-> '.join(top.get('interfaces', top.get('endpoints', []))) if top['type'] == 'link' else 'device / uplink interface'}) - confidence {top['confidence']}")
        self.log("output", {"headline": result.get("headline"), "alternatives": [h["location"] for h in result["alternatives"]]})
        msgs = self.send(state, "5-Impact", result.get("headline", "no candidate"))
        return {"fault_localization": result, "messages": msgs}
