"""
Mock calendar data for eval tests.

Events are generated relative to "today" so tests work regardless of run date.
Covers: today events, tomorrow events, this-week events, past events, reminders,
edge cases (all-day, no-location, multi-calendar).
"""

from datetime import datetime, timedelta


def _date_str(delta_days: int) -> str:
    """Return YYYY-MM-DD string for today +/- delta_days."""
    return (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def get_mock_events() -> list[dict]:
    """Return a fixed set of mock calendar events spanning past week to next week."""
    return [
        # --- PAST (last 3 days) ---
        {
            "title": "Team Standup",
            "time": "09:00 AM - 09:30 AM",
            "date": _date_str(-3),
            "calendar": "Work",
            "location": None,
            "description": None,
        },
        {
            "title": "Dentist Appointment",
            "time": "02:00 PM - 03:00 PM",
            "date": _date_str(-2),
            "calendar": "Personal",
            "location": "Downtown Dental Clinic",
            "description": "Regular cleaning",
        },
        {
            "title": "ML Paper Reading Group",
            "time": "04:00 PM - 05:30 PM",
            "date": _date_str(-1),
            "calendar": "School",
            "location": "Room 302 CS Building",
            "description": None,
        },

        # --- TODAY ---
        {
            "title": "Morning Workout",
            "time": "07:00 AM - 08:00 AM",
            "date": _date_str(0),
            "calendar": "Personal",
            "location": "Campus Gym",
            "description": None,
        },
        {
            "title": "1:1 with Advisor",
            "time": "10:00 AM - 10:30 AM",
            "date": _date_str(0),
            "calendar": "School",
            "location": "Professor's Office Room 412",
            "description": "Discuss thesis progress",
        },
        {
            "title": "Lunch with Alex",
            "time": "12:30 PM - 01:30 PM",
            "date": _date_str(0),
            "calendar": "Personal",
            "location": "Chipotle on Main St",
            "description": None,
        },
        {
            "title": "Sprint Planning",
            "time": "03:00 PM - 04:00 PM",
            "date": _date_str(0),
            "calendar": "Work",
            "location": None,
            "description": "Q2 sprint kickoff",
        },

        # --- TOMORROW ---
        {
            "title": "Career Fair",
            "time": "All day",
            "date": _date_str(1),
            "calendar": "School",
            "location": "Student Union Hall",
            "description": "Bring resume copies",
        },
        {
            "title": "Gym Session",
            "time": "06:00 PM - 07:00 PM",
            "date": _date_str(1),
            "calendar": "Personal",
            "location": "Campus Gym",
            "description": None,
        },

        # --- LATER THIS WEEK ---
        {
            "title": "Database Systems Midterm",
            "time": "09:00 AM - 11:00 AM",
            "date": _date_str(3),
            "calendar": "School",
            "location": "Lecture Hall A",
            "description": "Covers chapters 1-8",
        },
        {
            "title": "Dinner with Family",
            "time": "06:30 PM - 08:30 PM",
            "date": _date_str(5),
            "calendar": "Personal",
            "location": "Home",
            "description": None,
        },
    ]


def get_mock_reminders() -> list[dict]:
    """Return a fixed set of mock reminders."""
    return [
        {"title": "Submit internship application", "due": None, "list": "Tasks"},
        {"title": "Buy groceries", "due": None, "list": "Personal"},
        {"title": "Review PR #42", "due": None, "list": "Work"},
        {"title": "Call mom", "due": None, "list": "Personal"},
        {"title": "Finish ML homework", "due": None, "list": "School"},
    ]
