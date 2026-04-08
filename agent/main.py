import time
import asyncio
import threading
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import Conflict
from agent.config import TELEGRAM_TOKEN, ALLOWED_USERS, MLX_MODEL, DB_PATH
from agent.bot.telegram_handler import handle_message, handle_feedback, handle_sync, handle_noop, handle_write_confirm, _md_to_tg_html
from agent.integrations.apple_calendar import request_permissions, full_sync
from agent.scheduler.briefing import start_heartbeat, set_send_fn

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
    print(f"Model: {MLX_MODEL}")
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

    async def on_error(_update: Update, context: ContextTypes.DEFAULT_TYPE):
        err = context.error
        if isinstance(err, Conflict):
            print("  [bot] Conflict: Another bot instance is polling. Stop other instances (e.g. another terminal) and the updater will retry.")
            return
        raise err

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("sync", handle_sync))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_feedback, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(handle_write_confirm, pattern=r"^writeconfirm:"))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^noop$"))

    # Start heartbeat inside post_init so we have the running event loop
    async def _post_init(application):
        loop = asyncio.get_running_loop()

        async def _send(text: str):
            bot = application.bot
            html_text = _md_to_tg_html(f"🫀 {text}")
            for user_id in ALLOWED_USERS:
                await bot.send_message(chat_id=user_id, text=html_text, parse_mode="HTML")
                break

        def _sync_send(text: str):
            future = asyncio.run_coroutine_threadsafe(_send(text), loop)
            future.result(timeout=15)

        set_send_fn(_sync_send)
        start_heartbeat()

    app.post_init = _post_init

    print("Bot is running. Send a message on Telegram.")
    print("  (If you see 'Conflict: terminated by other getUpdates', stop any other bot instance—only one can poll at a time.)")
    app.run_polling()

if __name__ == "__main__":
    main()
