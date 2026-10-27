"""The tools the model can call, their JSON schemas, and a safe dispatcher.

Every tool returns a plain dict that is sent back to the model as JSON.
Errors are returned as {"error": ...} results instead of exceptions, so a
bad booking number or malformed arguments never crash the agent loop.
"""

import json
from datetime import datetime
from typing import Any, Callable

from helpdesk.bookings import BookingRepository
from helpdesk.config import NOW, SHOP_TZ
from helpdesk.policy_search import PolicySearch
from helpdesk.refund import calculate_refund

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_policies",
            "description": (
                "Search the CityWheels policy documents (prices, cancellations and refunds, FAQ: "
                "opening hours, age limits, payment, accidents, ...). Returns the most relevant "
                "sections. Use it for every question about the shop's rules or prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, in English keywords or a short question."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking",
            "description": "Get the details of one booking by its booking number, e.g. CW-1002.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string", "description": "Booking number such as CW-1002."},
                },
                "required": ["booking_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_refund",
            "description": (
                "Calculate exactly how much money a customer gets back if they cancel a booking. "
                "Always use this for refund amounts; never calculate them yourself. "
                "By default the cancellation time is now; pass cancel_at for a different moment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string", "description": "Booking number such as CW-1002."},
                    "cancel_at": {
                        "type": "string",
                        "description": (
                            "Optional. When the customer would cancel, as ISO 8601, "
                            "e.g. 2026-06-11T09:00:00+02:00. Omit to cancel now."
                        ),
                    },
                },
                "required": ["booking_id"],
            },
        },
    },
]


def _not_found(booking_id: Any) -> dict:
    return {
        "error": "booking_not_found",
        "booking_id": booking_id,
        "message": f"No booking with number '{booking_id}' exists. Do not guess its details.",
    }


def _parse_cancel_at(value: str | None) -> datetime:
    if not value:
        return NOW
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # Times without an offset are shop-local times.
        parsed = parsed.replace(tzinfo=SHOP_TZ)
    return parsed


class ToolRegistry:
    def __init__(self, bookings: BookingRepository | None = None, search: PolicySearch | None = None):
        self.bookings = bookings or BookingRepository()
        self.search = search or PolicySearch()
        self._functions: dict[str, Callable[..., dict]] = {
            "search_policies": self.search_policies,
            "get_booking": self.get_booking,
            "calculate_refund": self.calculate_refund,
        }

    @property
    def schemas(self) -> list[dict]:
        return TOOL_SCHEMAS

    # --- tools -------------------------------------------------------------

    def search_policies(self, query: str) -> dict:
        results = self.search.search(query)
        if not results:
            return {"results": [], "message": "No relevant section found in the CityWheels documents."}
        return {"results": results}

    def get_booking(self, booking_id: str) -> dict:
        booking = self.bookings.get(booking_id)
        return {"booking": booking} if booking else _not_found(booking_id)

    def calculate_refund(self, booking_id: str, cancel_at: str | None = None) -> dict:
        booking = self.bookings.get(booking_id)
        if not booking:
            return _not_found(booking_id)
        try:
            when = _parse_cancel_at(cancel_at)
        except ValueError:
            return {"error": "invalid_cancel_at", "message": f"Could not read the date/time '{cancel_at}'. Use ISO 8601."}
        if when < NOW:
            return {"error": "cancel_at_in_past", "message": f"The cancellation time must not be before now ({NOW.isoformat()})."}
        result = calculate_refund(booking, when).to_dict()
        result["cancel_at"] = when.isoformat()
        return result

    # --- dispatch ----------------------------------------------------------

    def execute(self, name: str, arguments: dict | str) -> dict:
        """Run a tool by name with model-provided arguments, never raising.

        The model may call an unknown tool, send invalid JSON or miss a
        required argument; each case becomes an error result the model can
        read and recover from (e.g. ask the customer for the booking number).
        """
        func = self._functions.get(name)
        if func is None:
            return {"error": "unknown_tool", "message": f"There is no tool called '{name}'."}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return {"error": "invalid_arguments", "message": "Arguments were not valid JSON."}
        if not isinstance(arguments, dict):
            return {"error": "invalid_arguments", "message": "Arguments must be a JSON object."}
        try:
            return func(**arguments)
        except TypeError as exc:
            return {"error": "invalid_arguments", "message": str(exc)}
        except Exception as exc:  # last line of defence: report, don't crash
            return {"error": "tool_failed", "message": f"{type(exc).__name__}: {exc}"}
