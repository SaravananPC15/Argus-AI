"""
calendar_agent.py — Feature 8: Calendar integration.

Keeps things dependency-light and fully local: events are stored in a
plain JSON file rather than requiring a Google/Outlook OAuth flow.
brain.py routes natural-language requests here ("what's on my calendar
tomorrow", "add a dentist appointment Friday at 3pm") via the
"calendar" action, and this module does the light NLP-assisted parsing
using the same fast local model everything else uses.
"""

import json
import os
from datetime import datetime, timedelta
import ollama
import model_router

CALENDAR_FILE = "argus_calendar.json"


def _load_events():
    if not os.path.exists(CALENDAR_FILE):
        return []
    try:
        with open(CALENDAR_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_events(events):
    with open(CALENDAR_FILE, "w") as f:
        json.dump(events, f, indent=2)


def add_event(title: str, when_iso: str) -> dict:
    """Adds an event. when_iso should be an ISO-8601 datetime string."""
    events = _load_events()
    event = {"title": title, "when": when_iso}
    events.append(event)
    events.sort(key=lambda e: e["when"])
    _save_events(events)
    try:
        import nexus_graph
        nexus_graph.add_node(f"event:{title}:{when_iso}", title, "event", {"when": when_iso})
    except Exception:
        pass
    return event


def list_events(on_date: str = None):
    """Returns events, optionally filtered to a single date (YYYY-MM-DD)."""
    events = _load_events()
    if on_date:
        return [e for e in events if e["when"].startswith(on_date)]
    return events


def _parse_request(natural_language_request: str) -> dict:
    """Uses the fast local model to turn a natural-language calendar
    request into structured intent + fields."""
    now = datetime.now()
    prompt = f"""
    You convert calendar requests into JSON. Today's date/time is {now.isoformat()}.
    Output ONLY valid JSON with keys:
    - "intent": either "add" or "list"
    - "title": the event title (for "add")
    - "when": an ISO-8601 datetime string, e.g. "{now.year}-01-15T15:00:00" (for "add")
    - "date": a YYYY-MM-DD date to filter by, or null for all events (for "list")

    Request: "{natural_language_request}"
    """
    try:
        response = ollama.chat(
            model=model_router.select_model("calendar"),
            messages=[{'role': 'system', 'content': prompt}],
            format='json'
        )
        return json.loads(response['message']['content'].strip())
    except Exception as e:
        print(f"[Calendar Parse Error]: {e}")
        return {"intent": "list", "date": None}


def handle_calendar_request(natural_language_request: str) -> str:
    """Entry point called by executor.py for the 'calendar' action."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("calendar_email"):
            return "Calendar & Email is currently toggled off in the control center."
    except Exception:
        pass

    parsed = _parse_request(natural_language_request)
    intent = parsed.get("intent", "list")

    if intent == "add":
        title = parsed.get("title", "Untitled event")
        when = parsed.get("when")
        if not when:
            return "I understood you want to add an event, but couldn't pin down the time, macha."
        add_event(title, when)
        try:
            friendly_time = datetime.fromisoformat(when).strftime("%A %B %d at %I:%M %p")
        except ValueError:
            friendly_time = when
        return f"Locked in, macha. '{title}' is on the calendar for {friendly_time}."

    # intent == "list"
    date_filter = parsed.get("date")
    events = list_events(date_filter)
    if not events:
        return "Your calendar's clear, bro. Nothing scheduled." if date_filter else "Your calendar is completely empty right now."

    lines = []
    for e in events[:5]:
        try:
            friendly_time = datetime.fromisoformat(e["when"]).strftime("%a %b %d, %I:%M %p")
        except ValueError:
            friendly_time = e["when"]
        lines.append(f"{e['title']} on {friendly_time}")
    return "Here's what's on deck: " + "; ".join(lines) + "."
