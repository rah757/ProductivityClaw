"""
ProductivityClaw Prototype
Single-file MVP: Telegram bot + Ollama (Qwen 2.5 14B) + iCloud Calendar + SQLite logging

Run: python prototype.py
Requires: .env with TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS, ICLOUD_USERNAME, ICLOUD_APP_PASSWORD
"""

import os
import sqlite3
import json
import uuid
import time
import asyncio
import subprocess
import threading
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
import ollama
import caldav
import vobject

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid.strip()) for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()]
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
DB_PATH = os.getenv("DB_PATH", "data/db/claw.db")
ICLOUD_USERNAME = os.getenv("ICLOUD_USERNAME")
ICLOUD_APP_PASSWORD = os.getenv("ICLOUD_APP_PASSWORD")

SYSTEM_PROMPT = """You are ProductivityClaw, a local-first AI productivity agent.
You help the user manage their time, tasks, and priorities.
Be concise and actionable. No fluff.

You have access to the user's real calendar data and reminders, which will be provided below.
When the user asks about their schedule, use the ACTUAL calendar data provided — do not make up events.
If no calendar data is provided or it's empty, say you don't see any events for that period.

If the user dumps context (tasks, reminders, thoughts), acknowledge and confirm storage.
If the user asks a question, answer directly.
Always reference specific event names, times, and calendars when discussing the schedule."""

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSON
        );
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action_type TEXT NOT NULL,
            user_feedback TEXT,
            metadata JSON
        );
    """)
    db.commit()
    return db

def log_message(db, trace_id, source, role, content, metadata=None):
    db.execute(
        "INSERT INTO conversations (trace_id, source, role, content, metadata) VALUES (?, ?, ?, ?, ?)",
        (trace_id, source, role, content, json.dumps(metadata) if metadata else None)
    )
    db.commit()

def log_action(db, trace_id, action_type, metadata=None):
    db.execute(
        "INSERT INTO actions (trace_id, action_type, metadata) VALUES (?, ?, ?)",
        (trace_id, action_type, json.dumps(metadata) if metadata else None)
    )
    db.commit()

def update_feedback(db, trace_id, feedback):
    db.execute(
        "UPDATE actions SET user_feedback = ? WHERE trace_id = ? AND user_feedback IS NULL",
        (feedback, trace_id)
    )
    db.commit()

def get_recent_conversations(db, limit=10):
    cursor = db.execute(
        "SELECT role, content, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    rows.reverse()
    return rows

# ─────────────────────────────────────────────
# iCloud Calendar
# ─────────────────────────────────────────────
_calendar_cache = {"events": None, "timestamp": 0}
_reminders_cache = {"reminders": [], "timestamp": 0}
CACHE_TTL_SECONDS = 300  # 5 minutes
REMINDERS_REFRESH_INTERVAL = 600  # 10 minutes

def get_caldav_client():
    """Connect to iCloud CalDAV."""
    return caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=ICLOUD_USERNAME,
        password=ICLOUD_APP_PASSWORD,
    )

def _fetch_all_calendar_data():
    """Single connection: fetch events + reminders together. Caches for 5 min."""
    now = time.time()
    if _calendar_cache["timestamp"] > 0 and (now - _calendar_cache["timestamp"]) < CACHE_TTL_SECONDS:
        age = int(now - _calendar_cache["timestamp"])
        print(f"  [cache hit] ({age}s old)")
        return

    start_date = datetime.now() - timedelta(days=7)
    end_date = datetime.now() + timedelta(days=14)

    try:
        t_connect = time.time()
        client = get_caldav_client()
        principal = client.principal()
        calendars = principal.calendars()
        print(f"  [connect] {(time.time() - t_connect) * 1000:.0f}ms | {len(calendars)} calendars")

        all_events = []
        all_reminders = []

        for cal in calendars:
            # Events
            try:
                t_search = time.time()
                results = cal.date_search(start=start_date, end=end_date, expand=True)
                print(f"  [search] {cal.name}: {(time.time() - t_search) * 1000:.0f}ms | {len(results)} events")
                for event in results:
                    try:
                        vcal = vobject.readOne(event.data)
                        vevent = vcal.vevent

                        summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else "No title"
                        dtstart = vevent.dtstart.value
                        dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else None
                        location = str(vevent.location.value) if hasattr(vevent, 'location') else None
                        description = str(vevent.description.value) if hasattr(vevent, 'description') else None

                        if isinstance(dtstart, datetime):
                            start_str = dtstart.strftime("%I:%M %p")
                            end_str = dtend.strftime("%I:%M %p") if dtend else "?"
                            time_str = f"{start_str} - {end_str}"
                            date_str = dtstart.strftime("%Y-%m-%d")
                        else:
                            time_str = "All day"
                            date_str = str(dtstart)

                        all_events.append({
                            "title": summary,
                            "time": time_str,
                            "date": date_str,
                            "calendar": cal.name,
                            "location": location,
                            "description": description,
                        })
                    except Exception as e:
                        print(f"  Error parsing event: {e}")
                        continue
            except Exception as e:
                print(f"  Error reading calendar {cal.name}: {e}")
                continue

        all_events.sort(key=lambda e: e["date"] + e["time"])
        _calendar_cache["events"] = all_events
        _calendar_cache["timestamp"] = time.time()

    except Exception as e:
        print(f"Calendar error: {e}")
        _calendar_cache["events"] = []
        _calendar_cache["timestamp"] = time.time()

def fetch_all_events():
    """Returns cached events (fetches if stale)."""
    _fetch_all_calendar_data()
    return _calendar_cache["events"] or []

# ─────────────────────────────────────────────
# Reminders (via AppleScript — local, no CalDAV)
# ─────────────────────────────────────────────
APPLESCRIPT_REMINDERS = '''
tell application "Reminders"
    set output to ""
    repeat with r in (every reminder whose completed is false)
        set n to name of r
        set d to ""
        try
            set d to due date of r as string
        end try
        set l to name of container of r
        set output to output & n & " | " & d & " | " & l & linefeed
    end repeat
    return output
end tell
'''

def _fetch_reminders_applescript():
    """Fetch reminders via osascript. Updates cache in-place. No timeout — let it run."""
    try:
        t0 = time.time()
        result = subprocess.run(
            ["osascript", "-e", APPLESCRIPT_REMINDERS],
            capture_output=True, text=True,
        )
        elapsed = int((time.time() - t0) * 1000)

        if result.returncode != 0:
            print(f"  [reminders] AppleScript error: {result.stderr.strip()}")
            return

        reminders = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(" | ")]
            if len(parts) >= 3:
                reminders.append({
                    "title": parts[0],
                    "due": parts[1] if parts[1] else None,
                    "list": parts[2],
                })
            elif len(parts) >= 1:
                reminders.append({"title": parts[0], "due": None, "list": "Unknown"})

        _reminders_cache["reminders"] = reminders
        _reminders_cache["timestamp"] = time.time()
        print(f"  [reminders] {elapsed}ms | {len(reminders)} reminders")

    except Exception as e:
        print(f"  [reminders] error: {e}")

def _full_sync():
    """Full sync: calendar + reminders. Runs in background thread."""
    print("  [sync] starting full sync...")
    t0 = time.time()
    _calendar_cache["timestamp"] = 0  # force calendar re-fetch
    _fetch_all_calendar_data()
    _fetch_reminders_applescript()
    print(f"  [sync] done in {(time.time() - t0) * 1000:.0f}ms | "
          f"{len(_calendar_cache['events'] or [])} events, "
          f"{len(_reminders_cache['reminders'])} reminders")

def start_sync():
    """Startup: full sync in background thread so bot starts immediately."""
    threading.Thread(target=_full_sync, daemon=True).start()

def fetch_all_reminders():
    """Returns cached reminders. Never blocks — always serves from cache."""
    return _reminders_cache["reminders"]

def filter_events(all_events, start_str, end_str):
    """Filter pre-fetched events by date range (YYYY-MM-DD strings)."""
    return [e for e in all_events if start_str <= e["date"] < end_str]

def build_calendar_context():
    """Build a text summary of the user's calendar for the LLM."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_str = today_start.strftime("%Y-%m-%d")
    tomorrow_str = (today_start + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after_str = (today_start + timedelta(days=2)).strftime("%Y-%m-%d")
    week_end_str = (today_start + timedelta(days=7)).strftime("%Y-%m-%d")
    past_week_str = (today_start - timedelta(days=7)).strftime("%Y-%m-%d")

    all_events = fetch_all_events()

    sections = []

    # Recent past (last 7 days)
    past_events = filter_events(all_events, past_week_str, today_str)
    if past_events:
        lines = ["RECENT (last 7 days):"]
        for e in past_events:
            line = f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]"
            lines.append(line)
        sections.append("\n".join(lines))

    # Today
    today_events = filter_events(all_events, today_str, tomorrow_str)
    if today_events:
        lines = [f"TODAY ({now.strftime('%A, %B %d')}):"]
        for e in today_events:
            line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
            if e['location']:
                line += f" @ {e['location']}"
            lines.append(line)
        sections.append("\n".join(lines))
    else:
        sections.append(f"TODAY ({now.strftime('%A, %B %d')}): No events")

    # Tomorrow
    tomorrow_events = filter_events(all_events, tomorrow_str, day_after_str)
    if tomorrow_events:
        tomorrow_date = (now + timedelta(days=1)).strftime('%A, %B %d')
        lines = [f"TOMORROW ({tomorrow_date}):"]
        for e in tomorrow_events:
            line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
            if e['location']:
                line += f" @ {e['location']}"
            lines.append(line)
        sections.append("\n".join(lines))

    # Rest of week
    rest_events = filter_events(all_events, day_after_str, week_end_str)
    if rest_events:
        lines = ["THIS WEEK:"]
        for e in rest_events:
            line = f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]"
            lines.append(line)
        sections.append("\n".join(lines))

    # Reminders
    reminders = fetch_all_reminders()
    if reminders:
        lines = ["REMINDERS:"]
        for r in reminders:
            line = f"  - {r['title']} [{r['list']}]"
            if r['due']:
                line += f" (due: {r['due']})"
            lines.append(line)
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "No calendar data available."

