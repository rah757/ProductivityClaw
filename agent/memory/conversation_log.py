import json
from agent.memory.database import db

def log_message(trace_id, source, role, content, metadata=None):
    db.execute(
        "INSERT INTO conversations (trace_id, source, role, content, metadata) VALUES (?, ?, ?, ?, ?)",
        (trace_id, source, role, content, json.dumps(metadata) if metadata else None)
    )
    db.commit()

def get_recent_conversations(limit=10):
    cursor = db.execute(
        "SELECT role, content, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    rows.reverse()
    return rows
