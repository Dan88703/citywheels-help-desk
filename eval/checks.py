"""Automatic checks for one evaluation case. Pure functions, unit-tested."""

import json
import re
from dataclasses import dataclass, field

from helpdesk.config import POLICIES_DIR

NUMBER = re.compile(r"\d+(?:[.,]\d{1,2})?")
# An amount of money: "340 EUR", "340.00 €", "€340", "EUR 340", "340 euros".
MONEY = re.compile(
    r"(?:(?:€|EUR)\s*(\d+(?:[.,]\d{1,2})?))|(?:(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR|euros?))",
    re.IGNORECASE,
)
STAFF_MARKERS = ["help@citywheels.example", "+48 000 000 000", "staff"]


@dataclass
class CheckOutcome:
    passed: bool
    failures: list[str] = field(default_factory=list)


# Models often write typographic characters: "can’t" with U+2019 instead of
# "can't", "CW‑1008" with a non-breaking hyphen U+2011. Plain substring checks
# then miss correct answers, so we map them to ASCII before checking.
_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    " ": " ", " ": " ",
})


def normalize(text: str) -> str:
    return text.translate(_TYPOGRAPHIC)


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def numbers_in(text: str) -> set[float]:
    return {_to_float(n) for n in NUMBER.findall(text)}


def money_amounts_in(text: str) -> set[float]:
    return {_to_float(a or b) for a, b in MONEY.findall(text)}


def _collect_numbers(value, out: set[float]) -> None:
    """Every number anywhere in a tool result: values and numbers inside strings."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, str):
        out.update(numbers_in(value))
    elif isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_numbers(v, out)


def policy_numbers() -> set[float]:
    out: set[float] = set()
    for path in POLICIES_DIR.glob("*.md"):
        out.update(numbers_in(path.read_text(encoding="utf-8")))
    return out


def check_case(case: dict, answer: str, called_tools: list[str], tool_results: list[dict],
               questions: list[str], known_numbers: set[float]) -> CheckOutcome:
    """Compare one agent answer with the expectations of its eval case."""
    failures = []
    answer = normalize(answer)
    lower = answer.lower()

    for tool in case.get("tools", []):
        if tool not in called_tools:
            failures.append(f"tool `{tool}` not called")
    any_tool = case.get("any_tool")
    if any_tool and not set(any_tool) & set(called_tools):
        failures.append(f"none of {any_tool} called")

    answer_numbers = numbers_in(answer)
    for amount in case.get("amounts", []):
        if float(amount) not in answer_numbers:
            failures.append(f"amount {amount} missing")

    for item in case.get("must_contain", []):
        options = item if isinstance(item, list) else [item]
        if not any(o.lower() in lower for o in options):
            failures.append(f"missing one of {options}")

    for text in case.get("must_not_contain", []):
        if text.lower() in lower:
            failures.append(f"contains forbidden `{text}`")

    if case.get("refusal") and not any(m.lower() in lower for m in STAFF_MARKERS):
        failures.append("does not refer the customer to the staff")

    # Grounding: an EUR amount the model wrote must come from somewhere real.
    allowed = set(known_numbers)
    for result in tool_results:
        _collect_numbers(result, allowed)
    for q in questions:
        allowed.update(numbers_in(q))
    ungrounded = sorted(a for a in money_amounts_in(answer) if a not in allowed)
    if ungrounded:
        failures.append(f"ungrounded amounts {ungrounded}")

    return CheckOutcome(passed=not failures, failures=failures)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
