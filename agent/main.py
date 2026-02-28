import time
import threading
from datetime import datetime, timedelta

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from agent.config import TELEGRAM_TOKEN, ALLOWED_USERS, OLLAMA_MODEL, DB_PATH
from agent.bot.telegram_handler import handle_message, handle_feedback, handle_sync, handle_noop
from agent.integrations.apple_calendar import request_permissions, full_sync

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
        full_sync()

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

    # Request EventKit permissions on startup
    if request_permissions():
        # Give EventKit a moment to warm up its cache from the macOS daemon.
        time.sleep(2)

    # Full sync on startup (background — bot starts immediately)
    print("Starting initial sync...")
    threading.Thread(target=full_sync, daemon=True).start()

    # Cron sync at 12pm and 12am
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
