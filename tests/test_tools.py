"""Tests for the tools against the real data files, plus the dispatcher."""

import pytest

from helpdesk.bookings import normalize_booking_id
from helpdesk.tools import ToolRegistry


@pytest.fixture(scope="module")
def tools():
    return ToolRegistry()


# --- get_booking -------------------------------------------------------------

def test_get_booking_returns_details(tools):
    result = tools.get_booking("CW-1002")
    assert result["booking"]["bike_type"] == "e-bike"
    assert result["booking"]["deposit_eur"] == 300.0


@pytest.mark.parametrize("raw", ["cw-1002", "CW1002", "CW 1002", "1002", " CW-1002 "])
def test_get_booking_accepts_common_id_variants(tools, raw):
    assert tools.get_booking(raw)["booking"]["id"] == "CW-1002"


@pytest.mark.parametrize("raw", ["CW-9999", "XX-1002", "", "abc"])
def test_get_booking_unknown_id_is_clear_not_found(tools, raw):
    result = tools.get_booking(raw)
    assert result["error"] == "booking_not_found"
    assert "booking" not in result


def test_normalize_rejects_non_strings():
    assert normalize_booking_id(None) is None


# --- calculate_refund on the real bookings (now = 2026-06-10 09:00) ----------

@pytest.mark.parametrize(
    "booking_id, percent, total",
    [
        ("CW-1001", 100, 90.0),    # 73 h before start: 40 + 50 deposit
        ("CW-1002", 50, 340.0),    # 33 h: 40 + 300
        ("CW-1003", 0, 50.0),      # 6 h: deposit only
        ("CW-1004", 100, 73.0),    # voucher: 23 + 50
        ("CW-1007", 100, 186.0),   # exactly 48 h: boundary is inclusive
        ("CW-1009", 100, 169.0),   # 7-day rental, already discounted price
        ("CW-1010", 50, 170.0),    # exactly 24 h: 20 + 150
    ],
)
def test_refund_for_real_bookings(tools, booking_id, percent, total):
    result = tools.calculate_refund(booking_id)
    assert result["refund_percent"] == percent
    assert result["total_refund_eur"] == total


@pytest.mark.parametrize("booking_id", ["CW-1005", "CW-1006", "CW-1008"])
def test_refund_for_non_cancellable_real_bookings(tools, booking_id):
    result = tools.calculate_refund(booking_id)
    assert result["can_cancel"] is False and result["total_refund_eur"] == 0.0


def test_refund_unknown_booking(tools):
    assert tools.calculate_refund("CW-0000")["error"] == "booking_not_found"


def test_refund_with_later_cancel_time(tools):
    # CW-1001 starts 2026-06-13 10:00. Cancelling on 06-12 11:00 is 23 h before.
    result = tools.calculate_refund("CW-1001", cancel_at="2026-06-12T11:00:00+02:00")
    assert result["refund_percent"] == 0 and result["total_refund_eur"] == 50.0


def test_refund_naive_cancel_time_is_shop_local(tools):
    result = tools.calculate_refund("CW-1001", cancel_at="2026-06-11T10:00:00")
    assert result["hours_before_start"] == 48.0 and result["refund_percent"] == 100


def test_refund_rejects_past_and_invalid_times(tools):
    assert tools.calculate_refund("CW-1001", cancel_at="2026-06-01T10:00:00+02:00")["error"] == "cancel_at_in_past"
    assert tools.calculate_refund("CW-1001", cancel_at="next tuesday")["error"] == "invalid_cancel_at"


# --- search_policies ---------------------------------------------------------

@pytest.mark.parametrize(
    "query, expected_section",
    [
        ("What time do you open on Saturday?", "When are you open?"),
        ("How much is an e-bike for a whole day?", "Bike rental"),
        ("Can my 14-year-old rent an e-bike?", "Are there age limits?"),
        ("storm warning, can I get my money back?", "Bad weather"),
        ("what if I return the bike late", "Late return"),
        ("can I pay the deposit in cash", "How can I pay?"),
    ],
)
def test_search_finds_the_right_section_first(tools, query, expected_section):
    results = tools.search_policies(query)["results"]
    assert results and results[0]["section"].endswith(expected_section)


def test_search_returns_nothing_for_unrelated_question(tools):
    result = tools.search_policies("What is the capital of Australia?")
    assert result["results"] == [] and "No relevant" in result["message"]


# --- dispatcher never raises -------------------------------------------------

def test_execute_parses_json_string_arguments(tools):
    assert tools.execute("get_booking", '{"booking_id": "CW-1001"}')["booking"]["id"] == "CW-1001"


@pytest.mark.parametrize(
    "name, args, error",
    [
        ("delete_booking", {}, "unknown_tool"),
        ("get_booking", "{not json", "invalid_arguments"),
        ("get_booking", {}, "invalid_arguments"),
        ("get_booking", {"booking_id": "CW-1001", "extra": 1}, "invalid_arguments"),
        ("get_booking", ["CW-1001"], "invalid_arguments"),
    ],
)
def test_execute_turns_bad_calls_into_errors(tools, name, args, error):
    assert tools.execute(name, args)["error"] == error
