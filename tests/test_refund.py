"""One test (or more) per rule in data/policies/cancellations.md."""

from datetime import timedelta

import pytest

from helpdesk.config import NOW
from helpdesk.refund import calculate_refund


def make_booking(hours_until_start: float, **overrides) -> dict:
    start = NOW + timedelta(hours=hours_until_start)
    booking = {
        "id": "CW-TEST",
        "status": "confirmed",
        "bike_type": "city",
        "bikes": 1,
        "start": start.isoformat(),
        "end": (start + timedelta(hours=24)).isoformat(),
        "add_ons": [],
        "rental_price_eur": 40.0,
        "booking_fee_eur": 2.0,
        "deposit_eur": 50.0,
        "paid_with": "card",
    }
    booking.update(overrides)
    return booking


# --- rental price tiers ------------------------------------------------------

@pytest.mark.parametrize("hours", [48, 48.01, 100])
def test_48h_or_more_refunds_full_rental(hours):
    r = calculate_refund(make_booking(hours), NOW)
    assert r.can_cancel and r.refund_percent == 100
    assert r.rental_refund_eur == 40.0


@pytest.mark.parametrize("hours", [24, 30, 47.99])
def test_between_24h_and_48h_refunds_half(hours):
    r = calculate_refund(make_booking(hours), NOW)
    assert r.refund_percent == 50
    assert r.rental_refund_eur == 20.0


@pytest.mark.parametrize("hours", [23.99, 6, 0.1])
def test_less_than_24h_refunds_nothing_of_rental(hours):
    r = calculate_refund(make_booking(hours), NOW)
    assert r.can_cancel and r.refund_percent == 0
    assert r.rental_refund_eur == 0.0


def test_half_refund_is_rounded_to_cents():
    r = calculate_refund(make_booking(30, rental_price_eur=23.0), NOW)
    assert r.rental_refund_eur == 11.5


# --- booking fee and deposit -------------------------------------------------

@pytest.mark.parametrize("hours", [100, 30, 1])
def test_booking_fee_is_never_refunded(hours):
    r = calculate_refund(make_booking(hours), NOW)
    assert r.booking_fee_refund_eur == 0.0


@pytest.mark.parametrize("hours", [100, 30, 1])
def test_deposit_is_always_refunded_in_full(hours):
    r = calculate_refund(make_booking(hours), NOW)
    assert r.deposit_refund_eur == 50.0


def test_total_is_rental_share_plus_deposit():
    r = calculate_refund(make_booking(30), NOW)
    assert r.total_refund_eur == 20.0 + 50.0


# --- statuses that cannot be cancelled ---------------------------------------

@pytest.mark.parametrize("status", ["in_progress", "completed", "cancelled"])
def test_non_confirmed_status_cannot_be_cancelled(status):
    r = calculate_refund(make_booking(100, status=status), NOW)
    assert not r.can_cancel
    assert r.total_refund_eur == 0.0 and r.deposit_refund_eur == 0.0
    assert status in r.reason


def test_confirmed_booking_that_already_started_cannot_be_cancelled():
    r = calculate_refund(make_booking(-1), NOW)
    assert not r.can_cancel and r.total_refund_eur == 0.0


# --- how the money comes back ------------------------------------------------

def test_card_refund_goes_back_to_card():
    r = calculate_refund(make_booking(100, paid_with="card"), NOW)
    assert "card" in r.refund_method and "5 working days" in r.refund_method


def test_voucher_refund_is_a_new_voucher_not_money():
    r = calculate_refund(make_booking(100, paid_with="voucher"), NOW)
    assert "voucher" in r.refund_method and "not money" in r.refund_method


# --- cancelling at a later moment (follow-up questions) ----------------------

def test_cancelling_later_can_drop_into_a_lower_tier():
    booking = make_booking(50)
    assert calculate_refund(booking, NOW).refund_percent == 100
    assert calculate_refund(booking, NOW + timedelta(hours=3)).refund_percent == 50
