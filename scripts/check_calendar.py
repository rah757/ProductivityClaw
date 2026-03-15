#!/usr/bin/env python3
"""
Diagnostic script to verify EventKit calendar access and event counts.
Run from project root: python scripts/check_calendar.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

def main():
    print("=== Calendar diagnostic ===\n")
    print(f"Current time (local): {datetime.now()}")
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Today range for filtering: {today_str} <= date < {tomorrow_str}\n")

    # 1. Request permissions and warm up
    from agent.integrations.apple_calendar import request_permissions, fetch_all_events, fetch_all_reminders
    print("Requesting EventKit permissions...")
    request_permissions()
    import time
    time.sleep(2)
    print("Warmed up.\n")

    # 2. Fetch raw events
    all_events = fetch_all_events()
    reminders = fetch_all_reminders()
    print(f"Raw fetch: {len(all_events)} events, {len(reminders)} reminders\n")

    if not all_events:
        print("⚠️  EventKit returned 0 events. Possible causes:")
        print("   - Calendar permission not granted for this Python process")
        print("   - Check: System Settings → Privacy & Security → Calendars")
        print("   - Try running from the same terminal/env as the bot")
        return

    # 3. Show today's events (same filter as the skill)
    today_events = [e for e in all_events if today_str <= e["date"] < tomorrow_str]
    print(f"Events for TODAY ({today_str}): {len(today_events)}")
    for e in today_events:
        print(f"  - {e['time']} | {e['title']} [{e['calendar']}]")
    if not today_events:
        print("  (none)")

    # 4. Show first 5 events overall (to verify data shape)
    print(f"\nFirst 5 events (all):")
    for e in all_events[:5]:
        print(f"  {e['date']} {e['time']} | {e['title']} [{e['calendar']}]")

if __name__ == "__main__":
    main()
