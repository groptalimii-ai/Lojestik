"""
Core database schema for FreightAI Saudi.
All primary keys are UUIDs. All important tables carry created_at/updated_at
and a soft-delete flag (is_deleted) instead of hard deletes.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def gen_uuid():
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    SHIPPER = "shipper"
    CARRIER = "carrier"
    DRIVER = "driver"


class DealStatus(str, enum.Enum):
    NEW = "NEW"
    QUALIFYING = "QUALIFYING"
    QUOTING = "QUOTING"
    CARRIER_SEARCH = "CARRIER_SEARCH"
    MATCHED = "MATCHED"
    NEGOTIATING = "NEGOTIATING"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED"
    CARRIER_APPROVED = "CARRIER_APPROVED"
    BOOKED = "BOOKED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    INVOICE_PENDING = "INVOICE_PENDING"
    PAID = "PAID"
    CARRIER_PAID = "CARRIER_PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class PriceSource(str, enum.Enum):
    CONFIRMED = "confirmed"          # actual agreed price
    USER_ENTERED = "user_entered"    # what shipper/carrier typed
    BROKER_ESTIMATE = "broker_estimate"
    HISTORICAL = "historical"
    AI_ESTIMATE = "ai_estimate"      # never treated as market truth


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    telegram_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.SHIPPER)
    language: Mapped[str] = mapped_column(String, default="ar")
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    # When set, any JWT issued BEFORE this timestamp is rejected even if
    # it hasn't naturally expired yet -- see core/token_revocation.py and
    # core/deps.py. Used for "invalidate every existing session for this
    # user right now" (role changes, suspected compromise). NULL means no
    # restriction (the common case).
    tokens_valid_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship(back_populates="users")


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        # Nullable-unique: Postgres allows any number of NULL phone
        # values (companies with no phone on file), but two non-NULL
        # phones can't collide -- same race-safety reasoning as
        # Location.city_name, see db_utils.get_or_create().
        UniqueConstraint("contact_phone", name="uq_companies_contact_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, nullable=True)  # shipper / carrier
    contact_phone: Mapped[str] = mapped_column(String, nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="company")


class Carrier(Base, TimestampMixin):
    __tablename__ = "carriers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    company_name: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    operates_international: Mapped[bool] = mapped_column(Boolean, default=False)
    eligible_countries: Mapped[str] = mapped_column(String, nullable=True)  # comma-separated for MVP
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    total_trips: Mapped[int] = mapped_column(Integer, default=0)
    reliability_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1

    trucks: Mapped[list["Truck"]] = relationship(back_populates="carrier")


class Truck(Base, TimestampMixin):
    __tablename__ = "trucks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    carrier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("carriers.id"))
    head_type: Mapped[str] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=True)
    trailer_type: Mapped[str] = mapped_column(String, nullable=True)   # e.g. curtain, flatbed, reefer
    max_weight_tons: Mapped[float] = mapped_column(Float, nullable=True)
    current_location: Mapped[str] = mapped_column(String, nullable=True)
    routes: Mapped[str] = mapped_column(String, nullable=True)         # comma-separated corridors
    available_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    approximate_price: Mapped[float] = mapped_column(Float, nullable=True)
    has_return_load: Mapped[bool] = mapped_column(Boolean, default=False)

    carrier: Mapped["Carrier"] = relationship(back_populates="trucks")


class Load(Base, TimestampMixin):
    __tablename__ = "loads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    shipper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    origin: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    cargo_type: Mapped[str] = mapped_column(String, nullable=True)
    weight_tons: Mapped[float] = mapped_column(Float, nullable=True)
    trailer_type: Mapped[str] = mapped_column(String, nullable=True)
    loading_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    hazardous: Mapped[str] = mapped_column(String, default="unknown")  # true/false/unknown
    temperature_required: Mapped[bool] = mapped_column(Boolean, default=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)         # original message, for audit
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="NEW")

    matches: Mapped[list["Match"]] = relationship(back_populates="load")


class Match(Base, TimestampMixin):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    load_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loads.id"))
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id"))
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[str] = mapped_column(Text, nullable=True)  # JSON-encoded list of match reasons
    is_backhaul: Mapped[bool] = mapped_column(Boolean, default=False)

    load: Mapped["Load"] = relationship(back_populates="matches")


class Quote(Base, TimestampMixin):
    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    load_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loads.id"))
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id"), nullable=True)
    customer_price: Mapped[float] = mapped_column(Float, nullable=True)
    carrier_price: Mapped[float] = mapped_column(Float, nullable=True)
    price_source: Mapped[PriceSource] = mapped_column(Enum(PriceSource), default=PriceSource.USER_ENTERED)


class Deal(Base, TimestampMixin):
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    load_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loads.id"))
    truck_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trucks.id"), nullable=True)
    carrier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("carriers.id"), nullable=True)

    customer_price: Mapped[float] = mapped_column(Float, nullable=True)
    carrier_price: Mapped[float] = mapped_column(Float, nullable=True)
    operating_cost: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[DealStatus] = mapped_column(Enum(DealStatus), default=DealStatus.NEW)

    customer_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    carrier_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    # FROZEN until commercial launch: nothing in the codebase currently
    # sets these to True (no payment endpoint exists yet -- see
    # `Payment` below). This is a deliberate decision, not an oversight:
    # real payment tracking depends on business/legal choices outside of
    # code (payment gateway selection, banking partnership, ZATCA
    # e-invoicing compliance) that have to happen before this can mean
    # anything. Until then, capital_progress() and
    # completed_deals_retained_profit() in services/financial.py will
    # always compute zero -- that's the correct, honest behavior for
    # data that was never actually collected, not a bug to "fix" by
    # faking these flags. See README "Frozen Until Commercial Launch".

    approved_by_admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    @property
    def gross_margin(self) -> float:
        if self.customer_price is None or self.carrier_price is None:
            return 0.0
        return self.customer_price - self.carrier_price

    @property
    def margin_pct(self) -> float:
        if not self.customer_price:
            return 0.0
        return round((self.gross_margin / self.customer_price) * 100, 2)

    @property
    def net_profit_estimate(self) -> float:
        return self.gross_margin - (self.operating_cost or 0.0)


class Payment(Base, TimestampMixin):
    """
    FROZEN until commercial launch -- no API endpoint writes to this
    table yet, deliberately (see Deal.customer_paid's comment above for
    why). The schema exists now so the eventual payment-tracking work
    slots into an already-designed shape instead of needing a schema
    migration on day one of accepting real payments.
    """
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    deal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deals.id"))
    direction: Mapped[str] = mapped_column(String)  # "incoming" (from customer) / "outgoing" (to carrier)
    amount: Mapped[float] = mapped_column(Float)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str] = mapped_column(String, nullable=True)


class FraudFlag(Base, TimestampMixin):
    """FROZEN until commercial launch -- same reasoning as Payment above.
    Fraud detection only makes sense once there's real payment/deal
    volume to detect fraud within; nothing writes to this table yet."""
    __tablename__ = "fraud_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    entity_type: Mapped[str] = mapped_column(String)  # "carrier" / "load" / "user"
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(String)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String, nullable=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[str] = mapped_column(Text, nullable=True)
