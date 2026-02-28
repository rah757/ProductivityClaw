import json
from agent.memory.database import db

def log_action(trace_id, action_type, metadata=None):
    db.execute(
        "INSERT INTO actions (trace_id, action_type, metadata) VALUES (?, ?, ?)",
        (trace_id, action_type, json.dumps(metadata) if metadata else None)
    )
    db.commit()

def update_feedback(trace_id, feedback):
    db.execute(
        "UPDATE actions SET user_feedback = ? WHERE trace_id = ? AND user_feedback IS NULL",
        (feedback, trace_id)
    )
    db.commit()
