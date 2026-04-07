import json
import re
import uuid
import time
import asyncio
import threading
from html import escape as html_escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from agent.config import ALLOWED_USERS, MLX_MODEL
from agent.memory.extraction import extract_facts_background


def _md_to_tg_html(text: str) -> str:
    """Convert LLM markdown to Telegram-safe HTML."""
    text = html_escape(text)
    # **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # *italic* → <i>italic</i> (but not inside bold tags)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # `code` → <code>code</code>
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text
from agent.memory.conversation_log import log_message, get_recent_conversations
from agent.memory.action_log import log_action, update_feedback
from agent.memory.pending_actions import get_pending_action, resolve_pending_action
from agent.memory.agent_created_events import register_agent_event
from agent.integrations.apple_calendar import full_sync, create_event, move_event

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Telegram messages with streaming response."""
    if update.effective_user.id not in ALLOWED_USERS:
        return

    # Track activity for LLM priority lock (heartbeat defers if user active)
    from agent.scheduler.briefing import record_user_activity
    record_user_activity()

    user_text = update.message.text
    trace_id = str(uuid.uuid4())[:8]

    log_message(trace_id, "telegram", "user", user_text, {
        "chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id,
    })

    recent = get_recent_conversations(limit=4)

    await update.message.chat.send_action("typing")
    print(f"  [{trace_id}] Received message, streaming via LangGraph...")

    t0 = time.time()

    try:
        from agent.core.graph_agent import chat_with_llm_stream, chat_with_llm as graph_chat
        from agent.bot.streaming import stream_to_telegram

        # Collect tokens from the sync generator in a thread
        tokens = []
        pending_action_id = None

        def _run_stream():
            nonlocal pending_action_id
            for token, pid in chat_with_llm_stream(user_text, recent, trace_id=trace_id):
                tokens.append(token)
                if pid is not None:
                    pending_action_id = pid

        # Run generator in thread, stream to Telegram from async context
        import queue

        token_queue = queue.Queue()
        stream_done = threading.Event()

        def _producer():
            nonlocal pending_action_id
            try:
                for token, pid in chat_with_llm_stream(user_text, recent, trace_id=trace_id):
                    token_queue.put(token)
                    if pid is not None:
                        pending_action_id = pid
            except Exception as e:
                token_queue.put(None)  # signal error
                print(f"  [{trace_id}] stream error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                stream_done.set()

        def _token_iter():
            """Sync iterator that reads from the queue until done."""
            while True:
                try:
                    token = token_queue.get(timeout=0.1)
                    if token is None:
                        break
                    yield token
                except queue.Empty:
                    if stream_done.is_set() and token_queue.empty():
                        break

        # Start producer thread
        producer = threading.Thread(target=_producer, daemon=True)
        producer.start()

        # Stream to Telegram
        response_text, stream_msg = await stream_to_telegram(
            chat_id=update.effective_chat.id,
            bot=context.bot,
            token_generator=_token_iter(),
            parse_mode="HTML",
            format_fn=_md_to_tg_html,
        )

        producer.join(timeout=5)
        latency_ms = int((time.time() - t0) * 1000)

        if not response_text:
            response_text = ""

    except Exception as e:
        import traceback
        traceback.print_exc()
        response_text = f"Error: {e}"
        latency_ms = int((time.time() - t0) * 1000)
        pending_action_id = None
        stream_msg = None

    # Log
    if not pending_action_id:
        log_message(trace_id, "telegram", "assistant", response_text, {
            "model": MLX_MODEL,
            "latency_ms": latency_ms,
        })

    log_action(trace_id, "chat_response", {
        "latency_ms": latency_ms,
        "model": MLX_MODEL,
    })

    # Fire fact extraction in background (3s delay, respects priority lock)
    extract_facts_background(user_text, response_text, trace_id=trace_id)

    # Handle pending actions (tool calls that need confirmation)
    if pending_action_id:
        action = get_pending_action(pending_action_id)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data=f"writeconfirm:{pending_action_id}:approve"),
            InlineKeyboardButton("❌ Cancel",  callback_data=f"writeconfirm:{pending_action_id}:cancel"),
        ]])
        desc_html = html_escape(action['description']) if action else ""
        body = f"{_md_to_tg_html(response_text)}\n\n<i>{desc_html}</i>" if action else _md_to_tg_html(response_text)
        if stream_msg:
            # Edit the streamed message to add buttons
            try:
                await stream_msg.edit_text(body or "Done.", reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                await update.message.reply_text(body or "Done.", reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.message.reply_text(body or "Done.", reply_markup=keyboard, parse_mode="HTML")
    else:
        # Add feedback buttons to the streamed message
        feedback_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍", callback_data=f"feedback:up:{trace_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback:down:{trace_id}"),
        ]])
        if stream_msg:
            try:
                formatted = _md_to_tg_html(response_text) if response_text else "Done."
                await stream_msg.edit_text(formatted, reply_markup=feedback_keyboard, parse_mode="HTML")
            except Exception:
                pass  # message already has the text, just couldn't add buttons
        else:
            await update.message.reply_text(
                _md_to_tg_html(response_text) or "Done.",
                reply_markup=feedback_keyboard,
                parse_mode="HTML",
            )

    print(f"[{trace_id}] llm:{latency_ms}ms | User: {user_text[:50]} | Agent: {(response_text or '')[:50]}")

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
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except Exception:
        pass  # already edited (double-tap)
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
