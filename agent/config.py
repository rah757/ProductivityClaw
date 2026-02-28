import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid.strip()) for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()]
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
DB_PATH = os.getenv("DB_PATH", "data/db/claw.db")
