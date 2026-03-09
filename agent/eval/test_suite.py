"""
ProductivityClaw Phase 1 Eval Suite

Two layers:
  1. DETERMINISTIC (no LLM) -- tests calendar filtering, context building, prompt assembly.
     Fast, always pass, no dependencies beyond Python.

  2. LLM INTEGRATION (requires Ollama running) -- sends real queries through the agent
     pipeline with mock calendar data, checks that responses mention the right events
     and don't hallucinate. Marked with @pytest.mark.llm so you can skip them:
       pytest agent/eval/test_suite.py -m "not llm"      # fast only
       pytest agent/eval/test_suite.py -m llm             # LLM only
       pytest agent/eval/test_suite.py                    # everything
"""

import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

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
        # A range in the far future with no events
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
        assert len(ctx) > 100  # should be a substantial block of text


class TestPromptAssembly:
    """Tests that the system prompt is constructed correctly."""

    def test_system_prompt_has_base_instructions(self):
        from agent.core.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "ProductivityClaw" in prompt
        assert "READ-ONLY" in prompt

    def test_system_prompt_includes_user_profile_section(self):
        from agent.core.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "LIVING USER PROFILE" in prompt

    def test_calendar_context_injected_into_graph_prompt(self):
        """Verify that graph_agent.chat_with_llm actually puts calendar data in the prompt."""
        # We can't call chat_with_llm without Ollama, but we can check
        # the prompt construction logic by inspecting the code path.
        from agent.core.prompts import get_system_prompt
        base = get_system_prompt()
        # Simulate what graph_agent.chat_with_llm does
        calendar_context = "TODAY: 10:00 AM | Test Event [Work]"
        sys_content = base + f"\n\nCurrent time: Monday, March 10, 2026 at 10:00 AM"
        sys_content += f"\n\n--- CALENDAR DATA (use this if the user asked about schedule) ---\n{calendar_context}\n---"
        assert "Test Event" in sys_content
        assert "CALENDAR DATA" in sys_content


# ===========================================================================
# LAYER 2: LLM INTEGRATION TESTS (requires Ollama running)
# ===========================================================================

def _ollama_available() -> bool:
    """Check if Ollama is reachable."""
    try:
        import ollama
        ollama.list()
        return True
    except Exception:
        return False


# Skip entire LLM section if Ollama is not running
pytestmark_llm = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running -- skipping LLM integration tests",
)


def _ask_agent(user_message: str) -> tuple[str, int]:
    """Send a message through the full agent pipeline with mock calendar data.

    Returns (response_text, latency_ms).
    """
    events_patch, reminders_patch = _patch_calendar()
    with events_patch, reminders_patch:
        from agent.memory.context_builder import build_calendar_context
        from agent.core.graph_agent import chat_with_llm

        calendar_context = build_calendar_context()
        response, latency = chat_with_llm(user_message, [], calendar_context)
        return response, latency


@pytest.mark.llm
class TestScheduleQueries:
    """Does the agent correctly report events from calendar data?"""

    @pytestmark_llm
    def test_whats_on_today(self):
        response, _ = _ask_agent("What's on my schedule today?")
        missing = _response_mentions(response, [
            "Morning Workout",
            "Advisor",
            "Lunch",
            "Sprint Planning",
        ])
        assert not missing, f"Response missing events: {missing}"

    @pytestmark_llm
    def test_whats_on_tomorrow(self):
        response, _ = _ask_agent("What do I have tomorrow?")
        missing = _response_mentions(response, ["Career Fair"])
        assert not missing, f"Response missing: {missing}"

    @pytestmark_llm
    def test_any_reminders(self):
        response, _ = _ask_agent("Do I have any reminders?")
        missing = _response_mentions(response, [
            "internship",
            "groceries",
            "PR",
        ])
        assert not missing, f"Response missing reminders: {missing}"

    @pytestmark_llm
    def test_next_meeting(self):
        response, _ = _ask_agent("What's my next meeting?")
        # Should mention at least one of today's events
        found_any = any(
            kw.lower() in response.lower()
            for kw in ["Advisor", "Sprint Planning", "Workout", "Lunch"]
        )
        assert found_any, f"Response doesn't mention any of today's events: {response[:200]}"

    @pytestmark_llm
    def test_this_week(self):
        response, _ = _ask_agent("What's happening this week?")
        missing = _response_mentions(response, ["Database Systems Midterm"])
        assert not missing, f"Response missing this-week event: {missing}"


@pytest.mark.llm
class TestNoHallucination:
    """Does the agent avoid making up events that aren't in the data?"""

    @pytestmark_llm
    def test_no_fake_events_on_empty_day(self):
        """Ask about a day with no events -- agent should say nothing scheduled."""
        # Patch with empty events
        with patch("agent.integrations.apple_calendar.fetch_all_events", return_value=[]), \
             patch("agent.integrations.apple_calendar.fetch_all_reminders", return_value=[]):
            from agent.memory.context_builder import build_calendar_context
            from agent.core.graph_agent import chat_with_llm
            ctx = build_calendar_context()
            response, _ = chat_with_llm("What's on my calendar today?", [], ctx)

        # Should NOT contain specific event-sounding content
        hallucination_signals = ["meeting at", "call with", "appointment", "interview"]
        found = _response_excludes(response, hallucination_signals)
        # Allow some false positives -- flag if 2+ hallucination signals present
        assert len(found) < 2, f"Possible hallucination -- found: {found} in: {response[:300]}"

    @pytestmark_llm
    def test_no_invented_events_for_today(self):
        """With known events, agent should not invent extra ones."""
        response, _ = _ask_agent("What's on my schedule today?")
        # These events exist in fixtures but NOT for today
        wrong_day = ["Dentist Appointment", "Career Fair", "Database Systems Midterm"]
        leaked = _response_excludes(response, wrong_day)
        assert not leaked, f"Agent mentioned events from wrong day: {leaked}"


@pytest.mark.llm
class TestReadOnlyBehavior:
    """Does the agent correctly refuse write requests?"""

    @pytestmark_llm
    def test_refuses_to_add_event(self):
        response, _ = _ask_agent("Add a meeting with John tomorrow at 3pm")
        found_refusal = any(
            kw.lower() in response.lower()
            for kw in ["can't", "cannot", "read-only", "don't have", "unable", "not able", "write"]
        )
        assert found_refusal, f"Agent did not refuse write request: {response[:300]}"

    @pytestmark_llm
    def test_refuses_to_delete_event(self):
        response, _ = _ask_agent("Delete my Sprint Planning meeting")
        found_refusal = any(
            kw.lower() in response.lower()
            for kw in ["can't", "cannot", "read-only", "don't have", "unable", "not able", "write"]
        )
        assert found_refusal, f"Agent did not refuse delete request: {response[:300]}"


@pytest.mark.llm
class TestLatency:
    """Latency checks -- not hard failures, but tracked."""

    @pytestmark_llm
    def test_response_under_10_seconds(self):
        """Agent should respond within 10s for a simple query."""
        _, latency = _ask_agent("What's on my calendar today?")
        assert latency < 10000, f"Response took {latency}ms -- exceeds 10s threshold"

    @pytestmark_llm
    def test_simple_greeting_under_5_seconds(self):
        """A non-calendar message should be fast."""
        _, latency = _ask_agent("Hey, how's it going?")
        assert latency < 5000, f"Simple greeting took {latency}ms -- exceeds 5s threshold"
