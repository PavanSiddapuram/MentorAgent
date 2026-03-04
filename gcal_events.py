"""
Google Calendar Event Creator – MentorAgent
-------------------------------------------
Creates color-coded daily study events in Google Calendar.

Color coding logic (applied by caller / orchestrator):
    Blue   (colorId=9)  → Build / code / implement tasks
    Yellow (colorId=5)  → Read / research / paper tasks
    Green  (colorId=2)  → Reflect / write / review tasks

Usage:
    from gcal_events import create_study_event

    event = create_study_event(
        title="AI Sprint – Threshold Sweep",
        date="2026-03-03",       # YYYY-MM-DD
        start_time="09:00",     # 24h format, user's local timezone
        duration_minutes=60,
        color="blue",            # "blue" | "yellow" | "green"
        description="Core Task: Implement threshold sweep 0.4–0.9\\n\\nReading: HuggingFace eval metrics blog",
    )
    print(event["htmlLink"])

Environment variables:
    GOOGLE_SHEETS_CREDENTIALS_FILE  - Path to credentials.json (OAuth or service account)
    CALENDAR_ID                      - Target calendar ID (default: "primary")
    TIMEZONE                         - e.g., "America/New_York"

OAuth scope required: https://www.googleapis.com/auth/calendar.events
If token.json was created without this scope, delete it and re-auth.
"""

import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv(Path(__file__).resolve().parent / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar.events",
]

CREDENTIALS_FILE = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_FILE",
    str(Path(__file__).resolve().parent / "credentials.json"),
)
TOKEN_FILE = str(Path(__file__).resolve().parent / "token.json")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

COLOR_MAP = {
    "blue": "9",       # Blueberry
    "yellow": "5",     # Banana
    "green": "2",      # Sage
    "red": "11",       # Tomato
    "purple": "3",     # Grape
    "cyan": "7",       # Peacock
}

TOPIC_COLOR_KEYWORDS = {
    "blue": ["implement", "build", "code", "script", "run", "create", "develop", "train"],
    "yellow": ["read", "paper", "blog", "course", "study", "research", "watch", "review"],
    "green": ["reflect", "write", "document", "plan", "summarize", "journal"],
}


def infer_color(topic: str) -> str:
    """
    Infer calendar color from topic keywords.
    Returns 'blue', 'yellow', or 'green'.
    """
    topic_lower = topic.lower()
    for color, keywords in TOPIC_COLOR_KEYWORDS.items():
        if any(kw in topic_lower for kw in keywords):
            return color
    return "blue"  # default to build/code color


def get_credentials() -> Credentials:
    """
    Load or refresh Google OAuth credentials.
    Requires calendar.events scope — re-auth if token.json was created without it.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[GCal] Token refresh failed: {e}. Re-authenticating...")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_FILE}. "
                    "Download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        print("[GCal] Token saved.")

    return creds


def create_study_event(
    title: str,
    date: str,
    start_time: str = "09:00",
    duration_minutes: int = 60,
    color: str = None,
    description: str = "",
    calendar_id: str = None,
) -> dict:
    """
    Create a Google Calendar event for a study/build session.

    Args:
        title: Event title, e.g. "AI Sprint – Threshold Sweep"
        date: Date string in YYYY-MM-DD format
        start_time: Start time in HH:MM (24h), e.g. "09:00"
        duration_minutes: Event duration in minutes (default: 60)
        color: "blue", "yellow", "green" (auto-inferred from title if None)
        description: Event description with task + reading details
        calendar_id: Target calendar (default: "primary")

    Returns:
        The created event dict (includes htmlLink)
    """
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Parse start datetime
    start_dt = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Infer color if not provided
    if color is None:
        color = infer_color(title)
    color_id = COLOR_MAP.get(color, "9")

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": TIMEZONE,
        },
        "colorId": color_id,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    cal_id = calendar_id or CALENDAR_ID

    try:
        event = service.events().insert(calendarId=cal_id, body=event_body).execute()
        print(f"[GCal] Event created: {event.get('htmlLink')}")
        return event
    except Exception as e:
        print(f"[GCal] Failed to create event: {e}")
        # Non-blocking — return partial info instead of raising
        return {"error": str(e), "title": title, "date": date}


def create_deep_work_event(
    title: str,
    date: str,
    start_time: str = "21:00",
    duration_minutes: int = 90,
    description: str = "",
) -> dict:
    """
    Create an optional deep work block in the evening.
    Default: 9 PM, 90 minutes, cyan color.
    """
    return create_study_event(
        title=f"[Deep Work] {title}",
        date=date,
        start_time=start_time,
        duration_minutes=duration_minutes,
        color="cyan",
        description=description,
    )


# ── CLI convenience ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a study event in Google Calendar")
    parser.add_argument("--title", required=True, help="Event title")
    parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    parser.add_argument("--start", default="09:00", help="Start time HH:MM (default: 09:00)")
    parser.add_argument("--duration", type=int, default=60, help="Duration in minutes")
    parser.add_argument(
        "--color",
        choices=["blue", "yellow", "green", "red", "purple", "cyan"],
        help="Event color (auto-inferred if not set)",
    )
    parser.add_argument("--description", default="", help="Event description")
    args = parser.parse_args()

    event = create_study_event(
        title=args.title,
        date=args.date,
        start_time=args.start,
        duration_minutes=args.duration,
        color=args.color,
        description=args.description,
    )
    print(event.get("htmlLink", event))
