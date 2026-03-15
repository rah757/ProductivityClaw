import json
import uuid
import time
import asyncio
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from agent.config import ALLOWED_USERS, OLLAMA_MODEL
from agent.memory.conversation_log import log_message, get_recent_conversations
from agent.memory.action_log import log_action, update_feedback
from agent.memory.pending_actions import get_pending_action, resolve_pending_action
from agent.memory.agent_created_events import register_agent_event
from agent.integrations.apple_calendar import full_sync, create_event, move_event

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

    recent = get_recent_conversations(limit=4)

    await update.message.chat.send_action("typing")
    print(f"  [{trace_id}] Received message, routing to LangGraph...")

    try:
        from agent.core.graph_agent import chat_with_llm as graph_chat
        response_text, latency_ms, pending_action_id = graph_chat(user_text, recent, trace_id=trace_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
        response_text = f"Error talking to LangGraph: {e}"
        latency_ms = 0
        pending_action_id = None

    # Only log assistant response to conversation history if it's a normal reply.
    # Pending-action responses ("please confirm") poison future context --
    # the LLM sees "I created X" and copies the pattern instead of calling tools.
    if not pending_action_id:
        log_message(trace_id, "telegram", "assistant", response_text, {
            "model": OLLAMA_MODEL,
            "latency_ms": latency_ms,
        })

    log_action(trace_id, "chat_response", {
        "latency_ms": latency_ms,
        "model": OLLAMA_MODEL,
    })

    if pending_action_id:
        action = get_pending_action(pending_action_id)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data=f"writeconfirm:{pending_action_id}:approve"),
            InlineKeyboardButton("❌ Cancel",  callback_data=f"writeconfirm:{pending_action_id}:cancel"),
        ]])
        body = f"{response_text}\n\n_{action['description']}_" if action else response_text
        await update.message.reply_text(body, reply_markup=keyboard, parse_mode="Markdown")
    else:
        feedback_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍", callback_data=f"feedback:up:{trace_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback:down:{trace_id}"),
        ]])
        await update.message.reply_text(response_text, reply_markup=feedback_keyboard)

    print(f"[{trace_id}] llm:{latency_ms}ms | User: {user_text[:50]} | Agent: {response_text[:50]}")

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


async def handle_write_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ✅ Confirm / ❌ Cancel buttons for write actions."""
    query = update.callback_query
    await query.answer()

    # callback_data format: "writeconfirm:{action_id}:{decision}"
    _, action_id, decision = query.data.split(":", 2)

    action = get_pending_action(action_id)
    if not action or action["status"] != "pending":
        await query.message.reply_text("Already resolved.")
        return

    if decision == "approve":
        payload = json.loads(action["payload"])
        action_type = action["action_type"]
        try:
            if action_type == "create_event":
                eid = create_event(**payload)
                register_agent_event(eid, payload["title"], action["trace_id"])
                msg = f"Done -- created '{payload['title']}' ✓"
            elif action_type == "move_event":
                move_event(
                    event_identifier=payload["event_identifier"],
                    new_date_str=payload["new_date_str"],
                    new_start_time=payload["new_start_time"],
                    new_end_time=payload["new_end_time"],
                )
                msg = f"Done -- moved '{payload['event_title']}' ✓"
            else:
                msg = f"Unknown action type: {action_type}"
            # Only mark confirmed after a successful write
            resolve_pending_action(action_id, "confirmed")
            # Refresh cache so next calendar query is accurate
            threading.Thread(target=full_sync, daemon=True).start()
        except Exception as e:
            msg = f"Error: {e}"
            resolve_pending_action(action_id, "failed")
            print(f"  [write_confirm] ERROR: {e}")
    else:
        resolve_pending_action(action_id, "cancelled")
        msg = "Cancelled."

    # Log the real outcome so future context is accurate
    log_message(action["trace_id"], "telegram", "assistant", msg, {
        "action_id": action_id,
        "decision": decision,
    })

    # Replace inline buttons with a simple status label
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton(msg, callback_data="noop")
    ]]))
    await query.message.reply_text(msg)
    print(f"  [write_confirm] action={action_id} decision={decision}: {msg}")

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
