"""
Leads collected manually through the operator's private Telegram channel
(see bot/handlers/intake.py + api/intake.py) -- NOT the same as
models.Carrier / models.Load, which assume a self-registered bot user
(user_id / shipper_id FK to `users`, filled in via the FSM flows).

A contact like "أبو سعد" typed by the operator has no Telegram account of
their own, so these tables intentionally have no NOT NULL user FK on the
lead's own side -- only `submitted_by_user_id`, which tracks the admin who
entered it.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.pricing_schema import TruckType


def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CarrierProfile(Base, TimestampMixin):
    """
    Aggregated identity per carrier, keyed by normalized phone -- built
    from repeated CarrierLead sightings over time.

    IMPORTANT, stated plainly: `total_appearances` is an ACTIVITY signal
    (how many times this contact has been logged), not a reliability or
    trust score. We don't yet track any real outcome data (was the load
    actually delivered, was there a no-show, a complaint) because that
    requires a deal-completion flow that doesn't exist yet (see README
    Roadmap). Once it does, THIS table is where that signal would
    accumulate -- but until then, showing "logged 5 times" is honest;
    calling it "5-star reliable" would not be.
    """
    __tablename__ = "carrier_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    phone: Mapped[str] = mapped_column(String, unique=True, index=True)
    contact_name: Mapped[str] = mapped_column(String, nullable=True)  # most recently seen name
    total_appearances: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CarrierLead(Base, TimestampMixin):
    """قاعدة بيانات مخصصة للناقلين (leads يدوية، لا تسجيل ذاتي)."""
    __tablename__ = "carrier_leads"
    __table_args__ = (
        Index("ix_carrier_leads_phone", "phone"),
        Index("ix_carrier_leads_route", "origin_location_id", "destination_location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    contact_name: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    truck_type: Mapped[TruckType] = mapped_column(Enum(TruckType), default=TruckType.OTHER)
    origin_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    destination_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # True when the AI extraction's self-reported confidence was low --
    # flags this row for a human to double-check rather than trusting it
    # silently. See services/lead_extraction.py.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    origin: Mapped["Location"] = relationship(foreign_keys=[origin_location_id])
    destination: Mapped["Location"] = relationship(foreign_keys=[destination_location_id])


class LoadLead(Base, TimestampMixin):
    """قاعدة بيانات الشركات/أصحاب الحمولات (leads يدوية)."""
    __tablename__ = "load_leads"
    __table_args__ = (
        Index("ix_load_leads_phone", "phone"),
        Index("ix_load_leads_route", "origin_location_id", "destination_location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    contact_name: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String, nullable=True)
    origin_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    destination_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    weight_tons: Mapped[float] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    origin: Mapped["Location"] = relationship(foreign_keys=[origin_location_id])
    destination: Mapped["Location"] = relationship(foreign_keys=[destination_location_id])
