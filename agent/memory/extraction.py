"""Fact extraction pipeline — runs after each conversation turn.

Sends the user message + agent response to the LLM, extracts structured
facts, and routes them to staging (low/medium confidence) or directly
to the facts table (high confidence >= 0.9).
"""

import json
import re
import threading
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agent.config import MLX_MODEL, MLX_BASE_URL
from agent.memory.facts import insert_staging, insert_fact, promote_staging

_EXTRACT_SYSTEM = """You extract factual information from conversations.

Only extract facts that are:
- User preferences, habits, routines (e.g. "prefers morning meetings")
- Personal info: name, role, location, education, schedule
- Work/project details: current projects, tools, deadlines
- Relationships: people, teams, contacts

Do NOT extract:
- Greetings, small talk, jokes
- One-off questions the user asked
- Transient requests ("remind me to...", "set a timer")
- Tool results or calendar data (already stored elsewhere)
- Things the assistant said that aren't user facts

Respond ONLY with a JSON array. If no facts to extract, respond with [].
Each fact needs: fact_type, subject, key, value, confidence.

Format:
[{"fact_type": "preference|personal|work|relationship", "subject": "user", "key": "short_key", "value": "the fact in plain english", "confidence": 0.5}]

confidence guide:
- 0.9-1.0: Explicit, direct statement ("I'm a data scientist", "I prefer mornings")
- 0.7-0.8: Strong implication ("just got back from the gym" → exercises regularly)
- 0.5-0.6: Weak signal, needs more evidence

/no_think"""


def extract_facts(
    user_message: str,
    response: str,
    trace_id: str | None = None,
) -> list[dict]:
    """Extract facts from a conversation turn. Returns list of extracted facts.
    High confidence (>= 0.9) → inserted directly into facts table.
    Lower confidence → inserted into facts_staging."""

    # Skip trivial exchanges
    if len(user_message.strip()) < 10 and len(response.strip()) < 20:
        return []

    llm = ChatOpenAI(
        base_url=MLX_BASE_URL,
        api_key="not-needed",
        model=MLX_MODEL,
        temperature=0.0,
        max_tokens=2000,
    )

    conversation = f"User: {user_message}\nAssistant: {response}"

    try:
        resp = llm.invoke([
            SystemMessage(content=_EXTRACT_SYSTEM),
            HumanMessage(content=conversation),
        ])

        text = resp.content or ""
        if isinstance(text, list):
            text = "".join(
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in text
            )

        # Strip think tags
        full_text = str(text)
        clean = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

        # Find JSON array
        json_str = None
        for candidate in [clean, full_text]:
            match = re.search(r"\[.*\]", candidate, re.DOTALL)
            if match:
                json_str = match.group()
                break

        if not json_str:
            return []

        facts = json.loads(json_str)
        if not isinstance(facts, list):
            return []

    except Exception as e:
        print(f"  [extraction] failed: {e}")
        return []

    tid = trace_id or "extract"
    results = []

    for fact in facts:
        if not all(k in fact for k in ("fact_type", "subject", "key", "value")):
            continue

        conf = float(fact.get("confidence", 0.7))
        fact_type = str(fact["fact_type"])
        subject = str(fact["subject"])
        key = str(fact["key"])
        value = str(fact["value"])

        if conf >= 0.9:
            # High confidence — insert directly
            insert_fact(
                fact_type=fact_type,
                subject=subject,
                key=key,
                value=value,
                confidence=conf,
                trace_id=tid,
            )
            print(f"  [extraction] direct: {subject}.{key} = {value} (conf={conf})")
        else:
            # Lower confidence — stage for review
            insert_staging(
                trace_id=tid,
                fact_type=fact_type,
                subject=subject,
                key=key,
                value=value,
                confidence=conf,
                evidence=f"From: {user_message[:100]}",
            )
            print(f"  [extraction] staged: {subject}.{key} = {value} (conf={conf})")

        results.append(fact)

    if results:
        print(f"  [extraction] extracted {len(results)} facts")
    return results


def extract_facts_background(
    user_message: str,
    response: str,
    trace_id: str | None = None,
    delay: float = 3.0,
) -> None:
    """Fire fact extraction in a background thread with a short delay.
    The delay avoids blocking MLX if the user sends another message immediately."""
    from agent.scheduler.briefing import is_user_active

    def _run():
        time.sleep(delay)
        # Check priority lock — skip if user is actively chatting
        if is_user_active():
            print("  [extraction] deferred — user active")
            return
        extract_facts(user_message, response, trace_id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
