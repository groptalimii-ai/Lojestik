"""
FreightAI — Pricing/ML-ready schema.

Design notes:
- Locations are normalized (not free-text strings) so that route pairs are
  queryable and distance/geo features can be computed for the future
  pricing model.
- Shipment = an open/live pricing request coming from a driver or shipper.
- TripRecord = the ML training table. One row per COMPLETED trip, holding
  the route, truck type, weight, and the *actually accepted* final price
  (the label). Rows are only written when a deal is closed — never from
  a driver's raw ask — so the training signal reflects real market price,
  not aspirational quotes.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TruckType(str, enum.Enum):
    FLATBED = "flatbed"
    CURTAIN = "curtain"
    REEFER = "reefer"
    BOX = "box"
    LOWBED = "lowbed"
    TANKER = "tanker"
    DYNA = "dyna"
    OTHER = "other"


class ShipmentStatus(str, enum.Enum):
    PENDING_PRICE = "pending_price"     # driver/shipper just asked for a price
    QUOTED = "quoted"
    ACCEPTED = "accepted"
    COMPLETED = "completed"             # -> mirrored into TripRecord
    CANCELLED = "cancelled"


class Location(Base, TimestampMixin):
    """
    المواقع الجغرافية — normalized so routes are (origin_id, destination_id)
    pairs instead of free strings. lat/lng feed distance-based ML features.
    """
    __tablename__ = "locations"
    __table_args__ = (
        Index("ix_locations_city_region", "city_name", "region"),
        # Enforced at the DB level, not just the application's
        # get-or-create check -- two concurrent requests resolving the
        # same city simultaneously would otherwise both pass the "does it
        # exist?" SELECT before either commits, creating two rows for the
        # same city. See api/pricing.py and api/intake.py's
        # _get_or_create_location() for the retry-on-conflict handling
        # this constraint requires.
        UniqueConstraint("city_name", name="uq_locations_city_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    city_name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=True)
    country_code: Mapped[str] = mapped_column(String, default="SA")
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)


class Shipment(Base, TimestampMixin):
    """
    الشحنات — a live pricing/matching request. Created the moment a driver
    or shipper asks for a price via the bot; later resolved into a Deal.
    """
    __tablename__ = "shipments"
    __table_args__ = (
        Index("ix_shipments_route", "origin_location_id", "destination_location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    # `companies` is defined in app.models.models (the pre-existing table,
    # already referenced by User.company_id) -- this schema reuses it
    # rather than redeclaring a second, colliding "companies" table.
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    # The authenticated caller (see api/pricing.py) -- never client-supplied.
    driver_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)

    origin_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"))
    destination_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"))

    truck_type: Mapped[TruckType] = mapped_column(Enum(TruckType), default=TruckType.OTHER)
    weight_tons: Mapped[float] = mapped_column(Float, nullable=True)

    requested_price: Mapped[float] = mapped_column(Float, nullable=True)   # what the driver asked for
    quoted_price: Mapped[float] = mapped_column(Float, nullable=True)      # what the system/broker offered

    status: Mapped[ShipmentStatus] = mapped_column(Enum(ShipmentStatus), default=ShipmentStatus.PENDING_PRICE)
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)             # original message, audit trail

    origin: Mapped["Location"] = relationship(foreign_keys=[origin_location_id])
    destination: Mapped["Location"] = relationship(foreign_keys=[destination_location_id])
    trip_record: Mapped["TripRecord"] = relationship(back_populates="shipment", uselist=False)


class TripRecord(Base, TimestampMixin):
    """
    سجل الرحلات — ML training table. One row per closed trip.
    `final_accepted_price` is the label for the future pricing model;
    everything else is a feature. `used_for_training` lets you hold out
    rows (e.g. disputed/fraudulent trips) without deleting history.
    """
    __tablename__ = "trip_records"
    __table_args__ = (
        Index("ix_trip_records_route", "origin_location_id", "destination_location_id"),
        Index("ix_trip_records_truck_type", "truck_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True, unique=True
    )

    origin_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"))
    destination_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"))

    truck_type: Mapped[TruckType] = mapped_column(Enum(TruckType), default=TruckType.OTHER)
    weight_tons: Mapped[float] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float] = mapped_column(Float, nullable=True)  # backfilled once a distance service exists

    # --- label ---
    final_accepted_price: Mapped[float] = mapped_column(Float, nullable=False)
    price_currency: Mapped[str] = mapped_column(String, default="SAR")

    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    used_for_training: Mapped[bool] = mapped_column(Boolean, default=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="trip_record")
    origin: Mapped["Location"] = relationship(foreign_keys=[origin_location_id])
    destination: Mapped["Location"] = relationship(foreign_keys=[destination_location_id])
