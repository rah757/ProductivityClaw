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

        -- FTS5 full-text search index over context_dumps
        CREATE VIRTUAL TABLE IF NOT EXISTS context_dumps_fts
        USING fts5(content, trace_id UNINDEXED, created_at UNINDEXED);

        CREATE TABLE IF NOT EXISTS processed_emails (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id      TEXT NOT NULL UNIQUE,
            subject         TEXT,
            sender          TEXT,
            account_name    TEXT,
            classification  TEXT NOT NULL,
            summary         TEXT,
            context_dump_id INTEGER,
            processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Durable extracted facts (subject + key + value model)
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 0.7,
            trace_id TEXT,
            source_conversation_id INTEGER,
            valid_from TEXT,
            valid_to TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP,
            times_confirmed INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (source_conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_subject_key ON facts(subject, key);
        CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(is_active);

        -- Proposed facts awaiting review or auto-promotion rules
        CREATE TABLE IF NOT EXISTS facts_staging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            fact_type TEXT NOT NULL,
            subject TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 0.7,
            evidence TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        );
        CREATE INDEX IF NOT EXISTS idx_facts_staging_status ON facts_staging(status);
    """)
    db.commit()

    # Migration: backfill FTS5 index from existing context_dumps
    fts_count = db.execute("SELECT COUNT(*) FROM context_dumps_fts").fetchone()[0]
    real_count = db.execute("SELECT COUNT(*) FROM context_dumps").fetchone()[0]
    if real_count > 0 and fts_count == 0:
        db.execute(
            "INSERT INTO context_dumps_fts (content, trace_id, created_at) "
            "SELECT content, trace_id, created_at FROM context_dumps"
        )
        db.commit()
        print(f"  [db] backfilled {real_count} rows into context_dumps_fts")

    # Migration: drop old context_dumps if it uses the legacy schema (raw_text column)
    cols = {row[1] for row in db.execute("PRAGMA table_info(context_dumps)").fetchall()}
    if "archived" not in cols:
        db.execute("ALTER TABLE context_dumps ADD COLUMN archived INTEGER DEFAULT 0")
        db.commit()
        print("  [db] added 'archived' column to context_dumps")

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
