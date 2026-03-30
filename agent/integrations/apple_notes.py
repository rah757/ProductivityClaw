"""Apple Notes integration via ScriptingBridge.
Fetches notes from all accounts/folders, stores in context_dumps with source='notes'."""

import hashlib
import re
import time
from datetime import datetime, timedelta

from agent.memory.database import db
from agent.memory.context_store import store_context_dump

# ── Cache ────────────────────────────────────────────────────────
_notes_cache: dict = {"notes": [], "timestamp": 0}
_CACHE_TTL = 300  # 5 min


# ── Helpers ──────────────────────────────────────────────────────

def _nsdate_to_datetime(nsdate) -> datetime | None:
    if nsdate is None:
        return None
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970())


def _strip_html(html: str) -> str:
    """Strip HTML tags from Notes body, collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _note_id(note) -> str:
    """Stable unique ID for dedup. Uses note name + modification date hash."""
    try:
        nid = note.id()
        if nid:
            return str(nid)
    except Exception:
        pass
    raw = f"{note.name()}{note.modificationDate()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Fetch ────────────────────────────────────────────────────────

def fetch_all_notes(modified_since_days: int = 90) -> list[dict]:
    """Fetch notes modified within the last N days from all accounts.
    Returns list of dicts with note_id, title, body, folder, account, modified_at.
    Uses 5-min TTL cache."""
    now = time.time()
    if now - _notes_cache["timestamp"] < _CACHE_TTL and _notes_cache["notes"]:
        return _notes_cache["notes"]

    from ScriptingBridge import SBApplication

    app = SBApplication.applicationWithBundleIdentifier_("com.apple.Notes")
    if app is None:
        print("  [notes] Apple Notes not available")
        return []

    cutoff = datetime.now() - timedelta(days=modified_since_days)
    results = []

    for account in app.accounts():
        acct_name = str(account.name())
        for folder in account.folders():
            folder_name = str(folder.name())
            for note in folder.notes():
                modified = _nsdate_to_datetime(note.modificationDate())
                if modified and modified < cutoff:
                    continue

                # Get body text — plaintext() is preferred, body() returns HTML
                body = ""
                try:
                    body = str(note.plaintext() or "")
                except Exception:
                    try:
                        body = _strip_html(str(note.body() or ""))
                    except Exception:
                        pass

                if not body.strip():
                    continue

                results.append({
                    "note_id": _note_id(note),
                    "title": str(note.name() or "(untitled)"),
                    "body": body,
                    "folder": folder_name,
                    "account": acct_name,
                    "modified_at": modified.isoformat() if modified else "",
                })

    _notes_cache["notes"] = results
    _notes_cache["timestamp"] = now
    print(f"  [notes] fetched {len(results)} notes from {len(app.accounts())} accounts")
    return results


def get_unprocessed_notes(modified_since_days: int = 90) -> list[dict]:
    """Fetch notes minus those already stored in context_dumps."""
    all_notes = fetch_all_notes(modified_since_days=modified_since_days)
    if not all_notes:
        return []

    # Check which note_ids already exist in context_dumps (source='notes')
    nids = [n["note_id"] for n in all_notes]
    placeholders = ",".join("?" * len(nids))
    rows = db.execute(
        f"SELECT trace_id FROM context_dumps WHERE source = 'notes' AND trace_id IN ({placeholders})",
        nids,
    ).fetchall()
    seen = {r[0] for r in rows}

    return [n for n in all_notes if n["note_id"] not in seen]


# ── Ingest ───────────────────────────────────────────────────────

def ingest_notes(modified_since_days: int = 90) -> int:
    """Fetch unprocessed notes and store them as context_dumps.
    Returns the number of new notes ingested."""
    unprocessed = get_unprocessed_notes(modified_since_days=modified_since_days)
    if not unprocessed:
        print("  [notes] no new notes to ingest")
        return 0

    count = 0
    for note in unprocessed:
        # Build content with metadata header
        content = f"[Note] {note['title']}\n"
        content += f"Folder: {note['folder']} | Account: {note['account']}\n"
        content += f"Modified: {note['modified_at']}\n\n"
        content += note["body"]

        store_context_dump(
            trace_id=note["note_id"],
            content=content,
            source="notes",
        )
        count += 1

    print(f"  [notes] ingested {count} new notes into context_dumps")
    return count
