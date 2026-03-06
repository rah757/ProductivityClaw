import ollama
from datetime import datetime
from agent.config import OLLAMA_MODEL
from agent.core.prompts import get_system_prompt

def chat_with_llm(user_message, recent_context, calendar_context):
    """Send message to Ollama with calendar + conversation context."""
    # 1. Static system prompt (maximizes KV cache hit rate across turns)
    messages = [{"role": "system", "content": get_system_prompt()}]

    # 2. Historical conversation context
    for role, content, ts in recent_context:
        messages.append({"role": role, "content": content})

    # 3. Volatile context injected right before the latest user message
    volatile_context = f"""[System context updated for this turn]
Current time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}

--- CURRENT CALENDAR & REMINDERS ---
{calendar_context}
--- END CALENDAR ---"""

    messages.append({"role": "system", "content": volatile_context})
    messages.append({"role": "user", "content": user_message})

    start = datetime.now()
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    latency_ms = int((datetime.now() - start).total_seconds() * 1000)

    return response["message"]["content"], latency_ms
