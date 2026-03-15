"""
Intent router: pre-pass that classifies user messages before the main LLM call.

Two-tier approach:
  1. Fast keyword match for obvious intents (~0ms)
  2. LLM classifier fallback for ambiguous messages (~2-4s)

Returns:
    {
        "tools": ["get_calendar_events", ...],  # which tools to bind
        "think": False,                          # reasoning on/off
    }
"""

import json
import re
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

from agent.config import OLLAMA_MODEL
from agent.core.registry import load_skills


# ---------------------------------------------------------------------------
# Tier 1: fast keyword patterns (no LLM call)
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[list[str], list[str], bool]] = [
    # (keywords, tools, think)
    # Order matters: first match wins.
    (
        ["schedule", "create", "add", "book", "set up", "plan a", "block"],
        ["create_event"],
        False,
    ),
    (
        ["move", "reschedule", "shift", "push", "postpone", "change time"],
        ["move_event", "get_calendar_events"],
        False,
    ),
    (
        ["remember", "save", "note", "keep in mind", "store", "don't forget"],
        ["store_context"],
        False,
    ),
    (
        ["calendar", "schedule", "today", "tomorrow", "this week", "what's on",
         "whats on", "events", "free", "busy", "available", "availability",
         "upcoming", "agenda", "plans"],
        ["get_calendar_events"],
        False,
    ),
]


def _keyword_match(msg: str) -> dict | None:
    """Try fast keyword matching. Returns intent dict or None if ambiguous."""
    lower = msg.lower()
    for keywords, tools, think in _KEYWORD_RULES:
        if any(kw in lower for kw in keywords):
            return {"tools": tools, "think": think}
    return None


# ---------------------------------------------------------------------------
# Tier 2: LLM classifier (fallback)
# ---------------------------------------------------------------------------

_TOOL_SUMMARY: str | None = None


def _get_tool_summary() -> str:
    global _TOOL_SUMMARY
    if _TOOL_SUMMARY is not None:
        return _TOOL_SUMMARY
    tools = load_skills()
    lines = [f"- {t.name}: {t.description[:120]}" for t in tools]
    _TOOL_SUMMARY = "\n".join(lines) if lines else "(no tools available)"
    return _TOOL_SUMMARY


_ROUTER_PROMPT = """You are an intent classifier. Given the user message, decide:

1. Which tools (if any) are needed to handle it.
2. Whether complex reasoning is required (multi-step planning, scheduling conflicts, etc.).

Available tools:
{tool_summary}

Respond with ONLY a JSON object, nothing else:
{{"tools": ["tool_name", ...], "think": true/false}}

Rules:
- tools: list tool names that MUST be called. Empty list = general chat.
- think: true ONLY for complex multi-step scheduling/planning. false for everything else.
- If the user asks about their schedule/calendar/events, include "get_calendar_events".
- If the user wants to create/schedule/add an event, include "create_event".
- If the user wants to move/reschedule an event, include "move_event".
- If the user shares info to remember, include "store_context".
- For greetings or general chat: tools=[], think=false.
"""


def _llm_classify(user_message: str) -> dict:
    """Use the LLM to classify ambiguous intents."""
    tool_summary = _get_tool_summary()
    prompt = _ROUTER_PROMPT.format(tool_summary=tool_summary)

    llm = ChatOllama(
        model=OLLAMA_MODEL,
        temperature=0.0,
        num_predict=500,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_message),
        ])
        raw = response.content.strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            print(f"  [router] WARNING: could not parse JSON from: {raw[:100]}")
            return {"tools": [], "think": False}

        known = {t.name for t in load_skills()}
        valid_tools = [t for t in result.get("tools", []) if t in known]

        return {
            "tools": valid_tools,
            "think": bool(result.get("think", False)),
        }
    except Exception as e:
        print(f"  [router] ERROR: {e} -- falling back to all tools")
        return {"tools": [t.name for t in load_skills()], "think": False}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(user_message: str) -> dict:
    """Classify intent of a user message.

    Tries fast keyword match first. Falls back to LLM for ambiguous messages.

    Returns dict with keys:
        tools  (list[str]): tool names to bind for the main call
        think  (bool):      whether reasoning mode should be enabled
    """
    # Tier 1: instant keyword match
    result = _keyword_match(user_message)
    if result is not None:
        print(f"  [router] keyword match: {result}")
        return result

    # Tier 2: LLM classification
    print(f"  [router] no keyword match, using LLM classifier...")
    result = _llm_classify(user_message)
    print(f"  [router] LLM classified: {result}")
    return result
