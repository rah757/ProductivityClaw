# ProductivityClaw — Comprehensive Project Plan
# Internal Reference Document (Not Public)
# Last Updated: February 2026

---

## Table of Contents

1. Project Overview & Decisions
2. Architecture
3. Phase 1 — Prove the Loop
4. Phase 2 — Memory + Write Actions
5. Phase 3 — Intelligence + Proactive Behavior
6. Phase 4 — Polish, Multimodal, Interview-Ready
7. Phase 5 — Open Source Ecosystem
8. Memory Architecture (Deep Dive)
9. Caching Strategy (Deep Dive)
10. Eval Strategy (Deep Dive)
11. Docker & Infrastructure
12. Key Technical Decisions Log

---

## 0. Development Best Practices & CI/CD

### Git Workflow

Branch strategy: `main` is always stable. Feature branches for each piece of work.

```
main (stable, protected)
├── feature/docker-setup
├── feature/telegram-bot
├── feature/calendar-integration
├── feature/agent-core
└── feature/eval-setup
```

Merge via PR even when solo — builds the habit and creates a paper trail.

### Commit Conventions

Use conventional commits. Recruiters and collaborators read commit history.

```
feat: add telegram bot message handler
fix: calendar timezone parsing for CST
test: add deepeval test cases for calendar queries
docs: update README with setup instructions
chore: add .gitignore and .env.example
refactor: extract calendar SDK wrapper into separate module
```

### GitHub Actions CI Pipeline

On every push and PR to `main`:

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r agent/requirements.txt
      - run: pytest agent/tests/ -v

  eval:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r agent/requirements.txt
      - run: python agent/eval/run_eval.py --mock  # runs against mock data, no live APIs

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build --no-cache
```

### Pre-Commit Hooks (Local)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

Setup: `pip install pre-commit && pre-commit install`

### .gitignore (set up early)

```
# Data & secrets
data/
.env
*.db

# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# Eval results (regenerable)
data/eval/results/

# IDE
.vscode/
.idea/

# OS
.DS_Store

# Docker
docker-compose.override.yml
```

### Code Quality Standards

- **Linting:** ruff (replaces flake8 + isort + black — single tool)
- **Formatting:** ruff format (consistent style, zero config)
- **Type hints:** use them on all function signatures (helps LLM code generation too)
- **Docstrings:** Google style on public functions
- **Testing:** pytest for unit tests, DeepEval for agent eval

### What NOT to Overengineer

- No CD (continuous deployment) until Phase 5 — you're deploying locally
- No Kubernetes, Terraform, or infrastructure-as-code
- No monorepo tooling — Docker Compose is your deployment tool
- No code coverage gates — focus on meaningful tests, not coverage %

### Why LangGraph (Not Plain Python)

The agent isn't a simple prompt→response chain. It's a loop: receive message →
decide if tool call needed → call tool → feed result back → maybe call another tool →
generate response. That's a cycle. LangGraph handles cycles natively.

By Phase 3, the agent needs: conditional branching (question vs context dump?),
retry logic (tool call failed), human-in-the-loop (wait for confirmation),
and proactive triggers (cron fires, agent reasons about what to notify).
LangGraph models all of this as a state graph.

The alternative (plain Python agent loop) works for Phase 1 but you'd rebuild
LangGraph's features by Phase 2-3 and lose the ecosystem benefits (LangSmith
tracing, community patterns, interview recognition).

### Why DeepEval (Not Custom Pytest)

DeepEval provides proper eval metrics (faithfulness, hallucination, tool correctness)
with an established vocabulary that interviewers recognize. Custom pytest assertions
work but don't scale and don't give you composable metrics.

Phase 1 uses ~10% of DeepEval's capabilities. That's fine — the framework is there,
test cases accumulate, and there's no migration from a throwaway system later.

Note: DeepEval's LLM-as-judge metrics (faithfulness, hallucination) require an LLM
to evaluate your LLM's output. Phase 1 sticks to deterministic metrics (tool call
correctness, latency, user feedback). LLM-judge metrics added in Phase 2 when
Claude Sonnet is available as benchmark reference.

---

## 1. Project Overview & Decisions

### What Is ProductivityClaw?
A local-first AI agent that fetches everything from your digital life (calendar, notes,
messages, notifications), builds persistent context over time, and proactively infers what
you should focus on.

### Confirmed Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| LLM (primary) | Qwen 2.5 14B via Ollama | Best local model for tool calling + structured output. M3 Max 36GB handles it at ~12-14GB (Q5_K_M). Free, private, no API cost. |
| LLM (benchmark) | Claude Sonnet via API | Benchmark-only — run eval samples through it to measure quality ceiling. Not for production. Costs ~$2-5/month for eval runs. |
| LLM (vision) | Qwen-VL via Ollama | Phase 4 only. On-demand when user sends images. Screenshots→tasks, whiteboard→notes. |
| Cloud API for dev? | No — start local | Avoids debugging model quality + agent logic simultaneously. Qwen 14B is competent for structured tool calling. If quality issues arise, swap to cloud temporarily to isolate whether it's model or agent logic. |
| DeepSeek API? | No | Routes through Chinese servers. Contradicts privacy-first narrative. Interviewers will notice. |
| Orchestration | LangGraph | Stateful workflows, cycles, reflection, retry logic. Industry standard for agentic apps. |
| Chat interface (MVP) | Telegram Bot API | Free, no approval needed, 2-minute setup, runs on phone. |
| Memory store | SQLite | Local-first, zero config, sufficient for personal-scale data. Upgrade path to Postgres if needed. |
| Vector store | ChromaDB (Phase 3) | Not needed until accumulated data exceeds LLM context window (~128K tokens). Add when the simpler approach measurably fails. |
| Eval framework | DeepEval | Real framework from day one. Grows with project — don't build throwaway eval code. |
| Hardware | M3 Max MacBook (36GB) | Develop and deploy on same machine. No Beelink until Phase 5 optional guide. |
| Deployment | Docker Compose | Reproducible, kill-switch friendly, each component is a container. |
| MCP | Phase 3+ | Skip for MVP. Use Google Calendar Python SDK directly. Refactor to MCP once stable reference implementation exists. |
| Siri | Phase 4 | Just a voice→HTTP redirector to the agent. Not a product surface. |
| WhatsApp | Read-only bridge Phase 2, sending Phase 5 | User's primary context dump tool (3 self-groups). Too important to skip but Meta API is a pain. Use whatsapp-web.js bridge for personal read-only. |

### What This Is NOT
- Not a calendar app (it sits on top of your calendar)
- Not a chatbot that waits for commands (it's proactive)
- Not cloud-dependent (everything runs locally)
- Not a wrapper around ChatGPT (it has persistent memory and tool integrations)

---

## 2. Architecture

### High-Level

```
Input Sources                    Agent Core                    Output
─────────────                    ──────────                    ──────
Telegram Bot ──┐                                         ┌──→ Telegram (responses)
Siri Shortcut ─┤    ┌─────────────────────────┐         │
WhatsApp ──────┼───→│  LangGraph Orchestrator  │─────────┤
Cron (briefs) ─┤    │  (stateful agent loop)   │         └──→ Logs (JSON)
Share Sheet ───┘    └────────┬────────────────┘
                             │
                    ┌────────┼────────┐
                    │        │        │
              Tool Layer   Memory   Eval
              (Calendar,   (SQLite, (DeepEval)
               Notes,      ChromaDB
               Email)      Phase 3+)
