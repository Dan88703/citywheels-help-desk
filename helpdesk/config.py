"""Shared configuration: data location and the fixed "current date".

The data README says to treat 2026-06-10 09:00 Europe/Warsaw (UTC+02:00) as
"now", so every answer is reproducible. We use a fixed UTC offset instead of
ZoneInfo("Europe/Warsaw") on purpose: ZoneInfo needs the `tzdata` package on
Windows, and the README states the offset explicitly anyway.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHOP_TZ = timezone(timedelta(hours=2), name="Europe/Warsaw (UTC+02:00)")

# Fixed "now" for the whole application.
NOW = datetime(2026, 6, 10, 9, 0, tzinfo=SHOP_TZ)

# data/ lives next to the package; can be overridden for tests.
DATA_DIR = Path(os.getenv("HELPDESK_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
BOOKINGS_FILE = DATA_DIR / "bookings.json"
POLICIES_DIR = DATA_DIR / "policies"

STAFF_CONTACT = "help@citywheels.example or +48 000 000 000"
