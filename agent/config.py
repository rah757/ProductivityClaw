import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid.strip()) for uid in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()]
DB_PATH = os.getenv("DB_PATH", "data/db/claw.db")

# MLX LLM server
MLX_MODEL = os.getenv("MLX_MODEL", "mlx-community/Qwen3.5-35B-A3B-4bit")
MLX_BASE_URL = os.getenv("MLX_BASE_URL", "http://localhost:8000/v1")
