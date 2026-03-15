"""Heartbeat — proactive agent that wakes up periodically and decides
whether to message the user.  Reads HEARTBEAT.md for instructions."""

import os
import time
import threading
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agent.config import MLX_MODEL, MLX_BASE_URL
from agent.core.prompts import get_system_prompt
from agent.integrations.apple_calendar import fetch_all_events
from agent.memory.context_store import get_recent_dumps

_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_DIR), "core")

HEARTBEAT_INTERVAL_MINUTES = 30
SKIP_TOKEN = "HEARTBEAT_SKIP"

# Will be set by main.py after bot starts
_send_message_fn = None


def set_send_fn(fn):
    """Register the async function that sends a Telegram message.
    Signature: async fn(text: str) -> None"""
    global _send_message_fn
    _send_message_fn = fn


def _read_heartbeat_md() -> str:
    path = os.path.join(_CORE_DIR, "HEARTBEAT.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _build_heartbeat_context() -> str:
    """Assemble the context the heartbeat LLM sees."""
    now = datetime.now()
    parts = [f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"]

    # Today's events
    events = fetch_all_events()
    today_str = now.strftime("%Y-%m-%d")
    today_events = [e for e in events if e.get("date") == today_str]
    if today_events:
        parts.append("Today's events:")
        for e in today_events:
            parts.append(f"  - {e['time']}: {e['title']} ({e.get('calendar', '')})")
    else:
        parts.append("No events today.")

    # Tomorrow's events
    from datetime import timedelta
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_events = [e for e in events if e.get("date") == tomorrow_str]
    if tomorrow_events:
        parts.append("Tomorrow's events:")
        for e in tomorrow_events:
            parts.append(f"  - {e['time']}: {e['title']} ({e.get('calendar', '')})")

    # Recent stored context
    dumps = get_recent_dumps(limit=5)
    if dumps:
        parts.append("Recent stored context:")
        for d in dumps:
            parts.append(f"  - {d['content']} ({d['created_at']})")

    return "\n".join(parts)


def _heartbeat_tick():
    """One heartbeat cycle: build context, ask LLM, send if needed."""
    import re
    import asyncio

    heartbeat_md = _read_heartbeat_md()
    if not heartbeat_md:
        return

    context = _build_heartbeat_context()
    system = f"{get_system_prompt()}\n\n{heartbeat_md}"

    llm = ChatOpenAI(
        base_url=MLX_BASE_URL,
        api_key="not-needed",
        model=MLX_MODEL,
        temperature=0.1,
        max_tokens=300,
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"Here is the current state:\n\n{context}"),
    ]

    try:
        response = llm.invoke(messages)
        text = response.content or ""
        # Strip <think> tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        if SKIP_TOKEN in text:
            print(f"  [heartbeat] {datetime.now().strftime('%H:%M')} — nothing to report")
            return

        if text and _send_message_fn:
            print(f"  [heartbeat] {datetime.now().strftime('%H:%M')} — sending: {text[:60]}...")
            # Run the async send function from sync context
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_send_message_fn(text))
            loop.close()
        else:
            print(f"  [heartbeat] {datetime.now().strftime('%H:%M')} — no send_fn registered, skipping")

    except Exception as e:
        print(f"  [heartbeat] ERROR: {e}")


def heartbeat_loop():
    """Run forever, ticking every HEARTBEAT_INTERVAL_MINUTES."""
    print(f"  [heartbeat] started — every {HEARTBEAT_INTERVAL_MINUTES}min")
    while True:
        time.sleep(HEARTBEAT_INTERVAL_MINUTES * 60)
        _heartbeat_tick()


def start_heartbeat():
    """Launch the heartbeat in a background daemon thread."""
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    return t
