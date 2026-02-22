"""Configuration loaded from environment variables."""

import os


# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Google Calendar
GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CALENDAR_CREDENTIALS_PATH", "./data/credentials/google_oauth.json"
)
GOOGLE_CALENDAR_TOKEN_PATH = os.getenv(
    "GOOGLE_CALENDAR_TOKEN_PATH", "./data/credentials/google_token.json"
)

# LLM
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b-instruct-q5_K_M")

# Agent
BRIEFING_TIME = os.getenv("BRIEFING_TIME", "08:00")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_PROACTIVE_MESSAGES_PER_DAY = int(
    os.getenv("MAX_PROACTIVE_MESSAGES_PER_DAY", "5")
)

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/db/productivityclaw.db")

# Optional: Cloud LLM for benchmarking
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BENCHMARK_ENABLED = os.getenv("BENCHMARK_ENABLED", "false").lower() == "true"
