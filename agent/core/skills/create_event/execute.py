from agent.memory.pending_actions import create_pending_action

_current_trace_id = None


def execute(
    title: str,
    date: str,
    start_time: str,
    end_time: str,
    calendar: str | None = None,
    location: str | None = None,
) -> str:
    """Propose creating a calendar event -- returns a pending-action token."""
    payload = {
        "title": title,
        "date_str": date,
        "start_time": start_time,
        "end_time": end_time,
    }
    if calendar:
        payload["calendar_name"] = calendar
    if location:
        payload["location"] = location

    description = f"Create '{title}' on {date} {start_time}–{end_time}"
    if location:
        description += f" @ {location}"

    action_id = create_pending_action(
        trace_id=_current_trace_id or "untraced",
        action_type="create_event",
        payload=payload,
        description=description,
    )
    print(f"  [create_event] pending action {action_id}: {description}")
    return f"PENDING_ACTION:{action_id}|{description}"
