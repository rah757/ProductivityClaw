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

# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def _parse_ns_date(date_str: str, time_str: str):
    """Parse YYYY-MM-DD + time string into an NSDate.

    Accepts both 24-hour (HH:MM) and 12-hour (H:MM AM/PM) formats so
    the function is robust to whatever the LLM happens to produce.
    """
    from Foundation import NSDate
    time_str = time_str.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p"):
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", fmt)
            return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse time '{time_str}' -- expected HH:MM (24h) or H:MM AM/PM"
    )


def find_event_identifier(title: str, date_str: str) -> str | None:
    """Search the live EventKit store for an event matching title + date.

    Returns EKEvent.eventIdentifier() or None if not found.
    Case-insensitive title match.
    """
    try:
        from Foundation import NSDate
        day_start = datetime.strptime(date_str, "%Y-%m-%d")
        day_end   = day_start + timedelta(days=1)
        ns_start  = NSDate.dateWithTimeIntervalSince1970_(day_start.timestamp())
        ns_end    = NSDate.dateWithTimeIntervalSince1970_(day_end.timestamp())
        predicate = _event_store.predicateForEventsWithStartDate_endDate_calendars_(
            ns_start, ns_end, None
        )
        events = _event_store.eventsMatchingPredicate_(predicate)
        for e in events:
            if e.title() and e.title().lower() == title.lower():
                return str(e.eventIdentifier())
        return None
    except Exception as ex:
        print(f"  [find_event_identifier] error: {ex}")
        return None


def create_event(
    title: str,
    date_str: str,
    start_time: str,
    end_time: str,
    calendar_name: str | None = None,
    location: str | None = None,
) -> str:
    """Create a new event via EventKit. Returns event_identifier.

    Args:
        date_str:   YYYY-MM-DD
        start_time: HH:MM (24h)
        end_time:   HH:MM (24h)
    """
    event = EventKit.EKEvent.eventWithEventStore_(_event_store)
    event.setTitle_(title)
    event.setStartDate_(_parse_ns_date(date_str, start_time))
    event.setEndDate_(_parse_ns_date(date_str, end_time))

    if location:
        event.setLocation_(location)

    # Pick calendar by name or fall back to default
    cal = None
    if calendar_name:
        for c in _event_store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
            if str(c.title()).lower() == calendar_name.lower():
                cal = c
                break
    if cal is None:
        cal = _event_store.defaultCalendarForNewEvents()
    event.setCalendar_(cal)

    error_ptr = None
    success = _event_store.saveEvent_span_commit_error_(
        event, EventKit.EKSpanThisEvent, True, error_ptr
    )
    if not success:
        raise RuntimeError(f"EventKit saveEvent failed for '{title}'")

    event_id = str(event.eventIdentifier())
    print(f"  [create_event] created '{title}' on {date_str} ({event_id[:8]}...)")
    return event_id


def move_event(
    event_identifier: str,
    new_date_str: str,
    new_start_time: str,
    new_end_time: str,
) -> bool:
    """Move an existing event to a new date/time by EventKit identifier.

    Args:
        new_date_str:    YYYY-MM-DD
        new_start_time:  HH:MM (24h)
        new_end_time:    HH:MM (24h)
    """
    event = _event_store.eventWithIdentifier_(event_identifier)
    if event is None:
        raise ValueError(f"Event not found: {event_identifier}")

    event.setStartDate_(_parse_ns_date(new_date_str, new_start_time))
    event.setEndDate_(_parse_ns_date(new_date_str, new_end_time))

    error_ptr = None
    success = _event_store.saveEvent_span_commit_error_(
        event, EventKit.EKSpanThisEvent, True, error_ptr
    )
    if not success:
        raise RuntimeError(f"EventKit saveEvent failed for move ({event_identifier[:8]}...)")

    print(f"  [move_event] moved event to {new_date_str} {new_start_time}-{new_end_time}")
    return True


# ---------------------------------------------------------------------------

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