```

### Docker Container Layout

```
┌─────────────────────────────────────────────────┐
│ Docker Compose Stack                             │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐ │
│  │  Ollama   │  │  Agent   │  │   SQLite DB   │ │
│  │ (Qwen14B) │  │ (Python) │  │  (via volume) │ │
│  │           │  │          │  │               │ │
│  │ Port:     │  │ Port:    │  │ File:         │ │
│  │ 11434     │  │ 8080     │  │ ./data/db/    │ │
│  └──────────┘  └──────────┘  └───────────────┘ │
│                                                  │
│  Shared volume: ./data/ (persists across runs)   │
│  Logs volume:   ./data/logs/                     │
└─────────────────────────────────────────────────┘
```

### Kill-Switch Design

```bash
# Type A: Stop reasoning only (messages queue in DB)
docker compose stop ollama

# Type B: Stop agent + LLM (DB keeps running via volume)
docker compose stop ollama agent

# Resume: agent processes queued items
docker compose start ollama agent
```

When agent restarts, it reads unprocessed messages from SQLite
(status='queued') and processes them in order.

### Data Path Tracing

Every message gets a trace_id and full source_path:

```
siri → http_webhook → agent → calendar_tool → response → telegram
whatsapp_bridge → agent → memory_store → response → telegram
telegram → agent → response → telegram
system_cron → agent → briefing_generator → telegram
```

Stored in conversation log for full observability and debugging.

---

## 3. Phase 1 — Prove the Loop

### Goal
A working Telegram bot that reads your Google Calendar and delivers a useful daily
briefing. You use it every morning for a week and it's actually helpful.

### Timeline: 2-3 weeks

### Components

#### 3.1 Docker Stack
- docker-compose.yml with three services: ollama, agent, db (SQLite via volume)
- Ollama preloaded with Qwen 2.5 14B (Q5_K_M quantization)
- Shared ./data/ volume for persistence
- .env file for secrets (Telegram token, Google Calendar credentials)
- Health checks on all services

#### 3.2 Telegram Bot
- python-telegram-bot library
- Webhook mode (not polling) for reliability
- Message handler: receive text → pass to agent → send response
- Inline keyboard for thumbs up/down on every agent response
- Error handling: if agent/LLM is down, respond "I'm restarting, your message is queued"

#### 3.3 Google Calendar Integration
- google-api-python-client + google-auth
- OAuth2 flow (one-time setup, token stored locally)
- READ-ONLY in Phase 1:
  - get_today_events()
  - get_tomorrow_events()
  - get_events_range(start, end)
  - get_next_event()
  - search_events(query)
- Returns structured data (not raw API response) to the agent

#### 3.4 LangGraph Agent
- Single-agent graph with tool-calling loop:
  1. Receive message
  2. Build context (system prompt + recent conversations + calendar summary)
  3. LLM decides: respond directly OR call a tool
  4. If tool call → execute → feed result back to LLM
  5. LLM generates final response
  6. Log everything
- Tools registered:
  - get_calendar_events (with date params)
  - get_next_event
  - search_calendar
  - store_context_dump (save user's random thoughts/tasks)
  - get_stored_context (retrieve past dumps)
- System prompt: personality, capabilities, what it can/can't do
- Retry logic: if LLM fails to generate valid tool call, retry once with clarification

#### 3.5 Daily Morning Briefing
- Cron job (APScheduler or system cron) triggers at user-configured time
- Fetches: today's events, tomorrow's first event, any stored context dumps from yesterday
- Generates briefing via LLM:
  - "Good morning. Here's your day:"
  - Schedule overview with time gaps highlighted
  - Any context you dumped yesterday that's relevant
  - Suggested priority based on event density + deadlines
- Sends to Telegram as a formatted message

#### 3.6 Context Dump Ingestion
- User sends random text to the bot: "remind me to email Alex about the project update"
- Agent classifies: is this a question (answer it) or a dump (store it)?
- Dumps stored in SQLite with timestamp, raw text, extracted entities (dates, names, actions)
- Retrieved during briefing generation and when contextually relevant

#### 3.7 Conversation Logging
- Every interaction logged to SQLite:

```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,           -- UUID grouping related hops
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    source_origin TEXT NOT NULL,      -- 'telegram', 'siri', 'system_cron', 'whatsapp'
    source_path TEXT NOT NULL,        -- 'telegram→agent', 'siri→http→agent'
    hop_number INTEGER DEFAULT 1,
    role TEXT NOT NULL,               -- 'user', 'assistant', 'system', 'tool'
    content TEXT NOT NULL,
    metadata JSON,                    -- {intent, entities, tool_calls, model, tokens_used, latency_ms}
    processing_time_ms INTEGER
);

CREATE INDEX idx_conversations_trace ON conversations(trace_id);
CREATE INDEX idx_conversations_timestamp ON conversations(timestamp);
CREATE INDEX idx_conversations_source ON conversations(source_origin);
```

#### 3.8 Structured Logging
- JSON logs to stdout + file (./data/logs/)
- Every LLM call logged: input prompt (truncated), output, model, tokens, latency
- Every tool call logged: tool name, params, result, success/failure, duration
- Every Telegram message: in/out, user feedback, trace_id
- Log levels: DEBUG (dev), INFO (production), ERROR (failures)
- Format: one JSON object per line (easy to grep, parse, analyze)

#### 3.9 Feedback System
- Every agent response in Telegram gets inline keyboard: [👍] [👎]
- Feedback stored in actions table:

```sql
CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    trace_id TEXT NOT NULL,
    action_type TEXT NOT NULL,       -- 'calendar_read', 'briefing', 'context_dump', 'suggestion'
    description TEXT,
    tool_calls JSON,                 -- [{tool, params, result, duration_ms}]
    user_feedback TEXT,              -- 'thumbs_up', 'thumbs_down', NULL
    feedback_timestamp DATETIME,
    conversation_id INTEGER,
    execution_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

#### 3.10 DeepEval (Phase 1 Scope)
- Manual test suite: 20-30 test cases covering:
  - "What's on my calendar today?" → expects correct events
  - "What's my next meeting?" → expects correct next event
  - "When am I free tomorrow?" → expects correct gap identification
  - Context dumps: "remind me to X" → expects storage confirmation
  - Briefing quality: given a known calendar state, is the briefing accurate?
- Metrics:
  - Tool call accuracy: did it call the right function with right params?
  - Response factuality: does the answer match actual calendar data?
  - Latency: end-to-end, LLM inference time, tool execution time
  - User feedback rate: % of thumbs up vs thumbs down
- Run manually during development, automated nightly once stable
- Store eval results in ./data/eval/ as JSON for trend tracking

### Phase 1 Exit Criteria
- [ ] Docker stack starts with `docker compose up` and all services healthy
- [ ] Can message the Telegram bot and get calendar-aware responses
- [ ] Morning briefing arrives automatically and is accurate >80% of the time
- [ ] Can dump context ("remind me to X") and it's stored/retrievable
- [ ] Full conversation log with trace paths in SQLite
- [ ] JSON logs capture every LLM call and tool call
- [ ] Thumbs up/down works and stores feedback
- [ ] DeepEval test suite passes with >85% tool call accuracy
- [ ] Used daily for 1 week without crashes

### Phase 1 File Structure

