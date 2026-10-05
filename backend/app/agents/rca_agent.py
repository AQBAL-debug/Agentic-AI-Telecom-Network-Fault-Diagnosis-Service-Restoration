"""
agents/rca_agent.py  -  AGENT 6: Root Cause Analysis & Troubleshooting Agent
----------------------------------------------------------------------------
WHAT IT DOES:
    1. Gathers evidence with tools: device logs, configuration-change and maintenance
       history, similar historical incidents (similarity retrieval), relevant SOPs (RAG).
    2. Builds RULE-BASED hypotheses for each root-cause category (physical link,
       interface hardware, configuration, upstream, power/restart, congestion,
       software/CPU, routing, telemetry issue) with SUPPORTING and CONTRADICTING
       evidence and the verification needed to confirm.
    3. Asks the LLM to review/re-weigh them (confidence may move at most +-0.2 from the
       rule score and evidence lists are never taken from the LLM -> no invented facts).
    Root cause always stays "SUSPECTED" until a NOC engineer confirms it.
"""
import json
from datetime import timedelta
from .base import BaseAgent
from . import prompts


class RCAAgent(BaseAgent):
    name = "6-RCA"
    prompt = prompts.RCA

    def run(self, state):
        fl = state["fault_localization"]
        top = fl.get("primary") or {}
        alarms = [a for a in state["alarms"] if a.get("role") != "duplicate"]
        start = min(a["timestamp"] for a in alarms)
        cand = top.get("endpoints", [top.get("location")]) if top else []
        cand = [c for c in cand if c]
        self.log("input", {"top_fault": top.get("location"), "candidates": cand})

        logs = self.tool("get_device_logs", self.tools.get_device_logs, devices=cand + state["correlation"]["devices"][:6],
                         since=start - timedelta(hours=1))
        changes = self.tool("get_change_and_maintenance_history", self.tools.get_changes, devices=cand,
                            since=start - timedelta(hours=24))
        dev_type = self.tools.devices[cand[-1]].device_type if cand and cand[-1] in self.tools.devices else ""
        pattern = " ".join(sorted({a["alarm_type"] for a in alarms})) + f" {dev_type} downstream"
        hist = self.tool("similar_incidents", self.tools.similar_incidents,
                         summary=lambda r: [f"{h['id']} ({h['similarity']})" for h in r],
                         query=pattern, device_type=dev_type, downstream_count=len(top.get("explained_devices", [])) - 1)
        sop = self.tool("search_procedures(RAG)", self.tools.search_procedures,
                        summary=lambda r: [x["reference"] for x in r],
                        query=f"root cause {pattern} troubleshooting fault isolation", k=3)

        hyps = self._rules(state, alarms, top, cand, changes, hist, logs, start)
        llm, meta = self.ask_llm(json.dumps({
            "fault_location": fl.get("headline"), "correlation": state["correlation"]["reasoning"],
            "anomalies": state["performance"].get("summary"), "investigation": state["performance"].get("investigation"),
            "impact": state["service_impact"]["summary"], "changes": changes, "historical": [h["title"] + " -> " + h["root_cause"] for h in hist],
            "hypotheses": [{k: h[k] for k in ("category", "hypothesis", "confidence", "supporting_evidence", "contradicting_evidence")} for h in hyps]},
            default=str))
        summary = None
        if llm and isinstance(llm.get("hypotheses"), list):
            by_cat = {h["category"]: h for h in hyps}
            for lh in llm["hypotheses"]:
                h = by_cat.get(lh.get("category"))
                if h and isinstance(lh.get("confidence"), (int, float)):
                    h["confidence"] = round(min(max(float(lh["confidence"]), h["confidence"] - 0.2), h["confidence"] + 0.2, 0.95), 2)
                    h["llm_reasoning"] = str(lh.get("reasoning", ""))[:600]
            summary = llm.get("summary")
        hyps.sort(key=lambda h: -h["confidence"])
        for i, h in enumerate(hyps, 1):
            h["rank"] = i
            h["status"] = "suspected"
        result = {
            "hypotheses": hyps[:6],
            "top_suspected": hyps[0]["hypothesis"] if hyps else "insufficient evidence",
            "summary": summary or (f"Most probable (suspected) cause: {hyps[0]['hypothesis']} at {top.get('location')}. "
                                   f"Confidence {hyps[0]['confidence']}. Verification required before confirmation." if hyps else "No hypothesis"),
            "evidence_sources": {"logs": logs[:10], "changes": changes, "historical_incidents": [h["id"] for h in hist]},
            "llm": meta,
            "status": "suspected",
        }
        self.log("output", {"top": result["top_suspected"], "summary": result["summary"]})
        msgs = self.send(state, "7-Restoration", f"Top suspected root cause: {result['top_suspected']}")
        return {"rca": result, "historical": hist, "knowledge": sop, "messages": msgs}

    # ---------------------------------------------------------------- rules
    def _rules(self, state, alarms, top, cand, changes, hist, logs, start):
        types = {}
        for a in alarms:
            types.setdefault(a["alarm_type"], set()).add(a["device"])
        pats = {x["pattern"]: x["device"] for x in state["performance"].get("anomalies", [])}
        loc = top.get("location", "unknown")
        hist_cats = {h["root_cause_category"]: h["id"] for h in hist}
        link = None
        if top.get("type") == "link":
            link = self.tools.topology.link_between(*top["endpoints"])
        else:
            for p in self.tools.topology.g.predecessors(loc) if loc in self.tools.topology.g else []:
                link = self.tools.topology.g.edges[p, loc]
        upstream_alarmed = [u for u in (self.tools.topology.upstream(loc) if loc in self.tools.topology.g else []) if u in {a["device"] for a in alarms}]
        cfg = [c for c in changes if c["type"] == "configuration"]
        mnt = [c for c in changes if c["type"] == "maintenance"]
        H = []

        def add(cat, hyp, conf, sup, con, verify):
            sup = [s for s in sup if s]
            if cat in hist_cats:
                sup.append(f"Similar historical incident {hist_cats[cat]} had this root cause (evidence, not proof)")
                conf += 0.05
            if not sup:
                return
            H.append({"category": cat, "hypothesis": hyp, "confidence": round(min(conf, 0.9), 2),
                      "supporting_evidence": sup, "contradicting_evidence": [c for c in con if c], "required_verification": verify})

        if "interface_down" in types:
            both = top.get("type") == "link" and all(e in types.get("interface_down", set()) for e in top.get("endpoints", []))
            add("physical_link_failure", f"Physical uplink/fiber failure on the link to {loc}", 0.55 + (0.2 if both else 0),
                [f"interface_down on {', '.join(sorted(types['interface_down']))}",
                 "Both link ends report down" if both else "",
                 f"Link medium: {link['id'] if link else 'n/a'}" if link else ""],
                ["Configuration change shortly before the event" if cfg else "",
                 "Only one end of the link reports down" if not both and top.get("type") == "link" else ""],
                ["Check optical Rx/Tx power on both ends", "Check remote-end interface state", "OTDR test by field team if light is absent"])
            add("interface_failure", f"Interface / SFP hardware failure on {loc}", 0.45,
                [f"interface_down on {loc}" if loc in types["interface_down"] else "",
                 f"Interface errors rising before failure on {pats.get('gradual_degradation_before_event')}" if "gradual_degradation_before_event" in pats else ""],
                ["Both link ends down suggests span rather than one port" if both else "",
                 "No error-counter increase before the failure" if "gradual_degradation_before_event" not in pats else ""],
                ["Review CRC/input error counters history", "Check SFP DOM values", "Swap SFP under approved MOP"])
        from datetime import datetime as _dt
        recent = [c for c in cfg if (start - _dt.fromisoformat(c["time"])).total_seconds() <= 7200]
        older = [c for c in cfg if c not in recent]
        add("configuration_issue", f"Recent configuration change on {loc}", 0.75 if recent else 0.2 if older else 0,
            [f"Change {c['id']} {int((start - _dt.fromisoformat(c['time'])).total_seconds() // 60)} min before first alarm: {c['description']}" for c in recent]
            + [f"Older change {c['id']} ({c['description']})" for c in older],
            ([] if recent else [f"Last change was {int((start - _dt.fromisoformat(older[-1]['time'])).total_seconds() // 3600)} h before the event - timing does not match"] if older
             else ["No configuration change recorded in the last 24 h"]),
            ["Compare running vs last-known-good config", "Confirm change timing vs first alarm"])
        if mnt:
            add("maintenance_activity", f"Planned maintenance activity on {loc}", 0.5,
                [f"Maintenance {c['id']}: {c['description']}" for c in mnt], [], ["Check maintenance window and field team activity"])
        add("upstream_connectivity", f"Upstream connectivity problem above {loc}", 0.5 if upstream_alarmed else 0.15,
            [f"Upstream device(s) also alarming: {', '.join(upstream_alarmed)}" if upstream_alarmed else
             ("Downstream outage pattern is also consistent with an upstream loss" if "backhaul_lost" in types else "")],
            [] if upstream_alarmed else ["Upstream core devices show no alarms"],
            ["Verify upstream interface and routing adjacency on the core router"])
        restart = types.get("power_failure", set()) | types.get("device_restart", set()) | types.get("node_unreachable", set())
        add("power_or_device_failure", f"Power failure / device restart at {loc}", 0.75 if loc in restart else 0.35 if restart else 0,
            [f"{t} on {', '.join(sorted(d))}" for t, d in types.items() if t in ("power_failure", "device_restart", "node_unreachable")],
            [f"{loc} is still reporting alarms/telemetry, so it is powered" if loc in {a['device'] for a in alarms} and loc not in restart else ""],
            ["Check site power alarms and device uptime", "Check out-of-band reachability"])
        add("network_congestion", f"Network congestion on {pats.get('congestion', loc)}", 0.6 if "congestion" in pats else 0,
            [f"Congestion pattern detected by anomaly model on {pats['congestion']}" if "congestion" in pats else ""],
            ["Interface failure present - congestion may be a consequence (traffic shift)" if "interface_down" in types else "",
             "High utilization alone is not proof of root cause"],
            ["Check traffic matrix / top talkers", "Check for traffic shift from failed links", "Validate telemetry source"])
        add("software_or_cpu_failure", f"Software/process or CPU overload on {pats.get('cpu_overload', loc)}", 0.55 if "cpu_overload" in pats or "high_cpu" in types else 0,
            [f"CPU overload anomaly on {pats['cpu_overload']}" if "cpu_overload" in pats else "", "high_cpu alarm" if "high_cpu" in types else ""],
            [], ["Check process CPU table", "Check control-plane protocol storm"])
        add("routing_issue", "Routing adjacency / route change", 0.55 if types.keys() & {"bgp_neighbor_down", "ospf_neighbor_down"} else 0,
            [f"{t} on {', '.join(sorted(types[t]))}" for t in ("bgp_neighbor_down", "ospf_neighbor_down") if t in types], [],
            ["Check routing table and neighbor state"])
        add("telemetry_issue", "Telemetry / sensor measurement error", 0.6 if "possible_telemetry_issue" in pats and "interface_down" not in types else 0.1 if "possible_telemetry_issue" in pats else 0,
            [f"Single impossible metric value on {pats['possible_telemetry_issue']}" if "possible_telemetry_issue" in pats else ""],
            ["Service-affecting alarms exist, so the problem is real" if types.keys() & {"backhaul_lost", "service_unavailable"} else ""],
            ["Cross-check with interface counters / second probe"])
        H = [h for h in H if h["confidence"] > 0.05]
        if not H:
            H.append({"category": "undetermined", "hypothesis": "Insufficient evidence for a specific cause", "confidence": 0.2,
                      "supporting_evidence": ["Alarms present but no matching pattern"], "contradicting_evidence": [],
                      "required_verification": ["Manual investigation by NOC engineer"]})
        return H
