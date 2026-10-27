"""Read-only access to data/bookings.json."""

import json
import re
from pathlib import Path

from helpdesk.config import BOOKINGS_FILE

# Accepts "CW-1002", "cw1002", "CW 1002" and plain "1002".
_ID_PATTERN = re.compile(r"^(?:CW)?[\s\-_]*(\d+)$", re.IGNORECASE)


def normalize_booking_id(raw: str) -> str | None:
    """Turn user-typed booking numbers into the canonical "CW-1234" form.

    Customers (and the model) do not always type the id exactly, so we accept
    a few harmless variants. Anything else returns None, which the caller
    reports as "not found" instead of guessing.
    """
    if not isinstance(raw, str):
        return None
    match = _ID_PATTERN.match(raw.strip())
    return f"CW-{match.group(1)}" if match else None


class BookingRepository:
    def __init__(self, path: Path = BOOKINGS_FILE):
        with open(path, encoding="utf-8") as f:
            self._bookings = {b["id"].upper(): b for b in json.load(f)}

    def get(self, booking_id: str) -> dict | None:
        canonical = normalize_booking_id(booking_id)
        if canonical is None:
            return None
        booking = self._bookings.get(canonical)
        # Return a copy so callers cannot mutate the "database".
        return dict(booking) if booking else None
