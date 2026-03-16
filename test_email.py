"""Test Apple Mail.app email fetching via ScriptingBridge.
Read-only. Requires your email accounts to be added in System Settings → Internet Accounts.
"""

import time
from datetime import datetime, timedelta
from ScriptingBridge import SBApplication


def nsdate_to_datetime(nsdate):
    if nsdate is None:
        return None
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970())


# ── Test 1: Connect & list accounts ──────────────────────────────
print("=" * 50)
print("TEST 1: Accounts & Mailboxes")
print("=" * 50)

t0 = time.time()
mail = SBApplication.applicationWithBundleIdentifier_("com.apple.mail")

accounts = mail.accounts()
print(f"  Found {len(accounts)} account(s) in {time.time() - t0:.1f}s\n")

for account in accounts:
    name = account.name()
    emails = list(account.emailAddresses())
    print(f"  Account: {name}")
    print(f"  Emails:  {', '.join(str(e) for e in emails)}")
    for mb in account.mailboxes():
        unread = mb.unreadCount()
        marker = f" ({unread} unread)" if unread > 0 else ""
        print(f"    📁 {mb.name()}{marker}")
    print()


# ── Test 2: Fetch last 7 days from each INBOX ────────────────────
print("=" * 50)
print("TEST 2: Recent Emails (past 7 days, max 10 per account)")
print("=" * 50)

cutoff = datetime.now() - timedelta(days=7)
total_fetched = 0

for account in accounts:
    acct_name = str(account.name())
    inbox = None
    for mb in account.mailboxes():
        if str(mb.name()).upper() == "INBOX":
            inbox = mb
            break

    if inbox is None:
        print(f"\n  [{acct_name}] No INBOX found, skipping")
        continue

    print(f"\n  [{acct_name}] INBOX:")
    t0 = time.time()
    count = 0

    for msg in inbox.messages():
        date_received = nsdate_to_datetime(msg.dateReceived())
        if date_received and date_received < cutoff:
            break  # newest-first, safe to stop

        subject = str(msg.subject() or "(no subject)")
        sender = str(msg.sender() or "(unknown)")
        read = msg.readStatus()
        status = "  " if read else "🔵"

        date_str = date_received.strftime("%b %d %I:%M%p") if date_received else "?"
        print(f"    {status} {date_str}  {sender[:40]}")
        print(f"       {subject[:70]}")

        count += 1
        total_fetched += 1
        if count >= 10:
            print(f"    ... (showing first 10)")
            break

    elapsed = time.time() - t0
    print(f"    Fetched {count} in {elapsed:.1f}s")


# ── Test 3: Fetch one email body ──────────────────────────────────
print("\n" + "=" * 50)
print("TEST 3: Email Body (first email from first INBOX)")
print("=" * 50)

for account in accounts:
    inbox = None
    for mb in account.mailboxes():
        if str(mb.name()).upper() == "INBOX":
            inbox = mb
            break
    if inbox is None:
        continue

    t0 = time.time()
    for msg in inbox.messages():
        subject = str(msg.subject() or "(no subject)")
        # Force ScriptingBridge to resolve the content object
        content = msg.content()
        try:
            body = content.get() if hasattr(content, 'get') else str(content)
            body = str(body)[:500] if body else "(empty)"
        except Exception:
            body = "(could not read body)"
        elapsed = time.time() - t0

        print(f"  Subject: {subject}")
        print(f"  Body preview ({elapsed:.1f}s):")
        print(f"  {body[:500]}")
        break
    break


# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 50)
print(f"Total: {len(accounts)} accounts, {total_fetched} emails in past 7 days")
print("=" * 50)
