from datetime import datetime, timedelta
from agent.integrations.apple_calendar import fetch_all_events, fetch_all_reminders

def filter_events(all_events, start_str, end_str):
    """Filter pre-fetched events by date range (YYYY-MM-DD strings)."""
    return [e for e in all_events if start_str <= e["date"] < end_str]

def execute(timeframe: str) -> str:
    """Execute the calendar fetch based on the requested timeframe."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Normalize: "this week" → "this_week", strip whitespace
    timeframe = timeframe.strip().lower().replace(" ", "_")

    # Note: EventKit fetches must have been warmed up by main.py in real usage,
    # but for testing, this will trigger a synchronous fetch.
    all_events = fetch_all_events()
    reminders = fetch_all_reminders()

    sections = []

    if timeframe == "today":
        today_str = today_start.strftime("%Y-%m-%d")
        tomorrow_str = (today_start + timedelta(days=1)).strftime("%Y-%m-%d")
        events = filter_events(all_events, today_str, tomorrow_str)
        if events:
            lines = [f"TODAY ({now.strftime('%A, %B %d')}):"]
            for e in events:
                line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
                if e['location']: line += f" @ {e['location']}"
                lines.append(line)
            sections.append("\n".join(lines))
        else:
            sections.append(f"TODAY ({now.strftime('%A, %B %d')}): No events")

    elif timeframe == "tomorrow":
        tomorrow_str = (today_start + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after_str = (today_start + timedelta(days=2)).strftime("%Y-%m-%d")
        events = filter_events(all_events, tomorrow_str, day_after_str)
        if events:
            lines = [f"TOMORROW ({(now + timedelta(days=1)).strftime('%A, %B %d')}):"]
            for e in events:
                line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
                if e['location']: line += f" @ {e['location']}"
                lines.append(line)
            sections.append("\n".join(lines))
        else:
            sections.append("TOMORROW: No events")

    elif timeframe == "this_week":
        today_str = today_start.strftime("%Y-%m-%d")
        # End of week = next Sunday (or 7 days out, whichever is more)
        days_until_sunday = 6 - now.weekday()  # weekday(): Mon=0, Sun=6
        if days_until_sunday <= 0:
            days_until_sunday = 7  # if today is Sunday, show next 7 days
        week_end_str = (today_start + timedelta(days=max(days_until_sunday + 1, 7))).strftime("%Y-%m-%d")
        events = filter_events(all_events, today_str, week_end_str)
        if events:
            lines = ["THIS WEEK:"]
            for e in events:
                lines.append(f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]")
            sections.append("\n".join(lines))
        else:
            sections.append("THIS WEEK: No events")

    elif timeframe == "recent":
        past_week_str = (today_start - timedelta(days=7)).strftime("%Y-%m-%d")
        today_str = today_start.strftime("%Y-%m-%d")
        events = filter_events(all_events, past_week_str, today_str)
        if events:
            lines = ["RECENT (last 7 days):"]
            for e in events:
                lines.append(f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]")
            sections.append("\n".join(lines))
        else:
            sections.append("RECENT: No events")

    elif timeframe == "all":
        if all_events:
            lines = ["ALL EVENTS (past 7 days + next 14 days):"]
            for e in all_events:
                lines.append(f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]")
            sections.append("\n".join(lines))
        else:
            sections.append("ALL EVENTS: No calendar events")

    # Always append reminders
    if reminders:
        lines = ["REMINDERS:"]
        for r in reminders:
            line = f"  - {r['title']} [{r['list']}]"
            if r['due']: line += f" (due: {r['due']})"
            lines.append(line)
        sections.append("\n".join(lines))

    if not sections:
        return "No events or reminders found for this timeframe."
        
    return "\n\n".join(sections)