```
ProductivityClaw/
├── docker-compose.yml
├── .env.example
├── .env                          # gitignored
├── README.md
├── PLAN.md                       # this document (gitignored or private)
│
├── agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # entry point, starts bot + scheduler
│   ├── config.py                 # env vars, model config, feature flags
│   │
│   ├── bot/
│   │   ├── telegram_handler.py   # message receive/send, feedback buttons
│   │   └── webhook.py            # HTTP endpoint (for Siri later)
│   │
│   ├── core/
│   │   ├── agent.py              # LangGraph agent definition
│   │   ├── prompts.py            # system prompts, briefing templates
│   │   └── tools/
│   │       ├── __init__.py       # exports ToolRegistry
│   │       ├── base.py           # BaseTool interface
│   │       ├── registry.py      # ToolRegistry class
│   │       ├── calendar_tool.py  # GoogleCalendarTool
│   │       └── context_tool.py   # ContextStoreTool
│   │
│   ├── integrations/
│   │   ├── google_calendar.py    # Calendar SDK wrapper
│   │   └── context_store.py      # SQLite CRUD for context dumps
│   │
│   ├── memory/
│   │   ├── database.py           # SQLite connection, schema init
│   │   ├── inbox.py              # inbox table CRUD + polling (message queue)
│   │   ├── outbox.py             # outbox table CRUD + dispatching
│   │   ├── context_builder.py    # builds LLM context from all memory sources
│   │   ├── conversation_log.py   # log conversations with trace paths
│   │   └── action_log.py         # log agent actions + feedback
│   │
│   ├── scheduler/
│   │   └── briefing.py           # morning briefing cron job
│   │
│   ├── observability/
│   │   ├── logger.py             # structured JSON logging
│   │   └── metrics.py            # latency tracking, counters
│   │
│   └── eval/
│       ├── test_suite.py         # DeepEval test cases
│       ├── run_eval.py           # evaluate against test suite
│       └── fixtures/             # mock calendar data for tests
│
├── data/                         # Docker volume mount, gitignored
│   ├── db/
│   │   └── productivityclaw.db
│   ├── logs/
│   │   └── agent.jsonl
│   └── eval/
│       └── results/
│
└── scripts/
    ├── setup_calendar_oauth.py   # one-time Google OAuth setup
    └── seed_test_data.py         # populate test calendar events
```

---

## 4. Phase 2 — Memory + Write Actions

### Goal
The agent remembers things about you across conversations and can modify your
calendar with confirmation. It starts feeling like it "knows" you.

### Timeline: 2-3 weeks (after Phase 1 complete)

### New Components

#### 4.1 Calendar Write Operations
- New tools: create_event, move_event, delete_event
- Human-in-the-loop confirmation flow:
  1. User: "move my 3pm to tomorrow same time"
  2. Agent generates action plan: "Move 'Team Sync' from today 3pm to tomorrow 3pm"
  3. Telegram inline keyboard: [✅ Confirm] [❌ Cancel]
  4. User confirms → agent executes → logs result
  5. User cancels → agent acknowledges → logs cancellation
- Risk classification:
  - Low risk (auto-execute): reading calendar, storing context
  - Medium risk (confirm): create event, move event
  - High risk (always confirm + show details): delete event, cancel multiple events

