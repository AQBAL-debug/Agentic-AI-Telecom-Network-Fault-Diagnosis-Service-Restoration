"""
agents/performance_agent.py  -  AGENT 4: Network Performance & Anomaly Detection Agent
--------------------------------------------------------------------------------------
WHAT IT DOES:
    * picks the devices in scope (alarmed devices + their upstream aggregation/core)
    * fetches telemetry from 60 min before the incident until now (tool: get_telemetry)
    * runs the trained anomaly model (z-score baseline + Isolation Forest)
    * compares BEFORE vs AFTER the event for every metric
    * runs the required INVESTIGATION checklist instead of jumping to conclusions:
        congestion? traffic shifted from a failed link? element degraded (CPU/memory)?
        routing change? telemetry/sensor problem?
    Result is telemetry evidence for fault localization and RCA.
"""
from datetime import timedelta
from .base import BaseAgent
from . import prompts
from ..engines.anomaly import METRICS


class PerformanceAgent(BaseAgent):
    name = "4-Performance"
    prompt = prompts.PERFORMANCE

    def run(self, state):
        alarms = [a for a in state["alarms"] if a.get("role") != "duplicate"]
        start = min(a["timestamp"] for a in alarms)
        topo = self.tools.topology
        scope = set(state["correlation"]["devices"])
        for d in list(scope):
            scope |= {u for u in topo.upstream(d) if not u.startswith("GW")}
        scope = sorted(scope)[:14]
        self.log("input", {"devices_in_scope": scope, "event_start": start.isoformat()})

        df = self.tool("get_telemetry", self.tools.get_telemetry,
                       summary=lambda d: {"rows": len(d), "devices": int(d["device"].nunique()) if len(d) else 0},
                       devices=scope, start=start - timedelta(minutes=60))
        if df.empty:
            result = {"devices_analyzed": scope, "anomalies": [], "comparison": {}, "investigation": [],
                      "summary": "No telemetry available for devices in scope"}
            return {"performance": result, "messages": self.send(state, "3-Topology", result["summary"])}

        scored = self.tool("anomaly_model.score", self.tools.model.score,
                           summary=lambda s: {"rows": len(s), "anomalous_rows": int(s["anomaly"].sum())}, df=df)
        before = scored[scored.timestamp < start - timedelta(seconds=30)]
        after = scored[scored.timestamp >= start - timedelta(seconds=30)]

        comparison, anomalies = {}, []
        for dev in scope:
            b, a = before[before.device == dev], after[after.device == dev]
            if a.empty:
                continue
            comparison[dev] = {m: {"before": round(float(b[m].mean()), 2) if len(b) else None,
                                   "current": round(float(a[m].iloc[-1]), 2),
                                   "change_pct": round((float(a[m].iloc[-1]) - float(b[m].mean())) / (abs(float(b[m].mean())) + 1e-6) * 100, 1) if len(b) else None}
                               for m in METRICS + ["link_up"]}
            an = a[a.anomaly]
            if len(an):
                worst = an.sort_values("anomaly_score").iloc[-1]
                anomalies.append({"device": dev, "anomalous_points": int(len(an)), "max_score": float(worst.anomaly_score),
                                  "pattern": worst.pattern, "top_metrics": worst.top_metrics,
                                  "first_seen": an.timestamp.min().isoformat(),
                                  "detected_by": ("isolation_forest+" if bool(worst.if_flag) else "") + ("zscore" if bool(worst.z_flag) else "")})
            # gradual degradation check: rising trend of errors/loss before the event
            if len(b) >= 6 and b["interface_errors"].iloc[-6:].is_monotonic_increasing and b["interface_errors"].iloc[-1] > 3 * (b["interface_errors"].median() + 1):
                anomalies.append({"device": dev, "pattern": "gradual_degradation_before_event",
                                  "max_score": 0.7, "top_metrics": [("interface_errors", "rising")], "anomalous_points": 6})
        anomalies.sort(key=lambda x: -x["max_score"])

        result = {"devices_analyzed": scope, "anomalies": anomalies, "comparison": comparison,
                  "investigation": self._investigate(state, anomalies, comparison),
                  "model": "per-device robust z-score + IsolationForest (hybrid)"}
        result["summary"] = (f"{len(anomalies)} anomalous device(s): " +
                             ", ".join(f"{x['device']}({x['pattern']})" for x in anomalies[:6])) if anomalies else "No performance anomaly detected"
        self.log("output", {"summary": result["summary"], "investigation": result["investigation"]})
        msgs = self.send(state, "3-Topology", result["summary"])
        return {"performance": result, "messages": msgs}

    def _investigate(self, state, anomalies, comparison):
        """The 5 questions the assignment asks before blaming utilization."""
        types = {a["alarm_type"] for a in state["alarms"]}
        pats = {a["pattern"] for a in anomalies}
        devs = state["correlation"]["devices"]
        changes = self.tools.get_changes(devs, min(a["timestamp"] for a in state["alarms"]) - timedelta(hours=2))
        cpu_high = [d for d, c in comparison.items() if c["cpu_pct"]["current"] > 85 or c["memory_pct"]["current"] > 90]
        checks = [
            {"check": "Link congestion", "result": "supported" if "congestion" in pats else "not supported",
             "evidence": [f"{a['device']}: {a['top_metrics']}" for a in anomalies if a["pattern"] == "congestion"] or ["no high-utilization + latency/loss combination"]},
            {"check": "Traffic shifted from another failed link", "result": "possible" if "interface_down" in types and "congestion" in pats else "not supported",
             "evidence": ["interface_down alarm present together with congestion"] if "interface_down" in types and "congestion" in pats else ["no failed parallel link in this incident"]},
            {"check": "Network element degraded", "result": "supported" if cpu_high or "cpu_overload" in pats else "not supported",
             "evidence": [f"{d} CPU/memory high" for d in cpu_high] or ["CPU and memory within baseline"]},
            {"check": "Routing change", "result": "possible" if types & {"bgp_neighbor_down", "ospf_neighbor_down"} or changes else "not supported",
             "evidence": [c["description"] for c in changes] or ["no routing alarms or change records"]},
            {"check": "Telemetry / sensor problem", "result": "suspected" if "possible_telemetry_issue" in pats else "not supported",
             "evidence": ["single impossible metric with other metrics normal"] if "possible_telemetry_issue" in pats else ["metrics are mutually consistent"]},
        ]
        return checks
