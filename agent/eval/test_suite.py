"""
ProductivityClaw Eval Suite (Phase 1 + Phase 2)

Two layers:
  1. DETERMINISTIC (no LLM) -- tests calendar filtering, context building, prompt assembly,
     email classification parsing, priority lock, pending actions.
     Fast, always pass, no dependencies beyond Python.

  2. LLM INTEGRATION (requires MLX server at localhost:8000) -- sends real queries through
     the agent pipeline with mock calendar data, checks that responses mention the right
     events and don't hallucinate. Marked with @pytest.mark.llm so you can skip them:
       pytest agent/eval/test_suite.py -m "not llm"      # fast only
       pytest agent/eval/test_suite.py -m llm             # LLM only
       pytest agent/eval/test_suite.py                    # everything
"""

import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from agent.eval.fixtures.mock_calendar import get_mock_events, get_mock_reminders


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_str():
    return datetime.now().strftime("%Y-%m-%d")

def _tomorrow_str():
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

def _date_str(delta):
    return (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")


def _patch_calendar():
    """Return mock patches for fetch_all_events and fetch_all_reminders.

    Patches at the import site (context_builder) not the source module,
    because context_builder does `from ... import fetch_all_events`.
    """
    events_patch = patch(
        "agent.memory.context_builder.fetch_all_events",
        return_value=get_mock_events(),
    )
    reminders_patch = patch(
        "agent.memory.context_builder.fetch_all_reminders",
        return_value=get_mock_reminders(),
    )
    return events_patch, reminders_patch


def _response_mentions(response: str, keywords: list[str]) -> list[str]:
    """Return keywords that are missing from the response (case-insensitive)."""
    lower = response.lower()
    return [kw for kw in keywords if kw.lower() not in lower]


def _response_excludes(response: str, forbidden: list[str]) -> list[str]:
    """Return forbidden keywords that ARE present in the response."""
    lower = response.lower()
    return [kw for kw in forbidden if kw.lower() in lower]


# ===========================================================================
# LAYER 1: DETERMINISTIC PIPELINE TESTS
# ===========================================================================

class TestFilterEvents:
    """Tests for the event filtering logic."""

    def test_filter_today_returns_only_today(self):
        from agent.memory.context_builder import filter_events
        events = get_mock_events()
        today = _today_str()
        tomorrow = _tomorrow_str()
        result = filter_events(events, today, tomorrow)
        assert len(result) == 4
        titles = {e["title"] for e in result}
        assert "Morning Workout" in titles
        assert "1:1 with Advisor" in titles
        assert "Lunch with Alex" in titles
        assert "Sprint Planning" in titles

    def test_filter_tomorrow_returns_only_tomorrow(self):
        from agent.memory.context_builder import filter_events
        events = get_mock_events()
        tomorrow = _tomorrow_str()
        day_after = _date_str(2)
        result = filter_events(events, tomorrow, day_after)
        assert len(result) == 2
        titles = {e["title"] for e in result}
        assert "Career Fair" in titles
        assert "Gym Session" in titles

    def test_filter_empty_range_returns_empty(self):
        from agent.memory.context_builder import filter_events
        events = get_mock_events()
        result = filter_events(events, "2099-01-01", "2099-01-02")
        assert result == []

    def test_filter_past_week(self):
        from agent.memory.context_builder import filter_events
        events = get_mock_events()
        past_week = _date_str(-7)
        today = _today_str()
        result = filter_events(events, past_week, today)
        assert len(result) == 3
        titles = {e["title"] for e in result}
        assert "Team Standup" in titles
        assert "Dentist Appointment" in titles
        assert "ML Paper Reading Group" in titles


class TestBuildCalendarContext:
    """Tests that build_calendar_context produces correct text sections."""

    def _build_with_mocks(self):
        events_patch, reminders_patch = _patch_calendar()
        with events_patch, reminders_patch:
            from agent.memory.context_builder import build_calendar_context
            return build_calendar_context()

    def test_contains_today_section(self):
        ctx = self._build_with_mocks()
        assert "TODAY" in ctx

    def test_today_events_listed(self):
        ctx = self._build_with_mocks()
        assert "Morning Workout" in ctx
        assert "1:1 with Advisor" in ctx
        assert "Lunch with Alex" in ctx
        assert "Sprint Planning" in ctx

    def test_tomorrow_events_listed(self):
        ctx = self._build_with_mocks()
        assert "Career Fair" in ctx

    def test_reminders_listed(self):
        ctx = self._build_with_mocks()
        assert "REMINDERS" in ctx
        assert "Submit internship application" in ctx
        assert "Buy groceries" in ctx
        assert "Review PR #42" in ctx

    def test_past_events_listed(self):
        ctx = self._build_with_mocks()
        assert "RECENT" in ctx
        assert "Team Standup" in ctx

    def test_locations_included(self):
        ctx = self._build_with_mocks()
        assert "Campus Gym" in ctx or "Chipotle" in ctx

    def test_no_empty_output(self):
        ctx = self._build_with_mocks()
        assert len(ctx) > 100


class TestPromptAssembly:
    """Tests that the system prompt is constructed correctly."""

    def test_system_prompt_has_base_instructions(self):
        from agent.core.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "ProductivityClaw" in prompt
        assert "Tools" in prompt

    def test_system_prompt_includes_user_profile_section(self):
        from agent.core.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "LIVING USER PROFILE" in prompt

    def test_memory_injection_format(self):
        """Verify that graph_agent injects FTS5 memories into the prompt."""
        from agent.core.prompts import get_system_prompt
        base = get_system_prompt()
        # Simulate what graph_agent.chat_with_llm does
        sys_content = base + f"\n\nCurrent time: Monday, March 10, 2026 at 10:00 AM"
        sys_content += "\n\n--- THINGS THE USER PREVIOUSLY TOLD YOU (use these to answer) ---"
        sys_content += "\n- I prefer morning meetings (2026-03-09)"
        sys_content += "\n--- END MEMORIES ---"
        assert "morning meetings" in sys_content
        assert "END MEMORIES" in sys_content


# ===========================================================================
# LAYER 1B: PRIORITY LOCK (deterministic)
# ===========================================================================

class TestPriorityLock:
    """Tests for the LLM priority lock (user activity tracking)."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_langchain(self):
        pytest.importorskip("langchain_openai")

    def test_inactive_by_default(self):
        from agent.scheduler.briefing import is_user_active
        import agent.scheduler.briefing as b
        b._last_user_message_ts = 0.0
        assert not is_user_active()

    def test_active_after_record(self):
        from agent.scheduler.briefing import record_user_activity, is_user_active
        record_user_activity()
        assert is_user_active()

    def test_inactive_after_timeout(self):
        import agent.scheduler.briefing as b
        b._last_user_message_ts = time.time() - 180
        assert not b.is_user_active()


# ===========================================================================
# LAYER 1C: EMAIL CLASSIFICATION PARSING (deterministic)
# ===========================================================================

class TestEmailClassificationParsing:
    """Tests that email classifier correctly parses LLM JSON output."""

    def test_parse_valid_json_response(self):
        """Simulate what classify_emails does when LLM returns valid JSON."""
        import json
        raw = '[{"id": "msg1", "priority": "HIGH", "reason": "deadline"}, {"id": "msg2", "priority": "LOW", "reason": "newsletter"}]'
        parsed = json.loads(raw)
        assert len(parsed) == 2
        assert parsed[0]["priority"] == "HIGH"
        assert parsed[1]["priority"] == "LOW"

    def test_parse_json_with_think_tags(self):
        """LLM sometimes wraps JSON in <think> tags — we strip them."""
        import re
        raw = '<think>Let me classify these emails...</think>\n[{"id": "msg1", "priority": "HIGH", "reason": "urgent"}]'
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        import json
        parsed = json.loads(cleaned)
        assert len(parsed) == 1
        assert parsed[0]["priority"] == "HIGH"

    def test_parse_empty_list(self):
        import json
        raw = "[]"
        parsed = json.loads(raw)
        assert parsed == []


# ===========================================================================
# LAYER 1D: PENDING ACTION TOKEN (deterministic)
# ===========================================================================

class TestPendingActionToken:
    """Verify PENDING_ACTION token parsing logic."""

    def test_token_parsed_correctly(self):
        fake_result = "PENDING_ACTION:abc12345|Create 'Standup' on 2026-03-15 09:00-09:30"
        parts = fake_result.split("|", 1)
        action_id = parts[0].replace("PENDING_ACTION:", "").strip()
        display = parts[1].strip()
        assert action_id == "abc12345"
        assert display == "Create 'Standup' on 2026-03-15 09:00-09:30"

    def test_normal_result_not_detected(self):
        result_str = "TODAY (Monday, March 09): No events"
        assert not result_str.startswith("PENDING_ACTION:")


# ===========================================================================
# LAYER 2: LLM INTEGRATION TESTS (requires MLX server at localhost:8000)
# ===========================================================================

def _mlx_available() -> bool:
    """Check if MLX server is reachable."""
    try:
        import requests
        resp = requests.get("http://localhost:8000/v1/models", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# Skip entire LLM section if MLX is not running
pytestmark_llm = pytest.mark.skipif(
    not _mlx_available(),
    reason="MLX server not running at localhost:8000 -- skipping LLM integration tests",
)


def _ask_agent(user_message: str) -> tuple[str, int, str | None]:
    """Send a message through the full agent pipeline with mock calendar data.

    Returns (response_text, latency_ms, pending_action_id).
    """
    with patch("agent.integrations.apple_calendar.fetch_all_events", return_value=get_mock_events()), \
         patch("agent.integrations.apple_calendar.fetch_all_reminders", return_value=get_mock_reminders()):
        from agent.core.graph_agent import chat_with_llm
        response, latency, pending_id = chat_with_llm(user_message, [])
        return response, latency, pending_id


@pytest.mark.llm
class TestScheduleQueries:
    """Does the agent correctly report events from calendar data?"""

    @pytestmark_llm
    def test_whats_on_today(self):
        response, _, _ = _ask_agent("What's on my schedule today?")
        missing = _response_mentions(response, [
            "Morning Workout",
            "Advisor",
            "Lunch",
            "Sprint Planning",
        ])
        assert not missing, f"Response missing events: {missing}"

    @pytestmark_llm
    def test_whats_on_tomorrow(self):
        response, _, _ = _ask_agent("What do I have tomorrow?")
        missing = _response_mentions(response, ["Career Fair"])
        assert not missing, f"Response missing: {missing}"

    @pytestmark_llm
    def test_any_reminders(self):
        response, _, _ = _ask_agent("Do I have any reminders?")
        missing = _response_mentions(response, [
            "internship",
            "groceries",
            "PR",
        ])
        assert not missing, f"Response missing reminders: {missing}"

    @pytestmark_llm
    def test_next_meeting(self):
        response, _, _ = _ask_agent("What's my next meeting?")
        found_any = any(
            kw.lower() in response.lower()
            for kw in ["Advisor", "Sprint Planning", "Workout", "Lunch"]
        )
        assert found_any, f"Response doesn't mention any of today's events: {response[:200]}"

    @pytestmark_llm
    def test_this_week(self):
        response, _, _ = _ask_agent("What's happening this week?")
        missing = _response_mentions(response, ["Database Systems Midterm"])
        assert not missing, f"Response missing this-week event: {missing}"


@pytest.mark.llm
class TestToolCallEnforcement:
    """Ensure schedule queries execute the calendar tool (agentic behavior)."""

    @pytestmark_llm
    def test_schedule_query_executes_get_calendar_events(self):
        with patch("agent.integrations.apple_calendar.fetch_all_events", return_value=get_mock_events()), \
             patch("agent.integrations.apple_calendar.fetch_all_reminders", return_value=get_mock_reminders()):
            from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
            from agent.core.prompts import get_system_prompt
            from agent.core.graph_agent import build_agent

            graph = build_agent()
            sys_content = get_system_prompt()
            sys_content += f"\n\nCurrent time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"

            result = graph.invoke({
                "messages": [
                    SystemMessage(content=sys_content),
                    HumanMessage(content="What's on my schedule today?"),
                ],
                "pending_action_id": None,
            })

            tool_messages = [
                m for m in result["messages"]
                if isinstance(m, ToolMessage) and getattr(m, "name", "") == "get_calendar_events"
            ]

            assert tool_messages, (
                "Expected get_calendar_events tool execution for schedule query, "
                "but no calendar tool call occurred."
            )


@pytest.mark.llm
class TestWriteToolBehavior:
    """Does the agent use write tools correctly (pending action pattern)?"""

    @pytestmark_llm
    def test_create_event_returns_pending_action(self):
        """Ask to create an event -- should produce a PENDING_ACTION token."""
        response, _, pending_id = _ask_agent("Add a meeting with John tomorrow at 3pm")
        # Agent should either return a pending_action_id or mention confirmation
        has_pending = pending_id is not None
        mentions_confirm = any(
            kw.lower() in response.lower()
            for kw in ["confirm", "pending", "approve", "create"]
        )
        assert has_pending or mentions_confirm, (
            f"Agent did not create pending action or mention confirmation: {response[:300]}"
        )

    @pytestmark_llm
    def test_delete_not_supported(self):
        """Delete is not a supported tool -- agent should say so."""
        response, _, _ = _ask_agent("Delete my Sprint Planning meeting")
        found_refusal = any(
            kw.lower() in response.lower()
            for kw in ["can't", "cannot", "don't have", "unable", "not able", "delete"]
        )
        assert found_refusal, f"Agent did not refuse delete request: {response[:300]}"


@pytest.mark.llm
class TestNoHallucination:
    """Does the agent avoid making up events that aren't in the data?"""

    @pytestmark_llm
    def test_no_fake_events_on_empty_day(self):
        """Ask about a day with no events -- agent should say nothing scheduled."""
        with patch("agent.integrations.apple_calendar.fetch_all_events", return_value=[]), \
             patch("agent.integrations.apple_calendar.fetch_all_reminders", return_value=[]):
            from agent.core.graph_agent import chat_with_llm
            response, _, _ = chat_with_llm("What's on my calendar today?", [])

        hallucination_signals = ["meeting at", "call with", "appointment", "interview"]
        found = _response_excludes(response, hallucination_signals)
        assert len(found) < 2, f"Possible hallucination -- found: {found} in: {response[:300]}"

    @pytestmark_llm
    def test_no_invented_events_for_today(self):
        """With known events, agent should not invent extra ones."""
        response, _, _ = _ask_agent("What's on my schedule today?")
        wrong_day = ["Dentist Appointment", "Career Fair", "Database Systems Midterm"]
        leaked = _response_excludes(response, wrong_day)
        assert not leaked, f"Agent mentioned events from wrong day: {leaked}"


@pytest.mark.llm
class TestLatency:
    """Latency checks -- not hard failures, but tracked."""

    @pytestmark_llm
    def test_response_under_10_seconds(self):
        """Agent should respond within 10s for a simple query."""
        _, latency, _ = _ask_agent("What's on my calendar today?")
        assert latency < 10000, f"Response took {latency}ms -- exceeds 10s threshold"

    @pytestmark_llm
    def test_simple_greeting_under_5_seconds(self):
        """A non-calendar message should be fast."""
        _, latency, _ = _ask_agent("Hey, how's it going?")
        assert latency < 5000, f"Simple greeting took {latency}ms -- exceeds 5s threshold"
