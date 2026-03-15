from agent.memory.pending_actions import create_pending_action
from agent.integrations.apple_calendar import find_event_identifier

_current_trace_id = None


def execute(
    event_title: str,
    current_date: str,
    new_date: str,
    new_start_time: str,
    new_end_time: str,
) -> str:
    """Propose moving a calendar event -- returns a pending-action token."""
    # Look up the live EventKit identifier so we can act on it later
    event_identifier = find_event_identifier(event_title, current_date)
    if event_identifier is None:
        return (
            f"Could not find an event titled '{event_title}' on {current_date}. "
            "Please check the title and date."
        )

    payload = {
        "event_identifier": event_identifier,
        "event_title": event_title,
        "new_date_str": new_date,
        "new_start_time": new_start_time,
        "new_end_time": new_end_time,
    }

    description = (
        f"Move '{event_title}' from {current_date} → {new_date} "
        f"{new_start_time}–{new_end_time}"
    )

    action_id = create_pending_action(
        trace_id=_current_trace_id or "untraced",
        action_type="move_event",
        payload=payload,
        description=description,
    )
    print(f"  [move_event] pending action {action_id}: {description}")
    return f"PENDING_ACTION:{action_id}|{description}"
