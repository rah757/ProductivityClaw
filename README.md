# ProductivityClaw

A local-first AI agent that ingests your digital life — calendar, notes, messages, notifications — builds persistent context, and proactively tells you what to focus on.

Not "here's your calendar." More like: **"Based on your deadlines, habits, and priorities — here's what you should do right now."**

## Why This Exists

Every productivity tool shows you *what* you have. None of them tell you *what matters*. ProductivityClaw sits on top of your existing tools, learns your patterns over time, and surfaces what's actually important — without you asking.

## Architecture Decisions

### Why Local LLM
All data stays on your device. Calendar events, personal notes, habits, routines — none of it leaves your machine. No cloud API calls, no data sharing, no latency dependency.

### Why MLX over Ollama
MLX uses ~50% less RAM than Ollama on Apple Silicon. The main reason: Qwen's 150K+ token vocabulary creates a 3-4GB embedding table in FP16. Ollama keeps this full-precision; MLX quantizes it down to ~1GB. MLX also exploits Apple Silicon's Unified Memory Architecture (no CPU↔GPU staging buffers) and uses custom Metal shaders. The codebase connects via OpenAI-compatible API (`ChatOpenAI`), so switching to Ollama for non-Mac deployment is a config change — same endpoint format.

### Why Qwen 3.5 35B-A3B
Mixture-of-Experts model: 35B total parameters, but only ~3B active per token (256 experts, 8 active). This gives you large-model quality at small-model speed — 2-4 second responses on a MacBook Pro. `think=False` works correctly (was broken on Qwen 3), keeping latency tight for chat while still available for background reasoning tasks.

### Why LangGraph
Not a simple prompt→response chain. LangGraph provides a stateful agent loop: the LLM can call tools, inspect results, call more tools, and maintain state across the cycle. Pending action state (for write confirmations) lives in the graph, not in fragile string parsing.

### Why SQLite + FTS5
Local-first, zero config, single file. FTS5 gives BM25-ranked full-text search over stored context — no vector database needed at personal scale. Every message, action, and tool call is linked by trace_id for full audit trails.

### Why Apple EventKit (Native)
No Google API keys, no OAuth dance, works offline. Direct access to macOS Calendar via PyObjC. Read-only by default — write actions (create/move events) require explicit user confirmation through Telegram buttons.

### Why Telegram
Free, instant setup, runs on your phone. Rich inline buttons enable the human-in-the-loop confirmation workflow for write actions. No web UI to build or maintain.

## Current Status — Phase 1: Prove the Loop

- [x] Project architecture and technical design
- [x] MLX inference backend (migrated from Ollama)
- [x] Telegram bot — messages, HTML rendering, feedback buttons
- [x] Apple Calendar read-only integration (EventKit)
- [x] Calendar write actions with confirmation (create_event, move_event)
- [x] Context dump ingestion (store_context + FTS5 search)
- [x] Living user profile (update_profile — add/remove/update CONTEXT.md)
- [x] Conversation logging with trace_id linking
- [x] Thumbs up/down feedback on every response
- [x] Heartbeat — proactive briefing system (morning/evening/meeting reminders)
- [ ] DeepEval test suite (tool call accuracy, response factuality, latency)

**Phase 1 target:** Use it every morning for a week. The briefing is accurate, the calendar answers are correct, and there's eval data proving it.

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python | LangGraph ecosystem + PyObjC for macOS |
| Orchestration | LangGraph | Stateful tool-calling loops, pending action state |
| LLM | Qwen 3.5 35B-A3B-4bit | MoE: ~3B active/token, 2-4s responses, local |
| Inference | MLX (mlx_lm.server) | 50% less RAM than Ollama on Apple Silicon |
| Chat Interface | Telegram Bot API | Free, inline buttons for confirmation, runs on phone |
| Memory | SQLite + FTS5 | Local-first, BM25 search, zero config |
| Calendar | Apple EventKit (PyObjC) | Native macOS, no API keys, works offline |
| Email | Apple Mail (ScriptingBridge) | Same native pattern as EventKit, zero credentials |
| Eval | DeepEval | (planned) |

## Skills

| Skill | Type | Description |
|-------|------|-------------|
| `get_calendar_events` | Read | Fetch events by timeframe (today, tomorrow, this_week, etc.) |
| `create_event` | Write | Propose a new calendar event — requires user confirmation |
| `move_event` | Write | Propose rescheduling an event — requires user confirmation |
| `store_context` | Write | Save notes, tasks, reminders to persistent memory with FTS5 indexing |
| `update_profile` | Write | Manage living user profile (preferences, schedule, routines, work) |

Write skills that modify external systems (calendar) use a **pending action workflow**: the LLM proposes the action, the user sees a confirmation button in Telegram, and only an explicit tap executes the write.

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **1 — Prove the Loop** | Telegram + Calendar + Memory + Heartbeat + Eval | Nearly complete |
| 2 — Intelligence | Epoch reasoning loop, email ingestion, MCP integrations, memory organization | Planned |
| 3 — Proactive | Proactive suggestions, pattern recognition, smart reminders | Planned |
| 4 — Polish | Siri Shortcuts, vision, multi-modal, eval dashboard | Future |
| 5 — Ecosystem | Skill import pipeline, multi-agent, OSS community | Future |

## Setup

Requires **macOS with Apple Silicon** and 16GB+ RAM (36GB recommended for Qwen 3.5 35B).

```bash
# Clone
git clone https://github.com/rah757/ProductivityClaw.git
cd ProductivityClaw

# Environment
cp .env.example .env
# Edit .env: add TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS

# Dependencies
pip install -r requirements.txt

# Start MLX model server (separate terminal)
mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit --port 8000

# Run the agent
python -m agent.main
```

## Privacy Model

- Agent runs 100% locally — API keys, data, memory all on your machine
- Local LLM (Qwen 3.5 35B-A3B) keeps all inference on-device
- Read-only by default for all integrations
- Write actions require explicit confirmation (human-in-the-loop via Telegram buttons)
- Scoped permissions per integration — no blanket system access
- SQLite database stays local, no sync

## License

MIT
