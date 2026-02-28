from datetime import datetime, timedelta
from agent.integrations.apple_calendar import fetch_all_events, fetch_all_reminders

def filter_events(all_events, start_str, end_str):
    """Filter pre-fetched events by date range (YYYY-MM-DD strings)."""
    return [e for e in all_events if start_str <= e["date"] < end_str]

def build_calendar_context():
    """Build a text summary of the user's calendar for the LLM."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_str = today_start.strftime("%Y-%m-%d")
    tomorrow_str = (today_start + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after_str = (today_start + timedelta(days=2)).strftime("%Y-%m-%d")
    week_end_str = (today_start + timedelta(days=7)).strftime("%Y-%m-%d")
    past_week_str = (today_start - timedelta(days=7)).strftime("%Y-%m-%d")

    all_events = fetch_all_events()

    sections = []

    # Recent past (last 7 days)
    past_events = filter_events(all_events, past_week_str, today_str)
    if past_events:
        lines = ["RECENT (last 7 days):"]
        for e in past_events:
            line = f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]"
            lines.append(line)
        sections.append("\n".join(lines))

    # Today
    today_events = filter_events(all_events, today_str, tomorrow_str)
    if today_events:
        lines = [f"TODAY ({now.strftime('%A, %B %d')}):"]
        for e in today_events:
            line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
            if e['location']:
                line += f" @ {e['location']}"
            lines.append(line)
        sections.append("\n".join(lines))
    else:
        sections.append(f"TODAY ({now.strftime('%A, %B %d')}): No events")

    # Tomorrow
    tomorrow_events = filter_events(all_events, tomorrow_str, day_after_str)
    if tomorrow_events:
        tomorrow_date = (now + timedelta(days=1)).strftime('%A, %B %d')
        lines = [f"TOMORROW ({tomorrow_date}):"]
        for e in tomorrow_events:
            line = f"  - {e['time']} | {e['title']} [{e['calendar']}]"
            if e['location']:
                line += f" @ {e['location']}"
            lines.append(line)
        sections.append("\n".join(lines))

    # Rest of week
    rest_events = filter_events(all_events, day_after_str, week_end_str)
    if rest_events:
        lines = ["THIS WEEK:"]
        for e in rest_events:
            line = f"  - {e['date']} {e['time']} | {e['title']} [{e['calendar']}]"
            lines.append(line)
        sections.append("\n".join(lines))

    # Reminders
    reminders = fetch_all_reminders()
    if reminders:
        lines = ["REMINDERS:"]
        for r in reminders:
            line = f"  - {r['title']} [{r['list']}]"
            if r['due']:
                line += f" (due: {r['due']})"
            lines.append(line)
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "No calendar data available."
