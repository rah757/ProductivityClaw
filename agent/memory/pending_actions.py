"""Pending actions -- write operations staged for user confirmation."""

import uuid
import json
from datetime import datetime
from agent.memory.database import db


def create_pending_action(trace_id: str, action_type: str, payload: dict, description: str) -> str:
    """Stage a write action awaiting user confirmation. Returns action_id."""
    action_id = str(uuid.uuid4())[:8]
    db.execute(
        """INSERT INTO pending_actions (action_id, trace_id, action_type, payload, description)
           VALUES (?, ?, ?, ?, ?)""",
        (action_id, trace_id, action_type, json.dumps(payload), description),
    )
    db.commit()
    return action_id


def get_pending_action(action_id: str) -> dict | None:
    """Fetch a pending action by its ID. Returns None if not found."""
    row = db.execute(
        "SELECT action_id, trace_id, action_type, payload, description, status "
        "FROM pending_actions WHERE action_id = ?",
        (action_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "action_id":   row[0],
        "trace_id":    row[1],
        "action_type": row[2],
        "payload":     row[3],   # raw JSON string -- caller does json.loads()
        "description": row[4],
        "status":      row[5],
    }


def resolve_pending_action(action_id: str, status: str):
    """Mark a pending action as confirmed or cancelled."""
    db.execute(
        "UPDATE pending_actions SET status = ?, resolved_at = ? WHERE action_id = ?",
        (status, datetime.utcnow().isoformat(), action_id),
    )
    db.commit()
