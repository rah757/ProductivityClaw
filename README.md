# 🦞 ProductivityClaw

A local-first AI agent that ingests your digital life — calendar, notes, messages, notifications — builds persistent context, and proactively tells you what to focus on.

Not "here's your calendar." More like: **"Based on your deadlines, habits, and priorities — here's what you should do right now."**

## Why This Exists

Every productivity tool shows you *what* you have. None of them tell you *what matters*. ProductivityClaw sits on top of your existing tools, learns your patterns over time, and surfaces what's actually important — without you asking.

## Architecture

<img width="561" height="687" alt="image" src="https://github.com/user-attachments/assets/be3dc207-21d4-43ab-b739-cb9c0a518100" />


Everything runs locally in Docker on a single machine. No cloud dependency. Your data never leaves your device.

## Current Status — Phase 1: Prove the Loop

Building the core agent loop end-to-end:

- [x] Project architecture and technical design
- [ ] Docker stack (Ollama + agent + SQLite)
- [ ] Telegram bot — receive messages, send responses
- [ ] Google Calendar read-only integration
- [ ] Automated daily morning briefing
- [ ] Context dump ingestion (send the agent tasks, reminders, thoughts — it stores everything)
- [ ] Conversation logging with full data path tracing
- [ ] Thumbs up/down feedback on every response
- [ ] DeepEval test suite (tool call accuracy, response factuality, latency)

**Phase 1 target:** Use it every morning for a week. The briefing is accurate, the calendar answers are correct, and there's eval data proving it.

## Privacy Model

- Agent runs 100% locally — API keys, data, memory all on your machine
- Read-only by default for all integrations
- Write actions require explicit confirmation (human-in-the-loop)
- Local LLM (Qwen 2.5 14B) keeps all data on-device
- Scoped permissions per integration — no blanket system access

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python | Ecosystem + LangGraph support |
| Orchestration | LangGraph | Stateful workflows, cycles, retry logic |
| LLM | Qwen 2.5 14B (Ollama) | Best local model for tool calling + structured output |
| Chat Interface | Telegram Bot API | Free, instant setup, runs on phone |
| Memory | SQLite | Local-first, zero config, sufficient for personal scale |
| Eval | DeepEval | Real framework from day one, grows with the project |
| Deployment | Docker Compose | Reproducible, kill-switch friendly, open-source ready |

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **1 — Prove the Loop** | Telegram + Calendar + Briefing + Eval | 🔨 In Progress |
| 2 — Memory + Actions | Fact extraction, calendar writes, WhatsApp ingestion | Planned |
| 3 — Intelligence | Proactive suggestions, email/Slack read, vector store | Planned |
| 4 — Polish | Siri Shortcuts, vision (Qwen-VL), HomeKit automation, eval dashboard | Planned |
| 5 — Ecosystem | Skill import pipeline, multi-agent, OSS community | Future |

## Setup

```bash
git clone https://github.com/rah757/ProductivityClaw.git
cd ProductivityClaw
cp .env.example .env  # Add your Telegram bot token + Google Calendar credentials
docker compose up
```

> Requires Docker and an Apple Silicon or x86-64 machine with 16GB+ RAM.

## License

MIT
