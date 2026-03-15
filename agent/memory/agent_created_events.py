"""Track events created by the agent for ownership protection."""

from agent.memory.database import db


def register_agent_event(event_identifier: str, title: str, trace_id: str | None = None):
    """Record that an event was created by the agent."""
    db.execute(
        """INSERT OR IGNORE INTO agent_created_events (event_identifier, title, created_by_trace_id)
           VALUES (?, ?, ?)""",
        (event_identifier, title, trace_id),
    )
    db.commit()


def is_agent_event(event_identifier: str) -> bool:
    """Return True if this event was created by the agent."""
    row = db.execute(
        "SELECT 1 FROM agent_created_events WHERE event_identifier = ?",
        (event_identifier,),
    ).fetchone()
    return row is not None
