"""
ProductivityClaw Prototype
Single-file MVP: Telegram bot + Ollama (Qwen 2.5 14B) + SQLite logging

Run: python prototype.py
Requires: TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS in .env
"""

import os
import asyncio
import sqlite3
import json
import uuid
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import ollama

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid.strip()) for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()]
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
DB_PATH = os.getenv("DB_PATH", "data/db/claw.db")

SYSTEM_PROMPT = """You are ProductivityClaw, a local-first AI productivity agent. 
You help the user manage their time, tasks, and priorities.
Be concise and actionable. No fluff.
If the user dumps context (tasks, reminders, thoughts), acknowledge and confirm storage.
If the user asks a question, answer directly."""

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
    rows.reverse()  # chronological order
    return rows

# ─────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────
def chat_with_llm(user_message, recent_context):
    """Send message to Ollama with recent conversation context."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add recent context
    for role, content, ts in recent_context:
        messages.append({"role": role, "content": content})

    # Add current message
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
    # Security: only respond to allowed users
    if update.effective_user.id not in ALLOWED_USERS:
        return

    user_text = update.message.text
    trace_id = str(uuid.uuid4())[:8]

    # Log incoming message
    log_message(db, trace_id, "telegram", "user", user_text, {
        "chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id,
    })

    # Get recent context
    recent = get_recent_conversations(db, limit=10)

    # Send typing indicator
    await update.message.chat.send_action("typing")

    # Get LLM response
    try:
        response_text, latency_ms = chat_with_llm(user_text, recent)
    except Exception as e:
        response_text = f"Error talking to LLM: {e}"
        latency_ms = 0

    # Log response
    log_message(db, trace_id, "telegram", "assistant", response_text, {
        "model": OLLAMA_MODEL,
        "latency_ms": latency_ms,
    })

    # Log action
    log_action(db, trace_id, "chat_response", {
        "latency_ms": latency_ms,
        "model": OLLAMA_MODEL,
    })

    # Send response with feedback buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data=f"feedback:up:{trace_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback:down:{trace_id}"),
        ]
    ])
    await update.message.reply_text(response_text, reply_markup=keyboard)

    # Print to console for debugging
    print(f"[{trace_id}] {latency_ms}ms | User: {user_text[:50]}... | Agent: {response_text[:50]}...")

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle thumbs up/down button presses."""
    query = update.callback_query
    await query.answer()

    _, direction, trace_id = query.data.split(":")
    feedback = "thumbs_up" if direction == "up" else "thumbs_down"
    update_feedback(db, trace_id, feedback)

    # Update button to show selection
    selected = "👍 ✓" if direction == "up" else "👎 ✓"
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(selected, callback_data="noop")
        ]])
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

    print(f"Starting ProductivityClaw prototype...")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Allowed users: {ALLOWED_USERS}")
    print(f"Database: {DB_PATH}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_feedback, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^noop$"))

    print("Bot is running. Send a message on Telegram.")
    app.run_polling()

if __name__ == "__main__":
    main()