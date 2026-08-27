"""
Deal lifecycle state machine. Enforces that a deal can only move to an
allowed next status, and that certain transitions require admin approval.
"""
from app.models.models import DealStatus

ALLOWED_TRANSITIONS: dict[DealStatus, list[DealStatus]] = {
    DealStatus.NEW: [DealStatus.QUALIFYING, DealStatus.CANCELLED],
    DealStatus.QUALIFYING: [DealStatus.QUOTING, DealStatus.CANCELLED],
    DealStatus.QUOTING: [DealStatus.CARRIER_SEARCH, DealStatus.CANCELLED],
    DealStatus.CARRIER_SEARCH: [DealStatus.MATCHED, DealStatus.CANCELLED],
    DealStatus.MATCHED: [DealStatus.NEGOTIATING, DealStatus.CUSTOMER_APPROVED, DealStatus.CANCELLED],
    DealStatus.NEGOTIATING: [DealStatus.CUSTOMER_APPROVED, DealStatus.CARRIER_APPROVED, DealStatus.CANCELLED],
    DealStatus.CUSTOMER_APPROVED: [DealStatus.CARRIER_APPROVED, DealStatus.CANCELLED],
    DealStatus.CARRIER_APPROVED: [DealStatus.BOOKED, DealStatus.CANCELLED],
    DealStatus.BOOKED: [DealStatus.LOADING, DealStatus.CANCELLED, DealStatus.DISPUTED],
    DealStatus.LOADING: [DealStatus.IN_TRANSIT, DealStatus.DISPUTED],
    DealStatus.IN_TRANSIT: [DealStatus.DELIVERED, DealStatus.DISPUTED],
    DealStatus.DELIVERED: [DealStatus.INVOICE_PENDING, DealStatus.DISPUTED],
    DealStatus.INVOICE_PENDING: [DealStatus.PAID, DealStatus.DISPUTED],
    DealStatus.PAID: [DealStatus.CARRIER_PAID],
    DealStatus.CARRIER_PAID: [DealStatus.COMPLETED],
    DealStatus.COMPLETED: [],
    DealStatus.CANCELLED: [],
    DealStatus.DISPUTED: [DealStatus.NEGOTIATING, DealStatus.CANCELLED, DealStatus.BOOKED],
}

# These transitions may never happen automatically - always require an
# explicit admin action (checked at the API layer, not just here).
REQUIRES_ADMIN_APPROVAL = {
    DealStatus.BOOKED,
    DealStatus.PAID,
    DealStatus.CARRIER_PAID,
    DealStatus.COMPLETED,
}


class InvalidTransitionError(Exception):
    pass


def validate_transition(current: DealStatus, target: DealStatus, is_admin: bool) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidTransitionError(f"Cannot move deal from {current} to {target}")
    if target in REQUIRES_ADMIN_APPROVAL and not is_admin:
        raise InvalidTransitionError(f"Transition to {target} requires admin approval")