- **Event ownership tagging:**
  - Events created by the agent get a custom property: `source: "productivityclaw"`
    (stored in Google Calendar's extendedProperties field)
  - Events created by the human (via Apple Calendar, Google Calendar UI, etc.)
    have NO such tag — they are treated as **human-owned**
  - **Human-owned events are protected:**
    - Agent can NEVER delete a human-owned event (tool rejects the call)
    - Agent can NEVER move a human-owned event without explicit confirmation
      + a warning: "This event was created by you, not me — are you sure?"
    - Agent CAN suggest changes to human-owned events but always as proposals
  - **Agent-owned events are flexible:**
    - Agent can move/modify its own events with standard confirmation flow
    - Auto-approval (Phase 3) only applies to agent-owned events
    - Agent-owned events display "(via Claw)" in the event description
  - On calendar read, every event is tagged with `ownership: 'human' | 'agent'`
    before being passed to the LLM — the agent always knows what it can/can't touch

#### 4.2 Fact Extraction Pipeline
- After each conversation turn, run extraction:
  - Input: conversation text + existing facts
  - Output: new facts or updates to existing facts
  - Uses the same LLM (Qwen 14B) with a structured extraction prompt
  - Runs asynchronously (doesn't block response)
- Extracted fact types:
  - preference: "I prefer morning meetings" → {key: preferred_meeting_time, value: morning}
  - routine: "I have standup at 9am daily" → {key: daily_standup, value: 9:00 AM}
  - deadline: "Paper due March 15" → {key: paper_deadline, value: 2026-03-15}
  - relationship: "Alex is my team lead" → {key: alex_role, value: team_lead}
  - job_application: "Applied to Stripe backend" → {subject: stripe_backend, key: status, value: applied}
  - action_item: "Email John for referral" → {subject: stripe_backend, key: next_step, value: email_john}
  - appointment: "Booked barber Saturday 2pm" → {subject: barber, key: next_appointment, value: 2026-02-28 14:00}
  - habit: user always approves calendar moves → {key: auto_approve_move, value: true, confidence: 0.8}
- Any topic gets unlimited attributes via the subject+key model (see 4.3)
- All data sources feed the same pipeline regardless of source_origin

#### 4.2.1 Extraction Rigor & Validation
- **Constrained extraction prompt:**
  - LLM receives the fixed set of allowed `fact_type` values — no freestyling
  - All existing subjects from DB injected into extraction prompt — forces reuse of
    `stripe_backend` instead of inventing `stripe_app` or `my_stripe_application`
  - Required JSON schema with field types enforced
  - Few-shot examples of correct extractions included in prompt
  - Examples of correct deduplication (recognizing "Stripe" refers to existing subject)
- **Validation layer (code, not LLM):**
  - Extracted JSON must parse as valid JSON
  - `fact_type`, `subject`, `key`, `value` all required — reject if missing
  - `fact_type` must be in the allowed set — reject unknown types
  - Subject fuzzy-matched against existing subjects (Levenshtein distance < 3 → prompt
    LLM to clarify: "Did you mean 'stripe_backend'?")
  - Malformed extractions logged for debugging, never inserted
- **Deduplication logic:**
  - Match on `subject + key` — if both match, it's an update not an insert
  - If match found: update value, bump `times_confirmed`, refresh `last_confirmed`
  - If new subject + key: insert with default confidence (0.7)
  - If contradicts existing (same subject+key, different value): flag for user confirmation
    ("You said you prefer mornings but now you said afternoons — which is it?")
- **Eval (how you know it's working):**
  - Take 50 conversation samples, manually label expected facts
  - Compare to actual LLM extractions
  - Track: false positives (hallucinated facts), false negatives (missed facts),
    naming drift (same entity called different subjects)
  - Every extraction bug becomes a test case
  - Target: >80% precision, >70% recall

#### 4.3 Facts Table

```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_type TEXT NOT NULL,       -- 'preference', 'habit', 'deadline', 'relationship', 'routine'
    subject TEXT NOT NULL,         -- 'user', 'team_sync_meeting', 'thursday_standup'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.7,  -- 0.0 to 1.0
    source_conversation_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP,
    times_confirmed INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (source_conversation_id) REFERENCES conversations(id)
);

-- Confidence decay: confidence * 0.95^(days_since_last_confirmed)
-- Facts below 0.3 confidence are marked is_active=FALSE
-- Facts confirmed multiple times get higher base confidence
```

#### 4.4 Memory Context Injection
- Before every LLM call, build context block:
  1. Query active facts (confidence > 0.5)
  2. Get recent actions (last 10)
  3. Get recent conversations (last 5)
  4. Format into structured text block
  5. Inject into system prompt
- Context budget: keep memory block under ~2000 tokens to leave room for conversation
- **Living user profile:** a compressed, periodically-updated summary of everything known
  about the user — preferences, routines, active projects, key relationships. Always
  injected into system prompt. Grows richer over time but stays within a fixed token
  budget (~500 tokens) because it's re-summarized weekly by the LLM.
  - System prompt structure per call:
    1. Fixed personality + capabilities (~500 tokens, static)
    2. Living user profile (~500 tokens, updated weekly)
    3. Relevant facts for this message (~500 tokens, queried per message)
    4. Recent conversation turns (~500 tokens)
    5. The user's new message

#### 4.5 WhatsApp Self-Group Ingestion
- whatsapp-web.js (Node.js) container added to Docker stack
- Connects to your WhatsApp Web session
- Monitors your 3 self-groups only (configured by group name/ID)
- On new message: extract text → send to agent as context dump with source_origin='whatsapp'
- Parse for: dates, action items, reminders, named entities
- Store in same conversation log + facts pipeline
- Read-only: never sends messages TO WhatsApp

#### 4.6 Apple Notes Capture
- iOS Shortcut: "Share to Claw"
  - Share sheet → Get text → HTTP POST to agent webhook (port 8080)
  - Agent receives with source_origin='apple_notes_share'
- Not a full sync — just on-demand sharing of specific notes

#### 4.7 Claude Sonnet Benchmarking
- Add optional Claude API integration (gated behind feature flag)
- Run eval test suite through both Qwen 14B and Claude Sonnet
- Compare: tool call accuracy, factuality, response quality
- Store comparison results in ./data/eval/comparisons/
- Purpose: know exactly where local model is weaker, inform Phase 3 routing decisions

#### 4.8 Agent Clarification Questions
- When context is ambiguous, the agent asks instead of guessing:
  - "You said 'meet with Alex' — which Alex? Alex from Stripe or Alex your advisor?"
  - "You mentioned a deadline but no date — when is it due?"
  - "You dumped 'important meeting next week' — can you be more specific?"
- Questions tracked in a dedicated table:

```sql
CREATE TABLE agent_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    question_text TEXT NOT NULL,
    context TEXT,                        -- what triggered the question
    status TEXT DEFAULT 'pending',       -- 'pending', 'resolved', 'rejected'
    answer_text TEXT,                    -- user's answer (NULL until resolved)
    answer_trace_id TEXT,                -- conversation where it was answered
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    related_subject TEXT,                -- fact subject this relates to
    FOREIGN KEY (trace_id) REFERENCES conversations(trace_id)
);
```

- **Pending questions** re-surfaced in next briefing:
  "Still need to know: which Alex for next week's meeting?"
- **Resolved answers** feed directly into fact extraction pipeline
- **Rejected questions** ("don't worry about it", "stop asking") logged —
  agent learns what NOT to ask about. Patterns of rejected questions inform
  prompt tuning (agent is asking too much → adjust threshold).
- **Eval signal:** if the agent asks too many questions per session, it's not
  inferring well enough. Track questions-per-conversation as a metric.
  Target: <2 questions per 10 conversations on average.
- Agent should prefer inferring from existing facts over asking. Question is
  the fallback when confidence is low AND the answer materially changes the action.

#### 4.9 DeepEval Expansion
- New metrics:
  - Faithfulness: is the response grounded in retrieved memory/calendar data?
  - Memory accuracy: are extracted facts correct? (manual review of fact samples)
  - Confirmation UX: time from action proposed → user confirms (measure friction)
- Test suite grows from real conversations:
  - Export interesting conversation turns from log
  - Curate into test cases with expected outputs
  - Target: 50+ test cases
- Tool call accuracy target: >90%
- Fact extraction precision target: >80%

### Phase 2 Exit Criteria
- [ ] "Move my 3pm to tomorrow" works with confirmation
- [ ] Say "I prefer morning meetings" once → agent references it a week later
- [ ] WhatsApp self-groups being ingested, agent can reference dumped content
- [ ] Apple Notes share sheet sends to agent
- [ ] Fact extraction running after every conversation
- [ ] Eval: tool call accuracy >90%, fact extraction precision >80%
- [ ] Claude vs Qwen comparison data available

### Phase 2 New Files

```
agent/
├── core/
│   └── confirmation.py            # human-in-the-loop confirmation flow
├── integrations/
│   ├── google_calendar.py         # updated: write operations added
│   └── apple_notes_webhook.py     # receive share sheet POSTs
├── memory/
│   ├── facts.py                   # fact extraction + storage + decay
│   └── context_builder.py         # build memory context for LLM calls
└── eval/
    └── benchmark.py               # Claude vs Qwen comparison runner

whatsapp-bridge/                   # separate container
├── Dockerfile
├── package.json
├── index.js                       # whatsapp-web.js connection
└── config.js                      # group IDs to monitor
```

---

## 5. Phase 3 — Intelligence + Proactive Behavior

### Goal
The agent reaches out to you WITHOUT being asked. It detects conflicts, surfaces
priorities, and pulls from a growing knowledge base. This is the "wow" phase —
where it stops being a chatbot and starts being a productivity agent.

### Timeline: 3-4 weeks

### New Components

#### 5.1 Proactive Notification Engine
- Background process checks every 15-30 minutes:
  - Upcoming meeting in 30 min? → "You have a 1:1 with your advisor in 30 min"
  - Calendar conflict detected? → "Your 2pm and 2:30pm overlap — which takes priority?"
  - Deadline approaching (from facts)? → "Paper deadline is in 3 days — have you started?"
  - Schedule gap? → "You have a 2-hour gap after lunch — good time for deep work"
  - **Departure alert:** "Leave for office at 7:15 today — traffic is heavy + rain
    starting at 7:30. ETA 48 min vs your usual 30 min."
    (combines: calendar first-event time + Distance Matrix ETA + weather)
  - **Weather alert:** "Freezing rain advisory 4-8pm — your 6pm is across town,
    consider rescheduling or leaving early"
  - **Unresolved questions:** "Still need to know: which Alex for next week?"
    (from agent_questions table, status='pending')
- Notification throttling: max 5 proactive messages per day (configurable)
- User can reply "stop" or "too many" → agent reduces frequency
- Each notification type can be individually toggled
- **Combined signal notifications are prioritized** — "traffic + weather + meeting"
  is one high-value message, not three separate pings

#### 5.2 Priority Inference
- Combines signals to rank what matters:
  - Calendar density (busy day → focus on must-dos)
  - Deadline proximity (from facts table)
  - Event importance (1:1 with manager > optional meeting)
  - Historical patterns (what does user always reschedule?)
  - Context dumps (user explicitly said "this is important")
- Priority score: 0-100 per task/event
- Used in briefings and proactive suggestions
- Initially rule-based, evolves with more data

#### 5.3 Email Read-Only Integration (Gmail)
- Gmail API: read-only OAuth scope
- Surface: unread count, important subject lines, action items in recent emails
- Agent can answer: "Do I have any important emails?" "Anything from my advisor?"
- Email content used in briefings: "You have 3 unread emails, one from your advisor about the paper"
- NEVER reads full email body into LLM unless user explicitly asks about a specific email

#### 5.4 Slack Read-Only Integration
- Slack API: read-only for personal workspace
- Surface: unread DMs, mentions in channels, threads you're tagged in
- Agent can answer: "Any Slack messages I need to respond to?"
- Used in briefings: "2 unread Slack DMs and a mention in #team-general"

#### 5.5 Confidence-Based Auto-Approval
- Track approval patterns in actions table:
  - If user approved action type X more than 5 times with 0 rejections → auto-approve
  - Example: after confirming 5 calendar moves, the 6th is auto-executed
  - Agent still reports: "Moved your meeting (auto-approved based on your history)"
- Audit trail: auto_approved=TRUE in action log, with reasoning
- User can revoke: "stop auto-approving calendar moves" → resets to confirmation
- **Only applies to agent-owned events** (see 4.1 event ownership tagging).
  Human-owned calendar events always require explicit confirmation regardless of history.
- **Reliability gate:** auto-approval is disabled system-wide until eval metrics meet
  thresholds:
  - Tool call accuracy >90% sustained over 2 weeks
  - Zero incorrect auto-actions in the last 50 actions
  - User feedback thumbs-up rate >80%
  - If any threshold drops, auto-approval pauses and reverts to confirmation mode
    with a Telegram notice: "Auto-approval paused — accuracy dropped below threshold"
  - Thresholds tracked automatically via the eval pipeline, no manual check needed

#### 5.6 Weekly Productivity Summary
- Generated every Sunday evening (or configured day)
- Data-driven:
  - Meetings this week: count, total hours, most-met person
  - Tasks completed (from context dumps marked done)
  - Patterns: busiest day, most rescheduled events, response time trends
  - Suggestions: "You had 8 meetings on Wednesday — consider blocking focus time"
- Stored in conversation log for future reference

#### 5.7 Travel Time Predictions
- **No history ingestion.** Agent never tracks where you've been — no location history,
  no GPS data, no Google Takeout. Privacy-first.
- **Forward-looking only:** calendar events have locations → Google Maps Distance Matrix
  API computes traffic-aware ETAs for upcoming events.

- **Google Maps Distance Matrix API:**
  - Input: origin (home/office), destination (next event location),
    departure_time (when you need to leave)
  - Output: travel time accounting for real-time traffic at that hour
  - `departure_time` parameter is key — a 2pm commute ≠ a 5pm commute
  - Free tier: 40K calls/month (more than enough for personal use)
  - Agent caches frequent routes in facts table to reduce API calls:
    `{subject: "route_home_to_office", key: "avg_8am", value: "35min"}`

- **How the agent uses this:**
  - Morning briefing: "Your first meeting is at campus — leave by 8:45 (32 min in
    current traffic)"
  - Between-meeting travel: "Your 2pm is downtown and your 3:30 is back on campus —
    that's 40 min apart. You'll be late unless you leave the 2pm early."
  - Proactive departure alerts: "Leave for your 2pm in 15 minutes — traffic is
    heavier than usual"

- **Home/office location:** stored in facts as user preference (one-time setup):
  `{subject: "user", key: "home_address", value: "..."}`
  `{subject: "user", key: "office_address", value: "..."}`

#### 5.7.1 Weather Integration
- **API:** OpenWeatherMap free tier (1,000 calls/day) or WeatherAPI.com free tier
- Agent checks weather automatically — no user action needed
- **What the agent does with weather:**
  - Morning briefing: "High of 42°F, rain starting at 2pm — bring an umbrella"
  - Combined with travel: "Rain + rush hour — leave 15 min earlier than usual
    for your 3pm downtown"
  - Outfit/prep: "Freezing rain tonight — you have a 7pm dinner, consider Uber"
  - Calendar awareness: "Your outdoor team event tomorrow has a 70% chance of rain —
    might want a backup plan"
  - Weekly forecast in Sunday summary: "Rain Mon-Wed, clear Thu-Fri — schedule
    outdoor plans accordingly"
  - Severe weather alert → proactive Telegram message regardless of throttle
- **Weather factors into travel ETA:**
  - Rain/snow → multiply travel time by 1.2-1.5x (configurable)
- **Caching:** weather data cached for 30 min (forecast doesn't change faster than that)
- **Privacy:** only your city/zip is sent to the weather API — no GPS coordinates

#### 5.8 ChromaDB Vector Store
- New Docker container: chromadb
- Embedding model: nomic-embed-text via Ollama (lightweight, local)
- What gets embedded:
  - Conversation chunks (grouped by trace_id)
  - Extracted facts
  - WhatsApp dumps
  - Calendar event descriptions
  - Context dumps
- Retrieval flow:
  1. User sends message
  2. Embed the message
  3. Semantic search top-K relevant memories (K=10)
  4. Inject into context alongside structured facts
  5. LLM reasons with full context
- Replaces "load all facts" approach from Phase 2
- Migration: existing SQLite facts get batch-embedded on first startup

#### 5.9 MCP Migration
- Refactor Google Calendar from direct SDK to MCP server pattern
- Why now: stable reference implementation exists, well-tested tool interface
- Benefits: scoped permissions, standardized tool protocol, easier to add new integrations
- Calendar MCP server: separate process, communicates with agent via MCP protocol
- Gmail and Slack also wrapped as MCP servers
- Foundation for Phase 5 skill ecosystem

#### 5.10 Google Keep Integration
- Google Keep API (unofficial — no official API exists)
- Alternative: use Google Tasks API (official) if user migrates
- Or: Apple Notes proper read via Shortcuts export
- Surface existing notes/lists in agent context
- Read-only: agent can reference but not modify

#### 5.11 Overnight Anomaly Scan & Fact Hygiene
- Scheduled job runs nightly (e.g. 3am)

- **Pre-scan database snapshot (mandatory):**
  - Before ANY edits, copy the SQLite DB file:
    `cp productivityclaw.db snapshots/pre_scan_YYYYMMDD_HHMMSS.db`
  - Snapshot stored in `./data/db/snapshots/` with timestamp
  - Retention: keep last 14 snapshots, delete older ones
  - If scan fails or produces bad results → restore from snapshot
  - Snapshot path logged in the scan's action log entry for traceability

- **Step 1 — Detection (deterministic, no LLM):**
  - **Duplicate candidates:** embed all subject names → cosine similarity scan →
    flag pairs with similarity > 0.7 as candidates
  - **Stale facts:** confidence < 0.3 (formula-based, no judgment)
  - **Orphans:** facts whose source_conversation_id points to deleted
    or very old conversations
  - **Naming fragmentation:** subjects that share keywords but differ in format
    (e.g. `barber_appointment` and `haircut_saturday`)

- **Step 2 — LLM reasoning on candidates (analyst, not editor):**
  - LLM receives the candidate pairs + all facts for both subjects
  - LLM explains WHY it thinks they're duplicates (or not):
    "john_stripe and john_referral are likely the same person — both linked to
    Stripe, both described as referral contacts"
  - LLM catches what embeddings miss: `barber_appointment` and `haircut_saturday`
    are the same topic despite low string similarity
  - LLM output is a structured proposal with a `reasoning` field — auditable
  - LLM writes to `scan_proposals` table ONLY. Never touches `facts` table directly.

- **Step 3 — Execution (strict rules, no exceptions):**
  - **Auto-execute (deterministic only, no LLM involvement):**
    - Stale fact archival (confidence < 0.3, formula-based — no judgment call)
    - Snapshot retention cleanup (delete snapshots older than 14 days)
  - **Propose + require user confirmation:**
    - Subject merges — ALWAYS. Even when LLM is highly confident.
    - Telegram message includes the LLM's reasoning:
      "I think 'john_stripe' and 'john_referral' are the same person because
      both are linked to Stripe. Merge? [Yes] [No]"
    - No merge is ever auto-executed. Period.
  - **Block on conflict (never auto-resolve):**
    - If two subjects have conflicting values for the same key
      (e.g. `john_stripe.email = john@a.com` vs `john_referral.email = john@b.com`)
      → mark as `status='conflict'`, surface to user with both values
    - Agent does NOT pick one unless:
      (a) one value is tool-verified (e.g. came from email header, calendar invite), OR
      (b) user explicitly confirms which is correct
  - **Never allowed:**
    - LLM writing directly to the facts table (always goes through scan_proposals)
    - Deleting facts (only archiving — data is never destroyed)
    - Editing facts that are tool-verified (source is API, not conversation)
    - LLM overriding a deterministic threshold (can reason, cannot lower the bar)

- All proposals and actions logged in actions table with action_type='anomaly_scan'
- Weekly summary includes: "Proposed 3 merges (1 confirmed, 2 pending), archived 12 stale facts"

```sql
CREATE TABLE scan_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp DATETIME NOT NULL,
    snapshot_path TEXT NOT NULL,          -- path to pre-scan DB snapshot
    proposal_type TEXT NOT NULL,          -- 'merge', 'conflict', 'archive', 'orphan'
    subject_a TEXT,
    subject_b TEXT,                       -- NULL for non-merge proposals
    similarity_score REAL,               -- cosine similarity (merges only)
    conflicting_key TEXT,                -- key with conflicting values (conflicts only)
    value_a TEXT,                         -- value from subject_a
    value_b TEXT,                         -- value from subject_b
    llm_reasoning TEXT,                  -- LLM's explanation of why this merge/action makes sense
    status TEXT DEFAULT 'pending',       -- 'pending', 'approved', 'rejected', 'auto_executed'
    resolved_by TEXT,                    -- 'user', 'auto_deterministic', NULL
    resolved_at DATETIME,
    notes TEXT
);
```

#### 5.12 iPhone Notification Capture (High-Value Apps)
- iOS Shortcuts automations for key apps (Slack, Gmail, Canvas)
- On notification from target app → POST summary to agent webhook
- Agent receives with source_origin='ios_notification'
- Not comprehensive (per-app setup required) but captures high-signal notifications
- Alternative: once email/Slack APIs are integrated, notifications become redundant
  for those apps — this is mainly useful for apps without direct API access (Canvas, etc.)
- Screen Time data (app usage stats) as optional enrichment for weekly summaries

#### 5.13 DeepEval Expansion
- New metrics:
  - Proactive suggestion engagement: did user act on it? (>60% target)
  - False positive rate: irrelevant notifications (< 20% target)
  - Memory retrieval relevance: are vector search results actually useful?
  - Priority accuracy: does the ranking match what user actually did?
- Regression suite: every bug fix adds a test case
- Automated nightly eval runs against full test suite
- Target: 100+ test cases

### Phase 3 Exit Criteria
- [ ] Agent proactively sends "You have a 1:1 in 30 min" and it's valued
- [ ] Weekly summary reveals a pattern user hadn't noticed
- [ ] Vector retrieval correctly surfaces a 2-week-old context dump
- [ ] Email/Slack read integration provides useful info in briefings
- [ ] Auto-approval works for frequently-confirmed actions
- [ ] Proactive suggestion engagement >60%
- [ ] MCP servers running for Calendar, Gmail, Slack
- [ ] Overnight anomaly scan merges at least one duplicate correctly
- [ ] Naming drift measurably reduced after scan feedback loop

### Phase 3 New Files

```
agent/
├── core/
│   ├── proactive.py              # notification engine + throttling
│   ├── priority.py               # priority inference scoring
│   └── auto_approval.py          # confidence-based auto-approve logic
├── integrations/
│   ├── gmail.py                  # Gmail API read-only
│   ├── slack.py                  # Slack API read-only
│   └── google_keep.py            # Google Keep/Tasks read
├── memory/
│   ├── vector_store.py           # ChromaDB wrapper
│   ├── embeddings.py             # nomic-embed-text via Ollama
│   └── context_builder.py        # updated: hybrid SQLite + vector retrieval
├── mcp/
│   ├── calendar_server.py        # Google Calendar MCP server
│   ├── gmail_server.py           # Gmail MCP server
│   └── slack_server.py           # Slack MCP server
├── scheduler/
│   ├── briefing.py               # updated: includes email/slack
│   ├── proactive_check.py        # periodic proactive notification check
│   ├── anomaly_scan.py           # nightly duplicate detection + fact hygiene
│   └── weekly_summary.py         # weekly productivity summary
└── memory/
    └── user_profile.py           # living user profile re-summarization

docker-compose.yml                # updated: +chromadb container
```

---

## 6. Phase 4 — Polish, Multimodal, Interview-Ready

### Goal
The version you demo live in interviews. Multiple input channels. Polished UX.
Documented for strangers.

### Timeline: 2-3 weeks

### New Components

#### 6.1 Siri Shortcuts Integration
- Agent HTTP endpoint already exists (port 8080 from Phase 1)
- iOS Shortcuts pack:
  - "Ask Claw": Dictate → POST to /siri/ask → Show result
  - "Dump to Claw": Dictate → POST to /siri/dump → "Stored ✓"
  - "Daily Brief": POST to /siri/briefing → Show result
  - "Share to Claw": Share sheet text → POST to /siri/share → "Stored ✓"
- First-run setup: shortcut prompts for server address + auth token
- Auth: simple shared secret in .env (not production-grade, but sufficient)

#### 6.2 Qwen-VL Image Processing
- Separate Ollama model: qwen-vl loaded on demand
- Trigger: user sends image to Telegram
- Pipeline:
  1. Image received → save to temp
  2. Load Qwen-VL → process image
  3. Output structured data: {summary, detected_dates, entities, action_items, confidence}
  4. Store structured output in memory (not the image itself)
  5. Unload Qwen-VL (save memory for text model)
- Use cases:
  - Screenshot of assignment → extract deadline + requirements
  - Whiteboard photo → extract notes + action items
  - Receipt → extract amount + date + vendor

#### 6.3 Discord Bot
- discord.py library
- Same agent backend, different input handler
- Registered as second source_origin in conversation log
- Useful for: testing multi-channel, users who prefer Discord

#### 6.4 Multi-Model Routing
- Automatic decision per request:
  - Simple/private queries → Qwen 14B local (default)
  - Complex reasoning (priority inference, multi-factor scheduling) → Cloud API
  - Image processing → Qwen-VL
- Router logic: classify query complexity based on tool calls needed + context size
- Feature flag: can disable cloud entirely (full local mode)
- All routing decisions logged for analysis

#### 6.5 Comprehensive Eval Dashboard
- Simple web UI (Flask/Streamlit) served from agent container
- Displays:
  - Quality metrics over time (tool accuracy, factuality, engagement)
  - Model comparison: Qwen vs Claude on eval suite
  - Latency percentiles by source path
  - User feedback trends
  - Memory stats: facts count, confidence distribution, decay rate
- Accessible at localhost:8081

#### 6.6 Response Confidence Self-Assessment
- After generating a response, agent rates its own confidence
- Low confidence → flagged: "I'm not sure about this — want me to check again?"
- Logged: helps identify patterns in uncertainty

#### 6.7 Apple Notes Proper Sync
- AppleScript on Mac → export notes periodically → agent ingests
- Or: Shortcuts automation → periodically share recent notes
- Full read access to Apple Notes library

#### 6.8 Documentation
- README.md: architecture diagrams, quick start, screenshots
- CONTRIBUTING.md: how to add integrations, coding standards
- Architecture decision records (ADRs) for major choices
- Setup guide: step-by-step for a new user

#### 6.9 Performance Optimization
- Response caching: identical calendar queries within 5 minutes return cached result
- Batch briefing generation: pre-compute morning briefing at 7:45am, send at 8:00am
- Model quantization tuning: benchmark Q4_K_M vs Q5_K_M vs Q6_K on eval suite
- Memory pruning: archive old conversations, keep only active facts in hot storage

#### 6.10 Context-Aware Home Automation via HomeKit Shortcuts
- Agent triggers HomeKit scenes/shortcuts based on schedule + context:
  - **Smart morning routine:** Briefing time triggers lights on, coffee machine, Focus Mode
    enabled — adapts to first-meeting time (earlier meeting = earlier routine)
  - **Focus mode activation:** When calendar shows deep work block or deadline approaching,
    agent triggers Do Not Disturb + Focus Mode via Shortcuts
  - **End-of-day transition:** After last meeting, agent triggers wind-down scene
    (lights dim, summary sent, tomorrow's prep surfaced)
- Implementation: agent POSTs to iOS Shortcuts HTTP endpoint (same webhook pattern as Siri)
  - Shortcut receives trigger type → runs HomeKit scene
  - Shortcuts: "Claw Morning", "Claw Focus", "Claw Wind Down"
- Triggers are context-driven, not just time-driven:
  - Morning routine adjusts to actual wake-up signals (first Telegram message, first calendar check)
  - Focus mode considers calendar density + active deadlines from facts table
  - End-of-day adapts to actual last meeting, not a fixed time
- All automations logged in actions table with action_type='homekit_trigger'
- User can override/disable any automation: "stop triggering focus mode"
- Throttling: max 1 trigger per scene per hour to prevent spam

### Phase 4 Exit Criteria
- [ ] "Hey Siri, ask Claw what I should focus on" → answer in Telegram within 5 seconds
- [ ] Image sent → structured extraction → stored as memory
- [ ] Discord bot works alongside Telegram
- [ ] Eval dashboard shows quality trends in browser
- [ ] README enables a stranger to set up in 30 minutes
- [ ] Demo takes under 60 seconds and is impressive
- [ ] Morning routine triggers automatically based on schedule context
- [ ] Focus mode activates during deep work blocks
- [ ] End-of-day transition fires after last meeting

---

## 7. Phase 5 — Open Source Ecosystem

### Goal
Community-ready. Extensible. Other people use it and contribute.

### Timeline: Ongoing

### Components

#### 7.1 Skill Manifest Spec
- Your own lightweight format:

```yaml
name: "weather_check"
description: "Check weather for a location"
version: "1.0"
permissions:
  - network_read    # needs to call weather API
inputs:
  location:
    type: string
    required: true
outputs:
  temperature: number
  conditions: string
  forecast: string
handler: "weather_skill.py"
env_vars:
  - WEATHER_API_KEY
```

#### 7.2 Skill Import Pipeline
- Folder flow: skillimport/ → staging/ → activeSkills/ → quarantine/
- Import steps:
  1. Detect format (native vs Claw-skill)
  2. Parse metadata
  3. Safety scan (no shell exec, no network by default)
  4. Sandbox test with mock data
  5. Generate import_report.json
  6. User confirms → promote to activeSkills/

#### 7.3 Claw-Skill Compatibility
- Parse SKILL.md frontmatter
- Map triggers/keywords to internal tool interface
- Wrap scripts as callable tools with permissions
- Generate native manifest
- Security: read-only auto-allowed, exec/network disabled by default

#### 7.4 Multi-Agent Architecture
- Specialized agents per domain:
  - Calendar Agent: scheduling, conflicts, availability
  - Email Agent: triage, summarize, draft responses
  - Notes Agent: organize, search, connect ideas
  - Triage Agent: routes incoming messages to the right specialist
- LangGraph sub-graphs for each agent
- Shared memory layer

#### 7.5 Additional Channels
- WhatsApp sending via Meta Business API (if accessible)
- iMessage via BlueBubbles (experimental, Mac-only)

#### 7.6 Financial Data Import (Optional/Maybe)
- Apple Pay CSV, bank CSV exports dropped into finances/import/ folder
- Agent parses: date, amount, category, vendor
- Stored in dedicated encrypted table (NOT in regular conversation logs)
- Agent surfaces aggregated trends only ("food spending up 30% this week")
- Raw transaction data never passed to LLM — only summaries
- Requires: encrypted SQLite storage, PII-safe prompting patterns
- Decision: build only if there's clear personal value; high security bar

#### 7.6 Community & CI/CD
- GitHub Actions: lint, test, eval suite on PR
- Skill validation pipeline in CI
- Issue templates, PR templates
- Community skill showcase
- Optional deployment guide for dedicated hardware (Beelink etc.)

### Phase 5 Exit Criteria
- [ ] Someone clones repo → `docker compose up` → working agent in 30 minutes
- [ ] At least one community-contributed skill exists
- [ ] CI/CD validates every PR against eval suite

---

## 8. Memory Architecture (Deep Dive)

### Three-Layer Design

```
Layer 1: Conversation Log (raw history, append-only)
    ↓ extraction pipeline
Layer 2: Structured Facts (learned knowledge, with confidence)
    ↓ embedding + indexing (Phase 3+)
Layer 3: Vector Store (semantic retrieval for large-scale memory)
```

### Layer 1 → Layer 2 Flow

After each conversation:
1. Extract facts using LLM (structured prompt → JSON output)
2. Deduplicate against existing facts (same subject + key)
3. If duplicate: increment times_confirmed, refresh last_confirmed, adjust confidence
4. If new: insert with default confidence (0.7)
5. If contradicts existing: flag for user confirmation

### Confidence Model

```
base_confidence = 0.7 (single mention)
                  0.85 (confirmed twice)
                  0.95 (confirmed 5+ times)

current_confidence = base_confidence * (0.95 ^ days_since_confirmed)

Thresholds:
  > 0.6: included in context
  0.3-0.6: included only if directly relevant
  < 0.3: marked inactive, excluded from context
```

### Phase 3 Vector Store Integration

```
User message → embed
                 ↓
         ChromaDB semantic search (top-K)
                 ↓
         Retrieved chunks + SQLite facts
                 ↓
         Context builder merges both
                 ↓
         Injected into LLM system prompt
```

Embedding model: nomic-embed-text (via Ollama)
- 768-dimensional embeddings
- Runs locally, ~500MB memory
- Fast: <50ms per embedding on M3 Max

---

## 9. Caching Strategy (Deep Dive)

Agentic chains are expensive: 3-5 LLM calls × 10-15s = 30-75 seconds without caching.
Three layers of caching bring this down to ~10-20 seconds.

### Layer 1: KV Cache (Ollama Native — Free, Phase 1)

Ollama keeps the model loaded in memory and caches the KV (key-value) attention state.
If the conversation prefix (system prompt + user context) is the same across calls,
Ollama reuses the cached computation.

```
First call:    system prompt + user context → ~1-2s prompt processing
Follow-up:     same prefix, new message    → ~50-100ms prompt processing
```

This is huge for ProductivityClaw because the system prompt + living user profile +
injected facts will be a stable prefix across calls in the same session. The 1-2 second
prompt processing essentially drops to nothing on follow-ups.

- **Phase 1:** just keep Ollama's model loaded (don't unload between calls). Set
  `OLLAMA_KEEP_ALIVE` to a long duration. Structure prompts so the stable context
  (system prompt, user profile) comes first and the variable part (new message) comes last.
- **Phase 3+:** when user profile and facts change between calls, the prefix changes and
  KV cache is invalidated. Minimize unnecessary context changes to preserve cache hits.
- **Cost:** zero — Ollama does this automatically. Just be aware of it when designing prompts.

### Layer 2: Response/Result Caching (SQLite — Phase 2)

Cache LLM outputs for repeated or near-identical queries. Serve cached response instead
of calling the LLM again.

```sql
CREATE TABLE response_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT NOT NULL,            -- SHA-256 of normalized query
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    context_hash TEXT NOT NULL,          -- hash of the context (calendar state, facts)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,        -- TTL-based expiry
    hit_count INTEGER DEFAULT 0,
    last_hit DATETIME
);

CREATE INDEX idx_cache_query ON response_cache(query_hash);
CREATE INDEX idx_cache_expiry ON response_cache(expires_at);
```

- **What gets cached:**
  - "What's on my calendar today?" → cache until calendar changes or EOD
  - "What should I focus on?" → cache for 30 min (unless new context arrives)
  - Classification tasks (email categorization, priority scoring) → cache by content hash
  - Briefing generation → pre-compute at 7:45am, serve cached at 8:00am
- **Cache invalidation:**
  - TTL-based: each cache type has a default TTL (calendar: 5 min, briefing: until next day,
    classification: 1 hour)
  - Event-based: new calendar event, new context dump, new email → invalidate related caches
  - `context_hash` ensures stale context doesn't produce stale answers
- **Performance:** turns a 10-second LLM call into <50ms SQLite lookup

### Layer 3: Semantic Caching (Phase 3 — Requires Vector Store)

Embed incoming queries and check cosine similarity against recent cached queries.
If similarity > threshold, serve the cached response without calling the LLM.

```
User: "What should I work on right now?"
  → Embed query → check against recent cache entries
  → Match: "What should I focus on?" (similarity: 0.94, cached 12 min ago)
  → Context hash still valid → serve cached response
  → Cost: ~100-200ms (embedding + lookup) vs 10-15s (full LLM call)
```

- Similarity threshold: 0.90 (conservative — would rather re-run the LLM than serve
  a wrong cached answer)
- Only applies when `context_hash` matches (same underlying data state)
- Uses the same ChromaDB instance as memory retrieval (separate collection)
- Cache collection: `query_cache` with metadata: response, context_hash, timestamp

### Net Effect on Agentic Chains

| Scenario | Without Caching | With Caching |
|----------|----------------|--------------|
| Single query | 10-15s | 10-15s (cold) / <50ms (cache hit) |
| Follow-up in same session | 10-15s | 3-5s (warm KV cache) |
| Agentic chain (3-5 calls) | 30-75s | ~10-20s (1-2 actual LLM calls + cached) |
| Repeated daily briefing | 10-15s | <50ms (pre-computed) |
| "What's on my calendar?" (asked twice in 5 min) | 10-15s × 2 | 10-15s + <50ms |

### Phase Rollout

| Phase | Caching Layer | Build  | Runtime Cost | What You Get |
|-------|--------------|-----------|-------------|--------------|
| 1 | KV cache | Zero — Ollama native | Native | Follow-up calls ~50ms instead of ~2s |
| 2 | Response cache | Small — SQLite table + lookup logic | local SQLite | Repeated queries <50ms, briefing pre-computed |
| 3 | Semantic cache | Medium — embedding + cosine lookup | local ChromaDB | "Similar enough" queries served from cache |

All three layers are free at runtime (no API costs, everything local). The only cost
is the engineering time to build layers 2 and 3.

---

## 10. Eval Strategy (Deep Dive)


### Framework: DeepEval

### Metrics by Phase

| Metric | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| Tool call accuracy | ✅ >85% | ✅ >90% | ✅ >90% | ✅ >95% |
| Response factuality | ✅ >80% | ✅ >85% | ✅ >90% | ✅ >90% |
| Latency (p95) | ✅ <10s | ✅ <8s | ✅ <5s | ✅ <3s |
| User feedback (thumbs up %) | ✅ track | ✅ >70% | ✅ >80% | ✅ >85% |
| Fact extraction precision | — | ✅ >80% | ✅ >85% | ✅ >90% |
| Faithfulness | — | ✅ basic | ✅ strict | ✅ strict |
| Proactive engagement | — | — | ✅ >60% | ✅ >70% |
| False positive rate | — | — | ✅ <20% | ✅ <15% |
| Memory retrieval relevance | — | — | ✅ basic | ✅ strict |

### Test Suite Growth

- Phase 1: 20-30 manual test cases
- Phase 2: 50+ (manual + curated from real conversations)
- Phase 3: 100+ (manual + curated + regression cases from bugs)
- Phase 4: 150+ (comprehensive, automated nightly)

### Eval Pipeline

```
1. Load test suite (fixtures + expected outputs)
2. Run each test case through agent
3. Score with DeepEval metrics
4. Compare against thresholds
5. Store results in ./data/eval/results/
6. If regression detected → alert (log + Telegram message)
```

---

## 11. Docker & Infrastructure

### docker-compose.yml Evolution

Phase 1:
- ollama (Qwen 14B)
- agent (Python)
- SQLite (via volume mount)

Phase 2: Add
- whatsapp-bridge (Node.js)

Phase 3: Add
- chromadb (vector store)

Phase 4: Add
- eval-dashboard (Flask/Streamlit)

### Resource Allocation (M3 Max 36GB)

| Component | Memory | Notes |
|-----------|--------|-------|
| Qwen 2.5 14B (Q5) | ~14GB | Primary LLM |
| Qwen-VL (Phase 4) | ~8GB | Loaded on demand, unloaded after |
| nomic-embed-text | ~500MB | Embedding model (Phase 3) |
| ChromaDB | ~1GB | Vector store (Phase 3) |
| Agent + SQLite | ~500MB | Python process |
| WhatsApp bridge | ~200MB | Node.js (Phase 2) |
| System overhead | ~4GB | macOS + Docker |
| **Total active** | **~20GB** | Leaves ~16GB headroom |

### Backup Strategy
- ./data/ directory: entire state of the system
- Weekly backup: `tar -czf backup-$(date +%Y%m%d).tar.gz ./data/`
- Can rebuild everything else from code + backup

### Environment Variables (.env)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Google Calendar
GOOGLE_CALENDAR_CREDENTIALS_PATH=./data/credentials/google_oauth.json
GOOGLE_CALENDAR_TOKEN_PATH=./data/credentials/google_token.json

# LLM
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=qwen2.5:14b-instruct-q5_K_M

# Agent
BRIEFING_TIME=08:00
LOG_LEVEL=INFO
MAX_PROACTIVE_MESSAGES_PER_DAY=5

# Optional: Cloud LLM for benchmarking
ANTHROPIC_API_KEY=
BENCHMARK_ENABLED=false

# Phase 2+
WHATSAPP_GROUP_IDS=
WEBHOOK_AUTH_TOKEN=

# Phase 3+
CHROMADB_HOST=http://chromadb:8000
EMBEDDING_MODEL=nomic-embed-text
```

---

## 12. Key Technical Decisions Log

| Date | Decision | Reasoning | Revisit When |
|------|----------|-----------|--------------|
| Feb 2026 | Qwen 14B over GPT-OSS-20B | Better tool calling support, more community validation, lower memory footprint | GPT-OSS-20B has more agentic benchmarks |
| Feb 2026 | No DeepSeek API | Privacy concern (Chinese servers), contradicts project narrative | DeepSeek offers US-hosted endpoints |
| Feb 2026 | No vector store Phase 1-2 | Data volume too small, fits in context window | Memory exceeds ~50K tokens |
| Feb 2026 | No MCP Phase 1-2 | Direct SDK is faster to build and debug | Phase 3, after stable tool interfaces exist |
| Feb 2026 | SQLite over Postgres | Simpler, zero config, sufficient for personal scale | Multi-user or concurrent access needed |
| Feb 2026 | M3 Max only, no Beelink | One environment to debug, more powerful, already owned | Phase 5 community deployment guide |
| Feb 2026 | Telegram over Discord for MVP | Free, instant setup, runs on phone, most agent builders start here | Never (keep as primary) |
| Feb 2026 | DeepEval from day one | Real framework prevents throwaway eval code | Never (grow the test suite) |
| Feb 2026 | WhatsApp read via web bridge | User's primary context dump tool, too important to skip | Meta opens Business API for personal use |
| Feb 2026 | Cloud LLM for benchmark only | Know quality ceiling, isolate agent vs model issues | Local model quality is sufficient |

---

## Quick Reference: What to Build Next

If you're ever stuck on what to work on, follow this order within each phase:

**Phase 1 priority order:**
1. Docker stack boots cleanly
2. Ollama serves Qwen 14B
3. Telegram bot sends/receives messages
4. Google Calendar read works
5. Agent connects Telegram → LLM → Calendar → response
6. Conversation logging works
7. Daily briefing triggers and sends
8. Context dump storage works
9. Feedback buttons work
10. DeepEval test suite passes
11. Use it daily for a week

Each step builds on the previous. Don't skip ahead.