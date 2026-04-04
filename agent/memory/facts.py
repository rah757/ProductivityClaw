"""Dedicated fact storage: durable `facts` + proposed `facts_staging`.

Extraction pipeline (LLM → validate → staging → promote) wires in here later.
"""

from __future__ import annotations

from typing import Any, Optional

from agent.memory.database import db


def insert_staging(
    trace_id: str,
    fact_type: str,
    subject: str,
    key: str,
    value: str,
    confidence: float = 0.7,
    evidence: Optional[str] = None,
) -> int:
    """Insert a proposed fact. Returns staging row id."""
    cur = db.execute(
        """
        INSERT INTO facts_staging (trace_id, fact_type, subject, key, value, confidence, evidence, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (trace_id, fact_type, subject, key, value, confidence, evidence),
    )
    db.commit()
    return int(cur.lastrowid)


def promote_staging(staging_id: int, source_conversation_id: Optional[int] = None) -> Optional[int]:
    """Move a staging row into `facts` (upsert on subject+key). Returns facts.id."""
    row = db.execute(
        "SELECT trace_id, fact_type, subject, key, value, confidence FROM facts_staging WHERE id = ? AND status = 'pending'",
        (staging_id,),
    ).fetchone()
    if not row:
        return None
    trace_id, fact_type, subject, key, value, conf = row

    existing = db.execute(
        "SELECT id FROM facts WHERE subject = ? AND key = ? AND is_active = 1",
        (subject, key),
    ).fetchone()
    now = datetime_sql()

    if existing:
        db.execute(
            """
            UPDATE facts SET value = ?, confidence = ?, last_confirmed = ?, times_confirmed = times_confirmed + 1,
                trace_id = ?, source_conversation_id = COALESCE(?, source_conversation_id)
            WHERE id = ?
            """,
            (value, conf, now, trace_id, source_conversation_id, existing[0]),
        )
        fact_id = existing[0]
    else:
        cur = db.execute(
            """
            INSERT INTO facts (fact_type, subject, key, value, confidence, trace_id, source_conversation_id, last_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fact_type, subject, key, value, conf, trace_id, source_conversation_id, now),
        )
        fact_id = int(cur.lastrowid)

    db.execute(
        "UPDATE facts_staging SET status = 'approved', resolved_at = ? WHERE id = ?",
        (now, staging_id),
    )
    db.commit()
    return fact_id


def reject_staging(staging_id: int) -> None:
    now = datetime_sql()
    db.execute(
        "UPDATE facts_staging SET status = 'rejected', resolved_at = ? WHERE id = ?",
        (now, staging_id),
    )
    db.commit()


def insert_fact(
    fact_type: str,
    subject: str,
    key: str,
    value: str,
    confidence: float = 0.7,
    trace_id: Optional[str] = None,
    source_conversation_id: Optional[int] = None,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
) -> int:
    """Insert directly into `facts` (e.g. after validation or tool-confirmed data)."""
    existing = db.execute(
        "SELECT id FROM facts WHERE subject = ? AND key = ? AND is_active = 1",
        (subject, key),
    ).fetchone()
    now = datetime_sql()
    if existing:
        db.execute(
            """
            UPDATE facts SET value = ?, confidence = ?, fact_type = ?, last_confirmed = ?, times_confirmed = times_confirmed + 1,
                trace_id = ?, source_conversation_id = COALESCE(?, source_conversation_id),
                valid_from = COALESCE(?, valid_from), valid_to = COALESCE(?, valid_to)
            WHERE id = ?
            """,
            (value, confidence, fact_type, now, trace_id, source_conversation_id, valid_from, valid_to, existing[0]),
        )
        db.commit()
        return int(existing[0])
    cur = db.execute(
        """
        INSERT INTO facts (fact_type, subject, key, value, confidence, trace_id, source_conversation_id, valid_from, valid_to, last_confirmed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (fact_type, subject, key, value, confidence, trace_id, source_conversation_id, valid_from, valid_to, now),
    )
    db.commit()
    return int(cur.lastrowid)


def get_active_facts(
    limit: int = 50,
    min_confidence: float = 0.5,
) -> list[dict[str, Any]]:
    """Rows for prompt injection."""
    rows = db.execute(
        """
        SELECT id, fact_type, subject, key, value, confidence, valid_from, valid_to, last_confirmed
        FROM facts
        WHERE is_active = 1 AND confidence >= ?
        ORDER BY last_confirmed DESC
        LIMIT ?
        """,
        (min_confidence, limit),
    ).fetchall()
    cols = ["id", "fact_type", "subject", "key", "value", "confidence", "valid_from", "valid_to", "last_confirmed"]
    return [dict(zip(cols, r)) for r in rows]


def format_facts_for_prompt(limit: int = 40, min_confidence: float = 0.5) -> str:
    """Compact block for system prompt."""
    facts = get_active_facts(limit=limit, min_confidence=min_confidence)
    if not facts:
        return ""
    lines = ["--- EXTRACTED FACTS (from conversations) ---"]
    for f in facts:
        line = f"  - [{f['fact_type']}] {f['subject']}.{f['key']} = {f['value']} (conf: {f['confidence']:.2f})"
        lines.append(line)
    lines.append("---")
    return "\n".join(lines)


def pending_staging(limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT id, trace_id, fact_type, subject, key, value, confidence, evidence, created_at
        FROM facts_staging WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    cols = ["id", "trace_id", "fact_type", "subject", "key", "value", "confidence", "evidence", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def archive_fact(fact_id: int) -> None:
    db.execute("UPDATE facts SET is_active = 0 WHERE id = ?", (fact_id,))
    db.commit()


def datetime_sql() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
