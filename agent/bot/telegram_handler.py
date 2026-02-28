import uuid
import time
import asyncio
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from agent.config import ALLOWED_USERS, OLLAMA_MODEL
from agent.memory.conversation_log import log_message, get_recent_conversations
from agent.memory.action_log import log_action, update_feedback
from agent.memory.context_builder import build_calendar_context
from agent.core.agent import chat_with_llm
from agent.integrations.apple_calendar import full_sync

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Telegram messages."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    user_text = update.message.text
    trace_id = str(uuid.uuid4())[:8]

    log_message(trace_id, "telegram", "user", user_text, {
        "chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id,
    })

    recent = get_recent_conversations(limit=10)

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

    log_message(trace_id, "telegram", "assistant", response_text, {
        "model": OLLAMA_MODEL,
        "latency_ms": latency_ms,
        "calendar_events_count": calendar_context.count("- "),
    })

    log_action(trace_id, "chat_response", {
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

    data = query.data.split(":")
    feedback = data[1]
    trace_id = data[2]

    update_feedback(trace_id, feedback)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'👍' if feedback == 'up' else '👎'} Recorded", callback_data="noop")]
    ])
    await query.edit_message_reply_markup(reply_markup=keyboard)
    print(f"  [{trace_id}] Feedback: {feedback}")

async def handle_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sync command — full re-fetch of calendar + reminders."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    await update.message.reply_text("Syncing calendar + reminders...")
    threading.Thread(target=full_sync, daemon=True).start()
    # Wait a bit for sync, then report
    await asyncio.sleep(2)
    from agent.integrations.apple_calendar import fetch_all_events, fetch_all_reminders
    events = fetch_all_events()
    reminders = fetch_all_reminders()
    await update.message.reply_text(
        f"Synced ✓ ({len(events)} events, {len(reminders)} reminders)"
    )

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle already-clicked feedback buttons."""
    await update.callback_query.answer()
