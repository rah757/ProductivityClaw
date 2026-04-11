# CLAUDE.md

Local-first AI productivity agent. Python + LangGraph + MLX (Qwen 3.5 35B-A3B) + Telegram + SQLite.
Runs entirely on macOS Apple Silicon. No cloud APIs, no data leaves the machine.

## Rules

- **NEVER** commit, push, or add co-author tags. The user does this manually.
- **No internet** in this repo. No web search, no duckduckgo, no external API calls.
- MLX is **single-threaded** — the priority lock in `briefing.py` ensures chat > heartbeat.

## Architecture

```
Telegram message
  → agent/bot/telegram_handler.py (streaming via streaming.py)
  → agent/core/graph_agent.py (LangGraph state machine)
  → agent/core/skills/{name}/execute.py (tool execution)
  → response back to Telegram
```

- **Prompt assembly** (`agent/core/prompts.py`): SOUL.md + hardcoded RULES + CONTEXT.md
- **Skills** are auto-discovered from `agent/core/skills/{name}/manifest.json` + `execute.py`
- **Write actions** (create_event, move_event) return `PENDING_ACTION:{id}|{description}` — user confirms via Telegram inline buttons before execution
- **trace_id** (8-char UUID) links every conversation, action, and memory entry

## Key Directories

```
agent/core/           LangGraph state machine, prompts, skill registry, SOUL.md, CONTEXT.md
agent/bot/            Telegram handlers, streaming (tiered message editing), feedback buttons
agent/memory/         SQLite + FTS5 (context_store, conversation log, pending_actions)
agent/integrations/   Apple Calendar (EventKit), Mail, Notes (ScriptingBridge) — all native, zero creds
agent/scheduler/      Heartbeat — 30min proactive loop (briefing, email sync, notes sync)
agent/eval/           Deterministic tests (32) + LLM-as-judge quality metrics (14)
agent/core/skills/    calendar, create_event, move_event, store_context, update_profile, get_emails
```

## Config

All env vars loaded in `agent/config.py` from `.env`:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`
- `MLX_MODEL` (default: `mlx-community/Qwen3.5-35B-A3B-4bit`)
- `MLX_BASE_URL` (default: `http://localhost:8000/v1`)
- `DB_PATH` (default: `data/db/claw.db`)

## Testing

```bash
# Deterministic (no LLM needed) — should always be 47 pass
pytest agent/eval/test_suite.py agent/eval/test_write_tools.py -m "not llm and not deepeval" -v

# LLM-as-judge (needs MLX server at localhost:8000)
python -m pytest agent/eval/test_deepeval.py -m deepeval -v -s

# All deterministic + judge
python agent/eval/run_eval.py
```

## Qwen Quirks

- Returns **empty content** ~30% of the time. Always retry (see `_judge()` in test_deepeval.py).
- For JSON output, prepend `/no_think` to the prompt to suppress `<think>` tags.
- Strip think tags from all responses: `re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)`
- Retry with **escalating temperature** (0.0 → 0.1 → 0.3 → 0.5 → 0.7) to break empty-response loops.
- ScriptingBridge (Mail/Notes) needs **Automation permission** in System Settings > Privacy & Security.

## Common Patterns

**Add a new skill:**
1. Create `agent/core/skills/{name}/manifest.json` (name, description, parameters)
2. Create `agent/core/skills/{name}/execute.py` with the execution function
3. Registry auto-discovers it — no wiring needed

**Add a new integration:**
1. Create `agent/integrations/{name}.py`
2. Hook into heartbeat sync in `agent/scheduler/briefing.py`
3. Store data via `context_store.store_context_dump(trace_id, content, source="{name}")`

**Store user data:** `context_store.store_context_dump(trace_id, content, source="telegram|email|notes")`
**Search user data:** `context_store.search_context_dumps(query, limit=5)` — FTS5 BM25 ranked

**LLM call pattern:**
```python
from langchain_openai import ChatOpenAI
from agent.config import MLX_MODEL, MLX_BASE_URL

llm = ChatOpenAI(base_url=MLX_BASE_URL, api_key="not-needed", model=MLX_MODEL, temperature=0.0)
```
