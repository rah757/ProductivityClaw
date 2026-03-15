"""Context dump storage -- raw text the user shares for future reference."""

from agent.memory.database import db


def store_context_dump(trace_id: str, content: str, source: str = "telegram"):
    """Persist a context dump from the user."""
    db.execute(
        "INSERT INTO context_dumps (trace_id, content, source) VALUES (?, ?, ?)",
        (trace_id, content, source),
    )
    db.commit()


def get_recent_dumps(limit: int = 10) -> list[dict]:
    """Return the most recent context dumps, newest first."""
    rows = db.execute(
        "SELECT trace_id, content, source, created_at FROM context_dumps "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"trace_id": r[0], "content": r[1], "source": r[2], "created_at": r[3]}
        for r in rows
    ]
