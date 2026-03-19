"""Simple Telegram chat bot using the same local MLX LLM.
No tools, no skills — just conversation with 15-turn history.
Uses TELEGRAM_CHAT_TOKEN (separate bot from ProductivityClaw)."""

import os
import re
import time
import requests
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_CHAT_TOKEN")
if not TOKEN:
    raise ValueError("Set TELEGRAM_CHAT_TOKEN in .env")

MLX_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "mlx-community/Qwen3.5-35B-A3B-4bit"

# Per-chat history: {chat_id: [{"role": ..., "content": ...}]}
histories: dict[int, list[dict]] = {}

SYSTEM = "You are a helpful assistant. Be concise and direct."


def build_messages(chat_id: int, user_msg: str) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]

    history = histories.get(chat_id, [])
    recent = history[-30:]  # 15 pairs max
    msgs.extend(recent)

    msgs.append({"role": "user", "content": user_msg})
    return msgs


def get_reply(chat_id: int, user_msg: str) -> str:
    msgs = build_messages(chat_id, user_msg)

    resp = requests.post(MLX_URL, json={
        "model": MODEL,
        "messages": msgs,
        "temperature": 0.7,
        "max_tokens": 4000,
    }, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    choice = data["choices"][0]["message"]
    content = choice.get("content", "") or ""
    reasoning = choice.get("reasoning", "") or ""

    print(f"  [chat] content_len={len(content)} reasoning_len={len(reasoning)}")

    if content.strip():
        text = content.strip()
    elif reasoning.strip():
        text = reasoning.strip()
    else:
        text = ""

    # Strip think tags if present
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if clean:
        text = clean

    if chat_id not in histories:
        histories[chat_id] = []
    histories[chat_id].append({"role": "user", "content": user_msg})
    histories[chat_id].append({"role": "assistant", "content": text})

    return text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    print(f"  [chat] message from {user.first_name} ({user.id}): {user_text[:50]}")
    await update.message.chat.send_action("typing")

    try:
        t0 = time.time()
        reply = get_reply(chat_id, user_text)
        ms = int((time.time() - t0) * 1000)
        print(f"  [chat] {ms}ms | reply: {reply[:80]}")
        await update.message.reply_text(reply or "...")
    except Exception as e:
        print(f"  [chat] ERROR: {e}")
        await update.message.reply_text(f"Error: {e}")


if __name__ == "__main__":
    print("Chat Bot (Qwen 3.5 · MLX · localhost:8000)")
    print("Send a message on Telegram.\n")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
