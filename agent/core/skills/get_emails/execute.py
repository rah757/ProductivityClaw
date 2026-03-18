"""Fetch and display recent emails from processed_emails + live fetch if needed."""

from datetime import datetime, timedelta
from agent.memory.database import db


def execute(timeframe: str = "today", filter: str = "all") -> str:
    """Return recent emails. Checks processed_emails first, triggers live fetch if empty."""
    timeframe = (timeframe or "today").strip().lower()
    filter = (filter or "all").strip().lower()

    # Determine cutoff
    if timeframe == "today":
        cutoff = datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
        label = "today"
    else:  # recent = last 7 days
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        label = "last 7 days"

    # Query processed_emails
    query = "SELECT subject, sender, classification, summary, processed_at FROM processed_emails WHERE processed_at >= ?"
    params = [cutoff]

    if filter == "high":
        query += " AND classification = 'HIGH'"
    elif filter == "low":
        query += " AND classification = 'LOW'"
    elif filter != "all":
        query += " AND classification != 'NOISE'"

    query += " ORDER BY processed_at DESC LIMIT 20"
    rows = db.execute(query, params).fetchall()

    if not rows:
        # Try live fetch + classify if no processed emails
        try:
            from agent.integrations.apple_mail import get_unprocessed_emails, classify_emails
            from agent.memory.context_store import store_context_dump

            hours = 24 if timeframe == "today" else 168
            new_emails = get_unprocessed_emails(hours=hours)
            if new_emails:
                classified = classify_emails(new_emails)
                for item in classified:
                    context_dump_id = None
                    cls = item["classification"]
                    if cls in ("HIGH", "LOW"):
                        context_dump_id = store_context_dump(
                            trace_id=f"email-{item['message_id'][:8]}",
                            content=f"[{cls}] {item['summary']}",
                            source="email",
                        )
                    db.execute(
                        "INSERT OR IGNORE INTO processed_emails "
                        "(message_id, subject, sender, account_name, classification, summary, context_dump_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (item["message_id"], item["subject"], item["sender"],
                         item.get("account", ""), cls, item["summary"], context_dump_id),
                    )
                db.commit()

                # Re-query
                rows = db.execute(query, params).fetchall()
        except Exception as e:
            return f"No processed emails found and live fetch failed: {e}"

    if not rows:
        return f"No emails found for {label}."

    lines = [f"EMAILS ({label}) — {len(rows)} total:"]
    for r in rows:
        subject, sender, cls, summary, ts = r
        icon = {"HIGH": "🔴", "LOW": "🔵", "NOISE": "⚪"}.get(cls, "⚪")
        # Use summary if available, otherwise subject
        display = summary or subject
        sender_short = sender.split("<")[0].strip() if "<" in sender else sender
        lines.append(f"  {icon} [{cls}] {display}")
        lines.append(f"     From: {sender_short}")

    high_count = sum(1 for r in rows if r[2] == "HIGH")
    if high_count:
        lines.append(f"\n⚠️ {high_count} email(s) need attention.")

    return "\n".join(lines)