# ─────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────
def chat_with_llm(user_message, recent_context, calendar_context):
    """Send message to Ollama with calendar + conversation context."""
    full_system = f"""{SYSTEM_PROMPT}

--- CURRENT CALENDAR & REMINDERS ---
{calendar_context}
--- END CALENDAR ---

Current time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"""

    messages = [{"role": "system", "content": full_system}]

    for role, content, ts in recent_context:
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    start = datetime.now()
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    latency_ms = int((datetime.now() - start).total_seconds() * 1000)

    return response["message"]["content"], latency_ms

# ─────────────────────────────────────────────
# Telegram Bot
# ─────────────────────────────────────────────
db = init_db()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Telegram messages."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    user_text = update.message.text
    trace_id = str(uuid.uuid4())[:8]

    log_message(db, trace_id, "telegram", "user", user_text, {
        "chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id,
    })

    recent = get_recent_conversations(db, limit=10)

    await update.message.chat.send_action("typing")

    # Fetch calendar
    try:
        t_cal = time.time()
        calendar_context = build_calendar_context()
        cal_ms = int((time.time() - t_cal) * 1000)
        print(f"  [{trace_id}] [calendar total] {cal_ms}ms")
    except Exception as e:
        calendar_context = f"Calendar unavailable: {e}"
        cal_ms = 0
        print(f"Calendar fetch error: {e}")

    # Get LLM response
    try:
        response_text, latency_ms = chat_with_llm(user_text, recent, calendar_context)
    except Exception as e:
        response_text = f"Error talking to LLM: {e}"
        latency_ms = 0

    log_message(db, trace_id, "telegram", "assistant", response_text, {
        "model": OLLAMA_MODEL,
        "latency_ms": latency_ms,
        "calendar_events_count": calendar_context.count("- "),
    })

    log_action(db, trace_id, "chat_response", {
        "latency_ms": latency_ms,
        "model": OLLAMA_MODEL,
    })

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data=f"feedback:up:{trace_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback:down:{trace_id}"),
        ]
    ])
    await update.message.reply_text(response_text, reply_markup=keyboard)

    print(f"[{trace_id}] cal:{cal_ms}ms llm:{latency_ms}ms total:{cal_ms + latency_ms}ms | User: {user_text[:50]}... | Agent: {response_text[:50]}...")

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle thumbs up/down button presses."""
    query = update.callback_query
    await query.answer()

    _, direction, trace_id = query.data.split(":")
    feedback = "thumbs_up" if direction == "up" else "thumbs_down"
    update_feedback(db, trace_id, feedback)

    selected = "👍 ✓" if direction == "up" else "👎 ✓"
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(selected, callback_data="noop")
        ]])
    )

async def handle_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sync command — full re-fetch of calendar + reminders."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    await update.message.reply_text("Syncing calendar + reminders...")
    threading.Thread(target=_full_sync, daemon=True).start()
    # Wait a bit for sync, then report
    await asyncio.sleep(20)
    events = _calendar_cache["events"] or []
    reminders = _reminders_cache["reminders"]
    await update.message.reply_text(
        f"Synced ✓ ({len(events)} events, {len(reminders)} reminders)"
    )

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle already-clicked feedback buttons."""
    await update.callback_query.answer()

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN in .env")
        return
    if not ALLOWED_USERS:
        print("ERROR: Set TELEGRAM_ALLOWED_USER_IDS in .env")
        return
    if not ICLOUD_USERNAME or not ICLOUD_APP_PASSWORD:
        print("WARNING: iCloud credentials not set — calendar features disabled")

    print(f"Starting ProductivityClaw prototype...")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Allowed users: {ALLOWED_USERS}")
    print(f"Database: {DB_PATH}")
    print(f"iCloud: {ICLOUD_USERNAME}")

    # Test calendar connection on startup
    try:
        client = get_caldav_client()
        principal = client.principal()
        cals = principal.calendars()
        print(f"Connected to iCloud — {len(cals)} calendars found: {[c.name for c in cals]}")
    except Exception as e:
        print(f"WARNING: Calendar connection failed: {e}")

    # Full sync on startup (background — bot starts immediately)
    print("Starting initial sync...")
    start_sync()

    # Cron sync at 12pm and 12am
    def _cron_sync_loop():
        while True:
            now = datetime.now()
            next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            if next_noon <= now:
                next_noon += timedelta(days=1)
            next_sync = min(next_noon, next_midnight)
            wait_seconds = (next_sync - now).total_seconds()
            print(f"  [cron] next sync at {next_sync.strftime('%I:%M %p')} ({int(wait_seconds)}s)")
            time.sleep(wait_seconds)
            _full_sync()
    threading.Thread(target=_cron_sync_loop, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("sync", handle_sync))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_feedback, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^noop$"))

    print("Bot is running. Send a message on Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()