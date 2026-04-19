"""Manual test: authenticates with Google and prints today's calendar events."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # add project root to path

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from gcal.client import get_events

load_dotenv()

tz = ZoneInfo(os.environ.get("TIMEZONE", "America/Toronto"))
now = datetime.now(tz)
start = now.replace(hour=0, minute=0, second=0, microsecond=0)
end = start + timedelta(days=1)

print(f"Fetching events for {start.date()} ...")
events = get_events(start, end)

if not events:
    print("No events today.")
else:
    for e in events:
        time = e["start"].get("dateTime", e["start"].get("date", "all-day"))
        print(f"  {time}  —  {e.get('summary', '(no title)')}")
