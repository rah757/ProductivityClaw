"""Test: can we fetch reminders from iCloud via CalDAV?"""

import os
from dotenv import load_dotenv
import caldav
import vobject

load_dotenv()

client = caldav.DAVClient(
    url="https://caldav.icloud.com",
    username=os.getenv("ICLOUD_USERNAME"),
    password=os.getenv("ICLOUD_APP_PASSWORD"),
)
principal = client.principal()

print("All calendars:")
for cal in principal.calendars():
    print(f"  - {cal.name} | URL: {cal.url}")

print("\n--- Trying todos on each calendar ---")
for cal in principal.calendars():
    try:
        todos = cal.todos(include_completed=False)
        print(f"{cal.name}: {len(todos)} incomplete todos")
        for todo in todos:
            print(f"  Raw data: {todo.data[:200]}")
            try:
                vcal = vobject.readOne(todo.data)
                vtodo = vcal.vtodo
                summary = vtodo.summary.value if hasattr(vtodo, "summary") else "?"
                print(f"  Parsed: {summary}")
            except Exception as e:
                print(f"  Parse error: {e}")
    except Exception as e:
        print(f"{cal.name}: {type(e).__name__}: {e}")