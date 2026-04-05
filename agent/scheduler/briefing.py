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
from agent.integrations.apple_calendar import fetch_all_events, full_sync
from agent.integrations.apple_mail import get_unprocessed_emails, classify_emails
from agent.integrations.apple_notes import ingest_notes
from agent.memory.facts import pending_staging
from agent.memory.context_store import get_recent_dumps, store_context_dump
from agent.memory.database import db

_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_DIR), "core")

HEARTBEAT_INTERVAL_MINUTES = 30
SKIP_TOKEN = "HEARTBEAT_SKIP"

# Will be set by main.py after bot starts
_send_message_fn = None

# ── LLM priority lock ───────────────────────────────────────────
_last_user_message_ts: float = 0.0


def record_user_activity():
    """Called by telegram_handler on every user message."""
    global _last_user_message_ts
    _last_user_message_ts = time.time()


def is_user_active() -> bool:
    """True if user messaged within last 2 minutes (MLX is single-threaded)."""
    return (time.time() - _last_user_message_ts) < 120


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

    # HIGH-priority emails from last 24h
    try:
        high_emails = db.execute(
            "SELECT summary, sender FROM processed_emails "
            "WHERE classification = 'HIGH' AND processed_at > datetime('now', '-1 day') "
            "ORDER BY processed_at DESC LIMIT 5"
        ).fetchall()
        if high_emails:
            parts.append("HIGH-priority emails needing attention:")
            for e in high_emails:
                parts.append(f"  - {e[0]} (from: {e[1]})")
    except Exception:
        pass

    # Pending fact proposals from extraction pipeline
    try:
        staged = pending_staging(limit=5)
        if staged:
            parts.append("Pending fact proposals (ask user to confirm/deny):")
            for s in staged:
                parts.append(f"  - [{s['fact_type']}] {s['subject']}.{s['key']} = {s['value']} (conf: {s['confidence']:.1f})")
    except Exception:
        pass

    return "\n".join(parts)


def _heartbeat_tick():
    """One heartbeat cycle: build context, ask LLM, send if needed."""
    import re
    import asyncio

    heartbeat_md = _read_heartbeat_md()
    if not heartbeat_md:
        return

    # Force fresh calendar data (cache is 5-min TTL, heartbeat ticks every 30min)
    full_sync()

    # ── Email sync + classify ────────────────────────────────────
    high_alerts = []
    if not is_user_active():
        try:
            new_emails = get_unprocessed_emails(hours=24)
            if new_emails:
                print(f"  [heartbeat] classifying {len(new_emails)} new emails...")
                classified = classify_emails(new_emails)
                for item in classified:
                    context_dump_id = None
                    cls = item["classification"]

                    # HIGH/LOW → store in context_dumps
                    if cls in ("HIGH", "LOW"):
                        context_dump_id = store_context_dump(
                            trace_id=f"email-{item['message_id'][:8]}",
                            content=f"[{cls}] {item['summary']}",
                            source="email",
                        )

                    # Log all in processed_emails
                    db.execute(
                        "INSERT OR IGNORE INTO processed_emails "
                        "(message_id, subject, sender, account_name, classification, summary, context_dump_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (item["message_id"], item["subject"], item["sender"],
                         item.get("account", ""), cls, item["summary"], context_dump_id),
                    )

                    if cls == "HIGH":
                        high_alerts.append(item)

                db.commit()
                print(f"  [heartbeat] processed {len(classified)} emails "
                      f"({len(high_alerts)} HIGH)")
        except Exception as e:
            print(f"  [heartbeat] email sync error: {e}")
    else:
        print("  [heartbeat] user active, deferring email classification")

    # ── Notes sync ───────────────────────────────────────────────
    if not is_user_active():
        try:
            new_notes = ingest_notes(modified_since_days=60)
            if new_notes:
                print(f"  [heartbeat] ingested {new_notes} new/updated notes")
        except Exception as e:
            print(f"  [heartbeat] notes sync error: {e}")

    # ── Send immediate HIGH email alerts ─────────────────────────
    if high_alerts and _send_message_fn:
        lines = ["📧 <b>Emails needing attention:</b>"]
        for e in high_alerts:
            lines.append(f"• {e['summary']} <i>(from: {e['sender']})</i>")
        alert_text = "\n".join(lines)
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_send_message_fn(alert_text))
            loop.close()
        except Exception as e:
            print(f"  [heartbeat] email alert send error: {e}")

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
        # Handle list-type content from MLX/OpenAI API
        if isinstance(response.content, list):
            text_parts = [
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in response.content
            ]
            response.content = "".join(text_parts)
        text = response.content or ""
        # Strip <think> tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        if not text or SKIP_TOKEN in text:
            print(f"  [heartbeat] {datetime.now().strftime('%H:%M')} — nothing to report")
            return

        if _send_message_fn:
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
