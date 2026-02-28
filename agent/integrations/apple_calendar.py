import time
import threading
import EventKit
from datetime import datetime, timedelta

_calendar_cache = {"events": None, "timestamp": 0}
_reminders_cache = {"reminders": [], "timestamp": 0}
CACHE_TTL_SECONDS = 300  # 5 minutes

# Global EventKit store (instantiate once)
_event_store = EventKit.EKEventStore.alloc().init()

def request_permissions():
    """Request EventKit permissions."""
    try:
        if hasattr(_event_store, 'requestFullAccessToEventsWithCompletion_'):
            _event_store.requestFullAccessToEventsWithCompletion_(lambda g, e: None)
        else:
            _event_store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, lambda g, e: None)
        _event_store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeReminder, lambda g, e: None)
        return True
    except Exception as e:
        print(f"WARNING: EventKit connection failed: {e}")
        return False

def _fetch_all_calendar_data():
    """Single connection: fetch events via native macOS EventKit. Caches for 5 min."""
    now = time.time()
    if _calendar_cache["timestamp"] > 0 and (now - _calendar_cache["timestamp"]) < CACHE_TTL_SECONDS:
        return

    try:
        t_start = time.time()
        start = datetime.now() - timedelta(days=7)
        end = datetime.now() + timedelta(days=14)

        from Foundation import NSDate
        ns_start = NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
        ns_end = NSDate.dateWithTimeIntervalSince1970_(end.timestamp())

        predicate = _event_store.predicateForEventsWithStartDate_endDate_calendars_(ns_start, ns_end, None)
        events = _event_store.eventsMatchingPredicate_(predicate)
        
        all_events = []
        for e in events:
            try:
                dtstart = datetime.fromtimestamp(e.startDate().timeIntervalSince1970())
                dtend = datetime.fromtimestamp(e.endDate().timeIntervalSince1970()) if e.endDate() else None
                
                if e.isAllDay():
                    time_str = "All day"
                    date_str = dtstart.strftime("%Y-%m-%d")
                else:
                    start_str = dtstart.strftime("%I:%M %p")
                    end_str = dtend.strftime("%I:%M %p") if dtend else "?"
                    time_str = f"{start_str} - {end_str}"
                    date_str = dtstart.strftime("%Y-%m-%d")

                all_events.append({
                    "title": str(e.title()) if e.title() else "No title",
                    "time": time_str,
                    "date": date_str,
                    "calendar": str(e.calendar().title()) if e.calendar() else "Unknown",
                    "location": str(e.location()) if e.location() else None,
                    "description": str(e.notes()) if e.notes() else None,
                })
            except Exception as ex:
                continue

        all_events.sort(key=lambda e: e["date"] + e["time"])
        _calendar_cache["events"] = all_events
        _calendar_cache["timestamp"] = time.time()
        ms = int((time.time() - t_start) * 1000)
        print(f"  [calendar] {ms}ms | {len(all_events)} events")

    except Exception as e:
        print(f"Calendar error: {e}")
        _calendar_cache["events"] = []
        _calendar_cache["timestamp"] = time.time()

def fetch_all_events():
    """Returns cached events (fetches if stale)."""
    _fetch_all_calendar_data()
    return _calendar_cache["events"] or []

def _fetch_reminders_eventkit():
    """Fetch reminders natively via macOS EventKit framework."""
    try:
        t0 = time.time()
        predicate = _event_store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, None)
        
        reminders_list = []
        fetch_event = threading.Event()
        
        def fetch_callback(reminders):
            if reminders:
                for r in reminders:
                    title = r.title()
                    cal_name = r.calendar().title() if r.calendar() else "Unknown"
                    reminders_list.append({"title": title, "due": None, "list": cal_name})
            fetch_event.set()
            
        _event_store.fetchRemindersMatchingPredicate_completion_(predicate, fetch_callback)
        fetch_event.wait(timeout=10)
        
        _reminders_cache["reminders"] = reminders_list
        _reminders_cache["timestamp"] = time.time()
        
        elapsed = int((time.time() - t0) * 1000)
        print(f"  [reminders] {elapsed}ms | {len(reminders_list)} reminders")

    except Exception as e:
        print(f"  [reminders] error: {e}")

def fetch_all_reminders():
    """Returns cached reminders."""
    # Ensure they are fetched if not yet cached
    if _reminders_cache["timestamp"] == 0:
        _fetch_reminders_eventkit()
    return _reminders_cache["reminders"]

def full_sync():
    """Full sync: calendar + reminders. Runs synchronously."""
    print("  [sync] starting full sync...")
    t0 = time.time()
    _calendar_cache["timestamp"] = 0  # force calendar re-fetch
    _fetch_all_calendar_data()
    _fetch_reminders_eventkit()
    print(f"  [sync] done in {(time.time() - t0) * 1000:.0f}ms | "
          f"{len(_calendar_cache['events'] or [])} events, "
          f"{len(_reminders_cache['reminders'])} reminders")
