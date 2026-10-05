r"""
agents/graph.py
---------------
WHAT IT DOES:
    MULTI-AGENT ORCHESTRATION with LangGraph.
    Defines the shared workflow state (NOCState) and wires the 8 agents as graph nodes:

      intake -> correlation -> performance -> topology(fault localization) -> impact
             -> rca -> restoration -> critic --(needs_rework, max 1)--> restoration
                                          \--(approved)--> END  (=> human approval)

    * Shared state = every agent reads previous results and writes its own key.
    * Agent-to-agent messages travel in state["messages"].
    * The conditional edge after the critic is the "request reassessment" loop.
    * Human-in-the-loop: the graph ends with status "awaiting_approval"; nothing is
      executed until an engineer approves actions through the API/UI.
    If LangGraph is not installed, a simple sequential runner with the same logic is used.
"""
from typing import TypedDict, Any
from .intake_agent import IntakeAgent
from .correlation_agent import CorrelationAgent
from .performance_agent import PerformanceAgent
from .topology_agent import TopologyAgent
from .impact_agent import ImpactAgent
from .rca_agent import RCAAgent
from .restoration_agent import RestorationAgent
from .critic_agent import CriticAgent


class NOCState(TypedDict, total=False):
    incident_id: str
    run_id: str
    alarms: list
    intake: dict
    correlation: dict
    timeline: list
    performance: dict
    fault_localization: dict
    service_impact: dict
    rca: dict
    historical: list
    knowledge: list
    restoration_plan: dict
    review: dict
    rework_count: int
    messages: list
    trace: Any


# node names end with "_agent" because LangGraph forbids node names equal to state keys
AGENT_ORDER = ["intake_agent", "correlation_agent", "performance_agent", "topology_agent",
               "impact_agent", "rca_agent", "restoration_agent", "critic_agent"]


def _after_critic(state: NOCState) -> str:
    return "restoration_agent" if state.get("review", {}).get("verdict") == "needs_rework" else "end"


def build_graph(tools):
    agents = dict(zip(AGENT_ORDER, [IntakeAgent(tools), CorrelationAgent(tools), PerformanceAgent(tools),
                                    TopologyAgent(tools), ImpactAgent(tools), RCAAgent(tools),
                                    RestorationAgent(tools), CriticAgent(tools)]))
    try:
        from langgraph.graph import StateGraph, END
        g = StateGraph(NOCState)
        for name, agent in agents.items():
            g.add_node(name, agent.run)
        g.set_entry_point("intake_agent")
        for a, b in zip(AGENT_ORDER[:-1], AGENT_ORDER[1:]):
            g.add_edge(a, b)
        g.add_conditional_edges("critic_agent", _after_critic, {"restoration_agent": "restoration_agent", "end": END})
        return g.compile(), "langgraph"
    except ImportError:  # fallback runner
        class Sequential:
            def invoke(self, state):
                for n in AGENT_ORDER:
                    state.update(agents[n].run(state))
                while _after_critic(state) == "restoration_agent":
                    state.update(agents["restoration_agent"].run(state))
                    state.update(agents["critic_agent"].run(state))
                return state
        return Sequential(), "sequential"


def run_workflow(tools, incident_id: str, run_id: str, alarms: list) -> dict:
    graph, engine = build_graph(tools)
    tools.tracer.log("Orchestrator", "input", {"engine": engine, "agents": AGENT_ORDER, "alarm_count": len(alarms)})
    final = graph.invoke({"incident_id": incident_id, "run_id": run_id, "alarms": alarms, "messages": [], "rework_count": 0})
    tools.tracer.log("Orchestrator", "output", {"status": "awaiting_approval", "review": final.get("review", {}).get("verdict")})
    return final
