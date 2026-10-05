"""
llm.py
------
WHAT IT DOES:
    Thin client for the LLM via OpenRouter (OpenAI-compatible chat API).
    * chat_json(system, user)  -> asks the model to answer ONLY in JSON and parses it.
    * chat_text(system, user)  -> plain text answer (knowledge-base Q&A).
    If the key is missing, LLM_ENABLED=false, the free model is rate-limited or the
    response is not valid JSON, it returns None and every agent falls back to its
    deterministic, rule-based output. So the system NEVER breaks because of the LLM.
    Every call (prompt, latency, success) is recorded so it can be shown on the
    Agent Execution page.
"""
import json
import re
import time
import httpx
from .config import settings

URL = "https://openrouter.ai/api/v1/chat/completions"


def llm_available() -> bool:
    return bool(settings.LLM_ENABLED and settings.OPENROUTER_API_KEY)


def _call(messages, max_tokens=1500, timeout=60):
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
               "HTTP-Referer": "https://noc-agentic-ai.local", "X-Title": "NOC Agentic AI"}
    body = {"model": settings.OPENROUTER_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    r = httpx.post(URL, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"].get("content") or ""


def chat_json(system: str, user: str, max_tokens=1500):
    """Returns (parsed_json_or_None, meta_dict)."""
    meta = {"model": settings.OPENROUTER_MODEL, "used": False}
    if not llm_available():
        meta["reason"] = "LLM disabled or no API key - rule-based fallback used"
        return None, meta
    t0 = time.time()
    try:
        text = _call([{"role": "system", "content": system + "\nRespond with ONE valid JSON object only. No markdown, no prose."},
                      {"role": "user", "content": user}], max_tokens)
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
        m = re.search(r"\{.*\}", text, re.S)                    # tolerate text around the JSON
        parsed = json.loads(m.group(0) if m else text)
        meta.update(used=True, latency_s=round(time.time() - t0, 2))
        return parsed, meta
    except Exception as e:                                       # network, 429 rate limit, bad JSON ...
        meta.update(reason=f"LLM call failed ({type(e).__name__}: {str(e)[:120]}) - fallback used",
                    latency_s=round(time.time() - t0, 2))
        return None, meta


def chat_text(system: str, user: str, max_tokens=900):
    meta = {"model": settings.OPENROUTER_MODEL, "used": False}
    if not llm_available():
        meta["reason"] = "LLM disabled or no API key"
        return None, meta
    t0 = time.time()
    try:
        text = _call([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens)
        meta.update(used=True, latency_s=round(time.time() - t0, 2))
        return text.strip(), meta
    except Exception as e:
        meta.update(reason=f"LLM call failed ({type(e).__name__})", latency_s=round(time.time() - t0, 2))
        return None, meta
