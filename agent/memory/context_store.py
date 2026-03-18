"""Context dump storage -- raw text the user shares for future reference."""

from agent.memory.database import db


def store_context_dump(trace_id: str, content: str, source: str = "telegram") -> int:
    """Persist a context dump from the user and sync to FTS5 index.
    Returns the row id of the inserted context_dump."""
    cursor = db.execute(
        "INSERT INTO context_dumps (trace_id, content, source) VALUES (?, ?, ?)",
        (trace_id, content, source),
    )
    row_id = cursor.lastrowid
    # Keep FTS index in sync
    db.execute(
        "INSERT INTO context_dumps_fts (content, trace_id, created_at) "
        "VALUES (?, ?, CURRENT_TIMESTAMP)",
        (content, trace_id),
    )
    db.commit()
    return row_id


def search_context_dumps(query: str, limit: int = 5) -> list[dict]:
    """Search stored context by relevance using FTS5 full-text search.
    Auto-joins words with OR so partial matches are returned.
    Returns best matches ranked by BM25. Falls back to empty list on error."""
    try:
        # Split query into words and join with OR for partial matching
        words = query.strip().split()
        if not words:
            return []
        fts_query = " OR ".join(words)

        rows = db.execute(
            "SELECT content, trace_id, created_at, rank "
            "FROM context_dumps_fts WHERE content MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [
            {"content": r[0], "trace_id": r[1], "created_at": r[2], "rank": r[3]}
            for r in rows
        ]
    except Exception:
        # If query has FTS5 syntax issues (special chars etc), return empty
        return []


def get_recent_dumps(limit: int = 10) -> list[dict]:
    """Return the most recent context dumps, newest first."""
    rows = db.execute(
        "SELECT trace_id, content, source, created_at FROM context_dumps "
        "WHERE archived = 0 ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"trace_id": r[0], "content": r[1], "source": r[2], "created_at": r[3]}
        for r in rows
    ]
