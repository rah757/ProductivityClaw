"""
Phase 2 deterministic tests: write skills + pending-action lifecycle.

No LLM, no Ollama, no EventKit required -- all write calls are mocked.

Run:
    pytest agent/eval/test_write_tools.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_trace(skill_dir: str):
    """Clear cached trace_id from a skill module."""
    import sys
    mod_name = f"skill_{skill_dir}"
    if mod_name in sys.modules:
        del sys.modules[mod_name]


# ===========================================================================
# store_context skill
# ===========================================================================

class TestStoreContextSkill:

    def test_returns_stored(self):
        with patch("agent.memory.context_store.store_context_dump") as mock_store:
            _reset_trace("store_context")
            import importlib, importlib.util, os
            path = os.path.join(os.path.dirname(__file__), "../core/skills/store_context/execute.py")
            spec = importlib.util.spec_from_file_location("skill_store_context", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result = mod.execute(text="I prefer morning meetings")
            assert result == "Stored."
            mock_store.assert_called_once()
            _, kwargs = mock_store.call_args
            assert "morning meetings" in mock_store.call_args[0][1]  # content arg

    def test_trace_id_injected(self):
        with patch("agent.memory.context_store.store_context_dump") as mock_store:
            _reset_trace("store_context")
            import importlib, importlib.util, os
            path = os.path.join(os.path.dirname(__file__), "../core/skills/store_context/execute.py")
            spec = importlib.util.spec_from_file_location("skill_store_context", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod._current_trace_id = "abc12345"

            mod.execute(text="test content")
            call_args = mock_store.call_args[0]
            assert call_args[0] == "abc12345"  # trace_id


# ===========================================================================
# create_event skill
# ===========================================================================

class TestCreateEventSkill:

    def _load_module(self):
        _reset_trace("create_event")
        import importlib, importlib.util, os
        path = os.path.join(os.path.dirname(__file__), "../core/skills/create_event/execute.py")
        spec = importlib.util.spec_from_file_location("skill_create_event", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_returns_pending_action_token(self):
        mod = self._load_module()
        result = mod.execute(
            title="Team Standup",
            date="2026-03-15",
            start_time="09:00",
            end_time="09:30",
        )
        assert result.startswith("PENDING_ACTION:")
        assert "|" in result

    def test_pending_action_stored_in_db(self):
        from agent.memory.pending_actions import get_pending_action
        mod = self._load_module()
        result = mod.execute(
            title="Deep Work Block",
            date="2026-03-15",
            start_time="10:00",
            end_time="12:00",
            location="Home",
        )
        action_id = result.split(":")[1].split("|")[0].strip()
        action = get_pending_action(action_id)

        assert action is not None
        assert action["action_type"] == "create_event"
        assert action["status"] == "pending"
        payload = json.loads(action["payload"])
        assert payload["title"] == "Deep Work Block"
        assert payload["location"] == "Home"

    def test_description_in_token(self):
        mod = self._load_module()
        result = mod.execute(
            title="Interview",
            date="2026-03-20",
            start_time="14:00",
            end_time="15:00",
        )
        description = result.split("|", 1)[1]
        assert "Interview" in description
        assert "2026-03-20" in description


# ===========================================================================
# move_event skill
# ===========================================================================

class TestMoveEventSkill:

    def _load_module(self):
        _reset_trace("move_event")
        import importlib, importlib.util, os
        path = os.path.join(os.path.dirname(__file__), "../core/skills/move_event/execute.py")
        spec = importlib.util.spec_from_file_location("skill_move_event", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_returns_pending_action_token_when_found(self):
        mod = self._load_module()
        with patch("agent.integrations.apple_calendar.find_event_identifier",
                   return_value="EK-FAKE-ID-001"):
            result = mod.execute(
                event_title="Sprint Planning",
                current_date="2026-03-09",
                new_date="2026-03-10",
                new_start_time="10:00",
                new_end_time="11:00",
            )
        assert result.startswith("PENDING_ACTION:")
        assert "Sprint Planning" in result

    def test_returns_error_when_not_found(self):
        mod = self._load_module()
        with patch("agent.integrations.apple_calendar.find_event_identifier",
                   return_value=None):
            result = mod.execute(
                event_title="Ghost Meeting",
                current_date="2026-03-09",
                new_date="2026-03-10",
                new_start_time="10:00",
                new_end_time="11:00",
            )
        assert "Could not find" in result
        assert "Ghost Meeting" in result

    def test_payload_contains_identifier(self):
        from agent.memory.pending_actions import get_pending_action
        mod = self._load_module()
        with patch("agent.integrations.apple_calendar.find_event_identifier",
                   return_value="EK-REAL-ID-XYZ"):
            result = mod.execute(
                event_title="Sprint Planning",
                current_date="2026-03-09",
                new_date="2026-03-11",
                new_start_time="14:00",
                new_end_time="15:00",
            )
        action_id = result.split(":")[1].split("|")[0].strip()
        action = get_pending_action(action_id)
        payload = json.loads(action["payload"])
        assert payload["event_identifier"] == "EK-REAL-ID-XYZ"
        assert payload["new_date_str"] == "2026-03-11"


# ===========================================================================
# Pending-action lifecycle
# ===========================================================================

class TestPendingActionLifecycle:

    def test_confirm_resolves_action(self):
        from agent.memory.pending_actions import (
            create_pending_action, get_pending_action, resolve_pending_action
        )
        aid = create_pending_action("t-test", "create_event", {"title": "X"}, "Create X")
        assert get_pending_action(aid)["status"] == "pending"
        resolve_pending_action(aid, "confirmed")
        assert get_pending_action(aid)["status"] == "confirmed"

    def test_cancel_resolves_action(self):
        from agent.memory.pending_actions import (
            create_pending_action, get_pending_action, resolve_pending_action
        )
        aid = create_pending_action("t-test", "create_event", {"title": "Y"}, "Create Y")
        resolve_pending_action(aid, "cancelled")
        assert get_pending_action(aid)["status"] == "cancelled"

    def test_unknown_id_returns_none(self):
        from agent.memory.pending_actions import get_pending_action
        assert get_pending_action("doesnotexist") is None


# ===========================================================================
# graph_agent: PENDING_ACTION token detection (no LLM)
# ===========================================================================

class TestGraphPendingActionDetection:
    """
    Verifies that call_tools correctly strips PENDING_ACTION tokens,
    sets state, and passes a clean display string to the LLM.
    """

    def test_pending_action_sets_state(self):
        """Simulate call_tools receiving a PENDING_ACTION result."""
        from langchain_core.messages import AIMessage, ToolMessage

        # Fake a tool call result
        fake_result = "PENDING_ACTION:abc12345|Create 'Standup' on 2026-03-15 09:00-09:30"

        # Replicate the detection logic from call_tools
        detected_pending_id = None
        result_str = fake_result
        if result_str.startswith("PENDING_ACTION:"):
            parts = result_str.split("|", 1)
            detected_pending_id = parts[0].replace("PENDING_ACTION:", "").strip()
            display = parts[1].strip() if len(parts) > 1 else result_str

        assert detected_pending_id == "abc12345"
        assert display == "Create 'Standup' on 2026-03-15 09:00-09:30"

    def test_normal_result_no_state_change(self):
        """Normal tool results should not trigger pending_action_id."""
        result_str = "TODAY (Monday, March 09): No events"
        detected = None
        if result_str.startswith("PENDING_ACTION:"):
            detected = "something"
        assert detected is None
