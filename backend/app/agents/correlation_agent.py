"""
agents/correlation_agent.py  -  AGENT 2: Alarm Correlation Agent
----------------------------------------------------------------
WHAT IT DOES:
    Calls the correlation engine (time window + topology) on the incident's alarms and
    produces the correlated-incident view:
      primary suspected event, consequential events, duplicates (suppressed in view,
      kept for audit), independent alarms, alarm-storm summary and the reasoning.
    It also builds the incident TIMELINE. Sends findings to the Performance Agent.
"""
from .base import BaseAgent
from . import prompts
from ..engines.correlation import correlate


class CorrelationAgent(BaseAgent):
    name = "2-Correlation"
    prompt = prompts.CORRELATION

    def run(self, state):
        alarms = state["alarms"]
        self.log("input", {"alarms": [f"{a['timestamp'].strftime('%H:%M:%S')} {a['device']} {a['alarm_type']}" for a in alarms[:30]]})
        groups = self.tool("correlate_alarms", correlate,
                           summary=lambda gs: [{"primary": g["primary_device"] + ":" + g["primary_type"],
                                                "size": len(g["alarm_ids"])} for g in gs],
                           alarms=[dict(a) for a in alarms], topo=self.tools.topology)
        # the incident = biggest group; any other group inside the incident = independent sub-events
        groups.sort(key=lambda g: -len(g["alarm_ids"]))
        main = groups[0]
        by_id = {a["id"]: a for a in alarms}
        roles = {main["primary_id"]: "primary", **{i: "consequential" for i in main["consequential_ids"]},
                 **{i: "duplicate" for i in main["duplicate_ids"]}}
        independent = []
        for g in groups[1:]:
            for i in g["alarm_ids"]:
                roles[i] = "independent"
                independent.append(i)
        for i, r in roles.items():
            by_id[i]["role"] = r

        def fmt(i):
            a = by_id[i]
            return {"id": i, "time": a["timestamp"].isoformat(), "device": a["device"], "type": a["alarm_type"],
                    "severity": a["severity"], "interface": a.get("interface", "")}

        result = {
            "primary": fmt(main["primary_id"]),
            "consequential": [fmt(i) for i in main["consequential_ids"]][:60],
            "duplicates": [fmt(i) for i in main["duplicate_ids"]][:60],
            "duplicate_count": len(main["duplicate_ids"]),
            "independent": [fmt(i) for i in independent][:30],
            "devices": main["devices"],
            "storm": main["storm"] or len(alarms) >= 50,
            "storm_summary": main["storm_summary"] or ({"total_alarms": len(alarms)} if len(alarms) >= 50 else {}),
            "reasoning": main["reasoning"],
            "confidence": "high" if len(main["devices"]) > 1 and main["reasoning"] else "medium",
        }
        timeline = [{"time": a["timestamp"].isoformat(), "event": f"{a['device']} {a['alarm_type']} ({roles.get(a['id'], 'n/a')})"}
                    for a in sorted(alarms, key=lambda x: x["timestamp"]) if roles.get(a["id"]) != "duplicate"][:40]
        self.log("output", {k: result[k] for k in ("primary", "devices", "storm", "reasoning")})
        msgs = self.send(state, "4-Performance",
                         f"Primary suspected event {result['primary']['device']} {result['primary']['type']}; "
                         f"{len(result['consequential'])} consequential alarms on {', '.join(result['devices'])}.")
        return {"correlation": result, "alarms": alarms, "timeline": timeline, "messages": msgs}
