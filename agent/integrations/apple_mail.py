"""Apple Mail integration via ScriptingBridge.
Fetches emails from all accounts' INBOX, classifies via LLM, stores in context_dumps."""

import hashlib
import json
import re
import time
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agent.config import MLX_MODEL, MLX_BASE_URL
from agent.memory.database import db

# ── Cache ────────────────────────────────────────────────────────
_email_cache: dict = {"emails": [], "timestamp": 0}
_CACHE_TTL = 300  # 5 min, same as calendar


# ── Helpers ──────────────────────────────────────────────────────

def _nsdate_to_datetime(nsdate) -> datetime | None:
    """Convert macOS NSDate to Python datetime."""
    if nsdate is None:
        return None
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970())


def _get_message_id(msg) -> str:
    """Extract a stable unique ID for dedup.
    Prefers RFC 2822 Message-ID header; falls back to hash of metadata."""
    try:
        mid = msg.messageId()
        if mid:
            return str(mid)
    except Exception:
        pass
    # Fallback: hash subject + sender + date
    raw = f"{msg.subject()}{msg.sender()}{msg.dateReceived()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_body_preview(msg, max_chars: int = 500) -> str:
    """Extract email body text, truncated."""
    try:
        content = msg.content()
        body = content.get() if hasattr(content, "get") else str(content)
        return str(body)[:max_chars] if body else ""
    except Exception:
        return ""


# ── Fetch ────────────────────────────────────────────────────────

def fetch_recent_emails(hours: int = 24) -> list[dict]:
    """Fetch emails from all INBOX mailboxes received in the last `hours`.
    Returns list of dicts with message_id, subject, sender, date, body_preview, account.
    Uses 5-min TTL cache."""
    now = time.time()
    if now - _email_cache["timestamp"] < _CACHE_TTL and _email_cache["emails"]:
        return _email_cache["emails"]

    from ScriptingBridge import SBApplication

    mail = SBApplication.applicationWithBundleIdentifier_("com.apple.mail")
    if mail is None:
        print("  [email] Apple Mail not available")
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    results = []

    for account in mail.accounts():
        acct_name = str(account.name())

        # Find INBOX (case-insensitive)
        inbox = None
        for mb in account.mailboxes():
            if str(mb.name()).upper() == "INBOX":
                inbox = mb
                break
        if inbox is None:
            continue

        # Skip accounts with massive unread (Gmail backlog protection)
        try:
            if inbox.unreadCount() > 5000:
                print(f"  [email] skipping {acct_name} ({inbox.unreadCount()} unread)")
                continue
        except Exception:
            pass

        count = 0
        for msg in inbox.messages():
            date_received = _nsdate_to_datetime(msg.dateReceived())
            if date_received and date_received < cutoff:
                break  # newest-first, safe to stop

            results.append({
                "message_id": _get_message_id(msg),
                "subject": str(msg.subject() or "(no subject)"),
                "sender": str(msg.sender() or "(unknown)"),
                "date": date_received.isoformat() if date_received else "",
                "body_preview": _get_body_preview(msg),
                "account": acct_name,
            })

            count += 1
            if count >= 50:
                break

    _email_cache["emails"] = results
    _email_cache["timestamp"] = now
    print(f"  [email] fetched {len(results)} emails from {len(mail.accounts())} accounts")
    return results


def get_unprocessed_emails(hours: int = 24) -> list[dict]:
    """Fetch recent emails minus those already in processed_emails."""
    all_emails = fetch_recent_emails(hours=hours)
    if not all_emails:
        return []

    # Get already-processed message_ids
    mids = [e["message_id"] for e in all_emails]
    placeholders = ",".join("?" * len(mids))
    rows = db.execute(
        f"SELECT message_id FROM processed_emails WHERE message_id IN ({placeholders})",
        mids,
    ).fetchall()
    seen = {r[0] for r in rows}

    return [e for e in all_emails if e["message_id"] not in seen]


# ── LLM Classification ──────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are an email triage assistant. Classify each email and provide a one-line summary.

Classifications:
- HIGH: Requires action or attention today. Direct asks from real people, meeting changes, time-sensitive requests, important personal emails.
- LOW: Informative but not urgent. Newsletters, shipping notifications, receipts, FYI emails.
- NOISE: Automated junk, marketing, social media notifications, promotional offers.

Respond ONLY with a JSON array (no other text, no reasoning):
[{"id": 0, "classification": "HIGH", "summary": "one line summary here"}]

/no_think"""


def classify_emails(emails: list[dict]) -> list[dict]:
    """Classify a batch of emails via single LLM call.
    Returns list of dicts with message_id, classification, summary, subject, sender."""
    if not emails:
        return []

    # Build human message with numbered emails
    lines = ["Classify these emails:\n"]
    for i, e in enumerate(emails):
        date_str = ""
        if e.get("date"):
            try:
                dt = datetime.fromisoformat(e["date"])
                date_str = dt.strftime("%b %d %I:%M%p")
            except Exception:
                date_str = e["date"][:16]

        lines.append(f"Email {i}:")
        lines.append(f"From: {e['sender']}")
        lines.append(f"Subject: {e['subject']}")
        lines.append(f"Date: {date_str}")
        if e.get("body_preview"):
            lines.append(f"Body: {e['body_preview'][:500]}")
        lines.append("")

    llm = ChatOpenAI(
        base_url=MLX_BASE_URL,
        api_key="not-needed",
        model=MLX_MODEL,
        temperature=0.0,
        max_tokens=4000,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_CLASSIFY_SYSTEM),
            HumanMessage(content="\n".join(lines)),
        ])

        text = response.content or ""
        # Handle list-type content from MLX
        if isinstance(text, list):
            text = "".join(
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in text
            )

        # Try to find JSON in the full response BEFORE stripping think tags
        # (Qwen sometimes puts the answer inside <think> and returns empty outside)
        full_text = str(text)
        # Strip think tags for the clean version
        clean_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

        # Search for JSON array in clean text first, then full text as fallback
        json_str = None
        for candidate in [clean_text, full_text]:
            match = re.search(r"\[.*?\]", candidate, re.DOTALL)
            if match:
                json_str = match.group()
                break

        if json_str:
            classified = json.loads(json_str)
        else:
            print(f"  [email] no JSON found in response: {full_text[:200]}")
            raise ValueError("No JSON array in LLM response")

    except Exception as e:
        print(f"  [email] classification failed, defaulting to LOW: {e}")
        classified = [{"id": i, "classification": "LOW", "summary": em["subject"]}
                      for i, em in enumerate(emails)]

    # Merge classification back with email data
    results = []
    for item in classified:
        idx = item.get("id", 0)
        if idx < len(emails):
            email = emails[idx]
            results.append({
                "message_id": email["message_id"],
                "subject": email["subject"],
                "sender": email["sender"],
                "account": email.get("account", ""),
                "classification": item.get("classification", "LOW"),
                "summary": item.get("summary", email["subject"]),
            })

    return results
