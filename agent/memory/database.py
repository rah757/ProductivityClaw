import os
import sqlite3
from agent.config import DB_PATH

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    
    db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSON
        );
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action_type TEXT NOT NULL,
            user_feedback TEXT,
            metadata JSON
        );
        CREATE TABLE IF NOT EXISTS pending_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id   TEXT NOT NULL UNIQUE,
            trace_id    TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload     JSON NOT NULL,
            description TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS agent_created_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            event_identifier    TEXT NOT NULL UNIQUE,
            title               TEXT NOT NULL,
            created_by_trace_id TEXT,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS context_dumps (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id   TEXT NOT NULL,
            content    TEXT NOT NULL,
            source     TEXT DEFAULT 'telegram',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS dsa_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem TEXT NOT NULL,
            category TEXT NOT NULL,
            pattern TEXT,
            attempt_number INTEGER DEFAULT 1,
            performance TEXT,
            time_minutes INTEGER,
            weaknesses TEXT,
            next_review DATE,
            interval_days INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dsa_problem_next_review
            ON dsa_progress (problem, next_review);
    """)
    db.commit()

    # Migration: drop old context_dumps if it uses the legacy schema (raw_text column)
    cols = {row[1] for row in db.execute("PRAGMA table_info(context_dumps)").fetchall()}
    if "raw_text" in cols:
        db.execute("DROP TABLE context_dumps")
        db.execute("""
            CREATE TABLE context_dumps (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id   TEXT NOT NULL,
                content    TEXT NOT NULL,
                source     TEXT DEFAULT 'telegram',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()
        print("  [db] migrated context_dumps to new schema")

    return db

# Global instance
db = init_db()
