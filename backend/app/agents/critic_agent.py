"""
agents/critic_agent.py  -  AGENT 8: Network Operations Reviewer / Critic Agent
------------------------------------------------------------------------------
WHAT IT DOES:
    Reviews the other agents' work BEFORE anything reaches the engineer:
      * correlation primary consistent with the localized fault?
      * fault localization has evidence and alternatives?
      * anomaly results present when performance alarms exist?
      * service impact uses only known customer numbers?
      * every RCA hypothesis has supporting evidence and is still "suspected"?
      * every disruptive action is classified potentially_disruptive + requires approval?
    If a safety rule fails -> verdict "needs_rework" -> LangGraph routes back to the
    Restoration Agent once (reassessment loop). LLM adds free-text review comments.
"""
import json
from .base import BaseAgent
from . import prompts
from .restoration_agent import DISRUPTIVE_WORDS


class CriticAgent(BaseAgent):
    name = "8-Critic"
    prompt = prompts.CRITIC

    def run(self, state):
        issues, notes = [], []
        corr, fl, perf = state["correlation"], state["fault_localization"], state["performance"]
        top = fl.get("primary") or {}
        if not top:
            issues.append("No fault location produced")
        else:
            if corr["primary"]["device"] not in top.get("endpoints", [top["location"]]) + top.get("explained_devices", []):
                notes.append(f"Correlation primary ({corr['primary']['device']}) differs from top fault location ({top['location']}) - engineer should verify")
            if not top.get("evidence"):
                issues.append("Top fault location has no evidence")
            if not fl.get("alternatives"):
                notes.append("No alternative fault hypotheses listed")
        perf_alarms = {"high_latency", "packet_loss", "high_utilization", "performance_anomaly", "high_jitter"} & {a["alarm_type"] for a in state["alarms"]}
        if perf_alarms and not perf.get("anomalies"):
            notes.append("Performance alarms received but anomaly model found no anomaly - possible telemetry issue")
        for s in state["service_impact"].get("affected_services", []):
            if s["customers"] != "unknown" and not isinstance(s["customers"], int):
                issues.append(f"Customer count for {s['service_id']} is not from source data")
        for h in state["rca"]["hypotheses"]:
            if not h.get("supporting_evidence"):
                issues.append(f"Hypothesis '{h['category']}' has no supporting evidence")
            if h.get("status") != "suspected":
                issues.append(f"Hypothesis '{h['category']}' must remain suspected until engineer confirmation")
            if h["confidence"] > 0.9:
                h["confidence"] = 0.9
                notes.append(f"Capped confidence of '{h['category']}' at 0.9 (not verified)")
        unsafe = [a for a in state["restoration_plan"]["actions"]
                  if any(w in a["description"].lower() for w in DISRUPTIVE_WORDS)
                  and a["category"] != "escalation" and (a["category"] != "potentially_disruptive" or not a["requires_approval"])]
        for a in unsafe:
            issues.append(f"Action '{a['description'][:60]}' is disruptive but classified '{a['category']}'")

        llm, meta = self.ask_llm(json.dumps({"fault": fl.get("headline"), "rca": state["rca"]["summary"],
                                             "hypotheses": [(h["category"], h["confidence"]) for h in state["rca"]["hypotheses"]],
                                             "impact": state["service_impact"]["summary"],
                                             "actions": [(a["description"], a["category"]) for a in state["restoration_plan"]["actions"]],
                                             "rule_check_issues": issues}, default=str), max_tokens=700)
        llm_comments = [str(c)[:300] for c in (llm or {}).get("comments", [])][:5]
        verdict = "needs_rework" if issues and state.get("rework_count", 0) < 1 else "approved"
        review = {"verdict": verdict, "blocking_issues": issues, "comments": notes + llm_comments,
                  "checks": ["correlation consistency", "fault evidence", "anomaly consistency", "no invented customers",
                             "hypotheses evidence-backed & suspected", "disruptive actions require approval"],
                  "llm": meta, "rework_count": state.get("rework_count", 0)}
        self.log("review", review)
        msgs = self.send(state, "7-Restoration" if verdict == "needs_rework" else "NOC Engineer",
                         "Rework required: " + "; ".join(issues) if verdict == "needs_rework" else "Analysis approved for human review")
        return {"review": review, "messages": msgs}
