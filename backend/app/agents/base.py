"""
agents/base.py
--------------
WHAT IT DOES:
    Base class shared by all agents.
      * self.log(...)   -> writes an agent step into the trace (agent_logs table)
      * self.tool(...)  -> calls a tool through the Toolbox (traced = "tool calling")
      * self.send(...)  -> AGENT-TO-AGENT COMMUNICATION: appends a message to the shared
                           workflow state ("messages"); the next agents read it.
      * self.ask_llm()  -> calls the LLM with the agent's system prompt and records it.
    Every agent implements run(state) -> dict of state updates (LangGraph node contract).
"""
from datetime import datetime
from ..llm import chat_json


class BaseAgent:
    name = "Agent"
    prompt = ""

    def __init__(self, tools):
        self.tools = tools

    def log(self, step_type: str, content: dict):
        self.tools.tracer.log(self.name, step_type, content)

    def tool(self, tool_name: str, fn, summary=None, **kwargs):
        return self.tools.call(self.name, tool_name, fn, summary, **kwargs)

    def send(self, state: dict, to: str, content: str):
        msg = {"from": self.name, "to": to, "time": datetime.utcnow().isoformat(timespec="seconds"), "content": content}
        self.log("message", msg)
        return state.get("messages", []) + [msg]

    def ask_llm(self, user_payload: str, max_tokens=1500):
        parsed, meta = chat_json(self.prompt, user_payload, max_tokens)
        self.log("llm", {"prompt_preview": user_payload[:1500], "meta": meta, "response": parsed})
        return parsed, meta

    def run(self, state: dict) -> dict:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError
