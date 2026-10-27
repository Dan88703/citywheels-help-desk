"""Refund rules from data/policies/cancellations.md, implemented in code.

The model must never do this arithmetic itself; it only calls the tool and
reports the numbers it gets back.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

# (minimum hours before start, percent of rental price refunded),
# checked from the top. Mirrors the table in cancellations.md.
REFUND_TIERS = [
    (48, 100),
    (24, 50),
    (0, 0),
]

CANCELLABLE_STATUS = "confirmed"


@dataclass
class RefundResult:
    booking_id: str
    can_cancel: bool
    reason: str
    hours_before_start: float | None
    refund_percent: int
    rental_price_eur: float
    rental_refund_eur: float
    deposit_refund_eur: float
    booking_fee_refund_eur: float
    total_refund_eur: float
    refund_method: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _money(value) -> Decimal:
    # Decimal avoids float surprises like 0.1 + 0.2 != 0.3 in money math.
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _refund_method(paid_with: str) -> str:
    if paid_with == "voucher":
        return "new voucher of the same value (not money); the deposit is refunded the same way it was paid"
    return "back to the same card within 5 working days"


def calculate_refund(booking: dict, cancel_at: datetime) -> RefundResult:
    """Apply the cancellation rules to one booking at a given moment.

    Steps:
    1. Only `confirmed` bookings can be cancelled; any other status refunds 0.
    2. A confirmed booking whose start time has already passed at `cancel_at`
       can't be cancelled either (the rental is running). The policy does not
       say this explicitly, so it is our interpretation (see SOLUTION.md).
    3. Otherwise the share of the rental price depends on the hours left
       until the start (>=48h: 100%, >=24h: 50%, <24h: 0%). Boundaries are
       inclusive: exactly 48h still gives 100%.
    4. The deposit is always returned in full, the booking fee never.
    """
    start = datetime.fromisoformat(booking["start"])
    rental = _money(booking["rental_price_eur"])
    deposit = _money(booking["deposit_eur"])

    def not_cancellable(reason: str, hours: float | None) -> RefundResult:
        return RefundResult(
            booking_id=booking["id"],
            can_cancel=False,
            reason=reason,
            hours_before_start=hours,
            refund_percent=0,
            rental_price_eur=float(rental),
            rental_refund_eur=0.0,
            deposit_refund_eur=0.0,
            booking_fee_refund_eur=0.0,
            total_refund_eur=0.0,
            refund_method=None,
        )

    status = booking["status"]
    if status != CANCELLABLE_STATUS:
        return not_cancellable(
            f"Booking has status '{status}'. Only 'confirmed' bookings can be cancelled; nothing is refunded.",
            None,
        )

    hours = (start - cancel_at).total_seconds() / 3600
    if hours <= 0:
        return not_cancellable(
            "The rental has already started at this time, so the booking can no longer be cancelled.",
            round(hours, 2),
        )

    percent = next(p for min_hours, p in REFUND_TIERS if hours >= min_hours)
    rental_refund = _money(rental * percent / 100)
    total = rental_refund + deposit  # the booking fee is never refunded

    return RefundResult(
        booking_id=booking["id"],
        can_cancel=True,
        reason=(
            f"Cancelled {hours:.1f} hours before the start: {percent}% of the rental price is refunded. "
            "The deposit is refunded in full. The booking fee is never refunded."
        ),
        hours_before_start=round(hours, 2),
        refund_percent=percent,
        rental_price_eur=float(rental),
        rental_refund_eur=float(rental_refund),
        deposit_refund_eur=float(deposit),
        booking_fee_refund_eur=0.0,
        total_refund_eur=float(total),
        refund_method=_refund_method(booking["paid_with"]),
    )
