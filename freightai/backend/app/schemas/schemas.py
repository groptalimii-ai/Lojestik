from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.phone_normalizer import normalize_saudi_phone

# Shared bounds. Previously most numeric/string fields had no constraints
# at all -- a client could send a negative weight, a truck with -50 tons
# capacity, or a 500KB "text" blob to /ai/extract-load (which is billed
# per token upstream, so an unbounded text field is a real cost-control
# gap, not just a data-quality one).
MAX_WEIGHT_TONS = 100
MAX_PRICE_SAR = 500_000
MAX_TEXT_LEN = 2000
MAX_SHORT_STR_LEN = 200


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=3, max_length=MAX_TEXT_LEN)


class ExtractResponse(BaseModel):
    origin: str | None = None
    destination: str | None = None
    cargo_type: str | None = None
    weight_tons: float | None = None
    trailer_type: str | None = None
    loading_date: str | None = None
    hazardous: str = "unknown"
    temperature_required: bool = False
    target_price: float | None = None
    confidence: float = 0.0
    missing_important_fields: list[str] = []


class LoadCreate(BaseModel):
    # shipper_id intentionally NOT here — it's the authenticated caller's
    # own id (see api/loads.py), never a value the client gets to assert.
    origin: str = Field(..., min_length=1, max_length=MAX_SHORT_STR_LEN)
    destination: str = Field(..., min_length=1, max_length=MAX_SHORT_STR_LEN)
    cargo_type: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    weight_tons: float | None = Field(default=None, gt=0, le=MAX_WEIGHT_TONS)
    trailer_type: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    loading_date: datetime | None = None
    hazardous: str = "unknown"
    temperature_required: bool = False
    target_price: float | None = Field(default=None, ge=0, le=MAX_PRICE_SAR)
    raw_text: str | None = Field(default=None, max_length=MAX_TEXT_LEN)
    # How confident the AI extraction was (0-1), carried through from
    # ExtractResponse so it actually reaches the DB -- previously this
    # value was computed and shown to the driver but silently dropped
    # before storage, leaving Load.extraction_confidence permanently
    # NULL despite the column existing specifically to hold it.
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)


class LoadOut(LoadCreate):
    id: UUID
    shipper_id: UUID
    status: str

    class Config:
        from_attributes = True


class CarrierRegister(BaseModel):
    # user_id intentionally NOT here — same reasoning as LoadCreate.shipper_id.
    company_name: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    phone: str | None = Field(default=None, max_length=20)
    operates_international: bool = False
    eligible_countries: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)

    @field_validator("phone")
    @classmethod
    def phone_digits_only(cls, v: str | None) -> str | None:
        # Normalized to the same canonical form used everywhere else
        # (intake, Company matching) so a self-registered carrier's phone
        # matches leads collected manually for the same person.
        if v is None:
            return v
        normalized = normalize_saudi_phone(v)
        if normalized is None:
            raise ValueError("رقم الهاتف يجب أن يحتوي أرقامًا فقط")
        return normalized


class TruckCreate(BaseModel):
    carrier_id: UUID
    head_type: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    model: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    year: int | None = Field(default=None, ge=1980, le=2100)
    trailer_type: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    max_weight_tons: float | None = Field(default=None, gt=0, le=MAX_WEIGHT_TONS)
    current_location: str | None = Field(default=None, max_length=MAX_SHORT_STR_LEN)
    routes: str | None = Field(default=None, max_length=MAX_TEXT_LEN)
    # Raw phrase as typed by the driver (e.g. "الخميس", "2026-08-25").
    # Normalized into a real datetime server-side -- see api/carriers.py.
    available_from_text: str | None = Field(default=None, max_length=100)
    approximate_price: float | None = Field(default=None, ge=0, le=MAX_PRICE_SAR)
    has_return_load: bool = False


class MatchOut(BaseModel):
    truck_id: UUID
    score: float
    reasons: list[str]
    is_backhaul: bool


class CarrierOut(CarrierRegister):
    id: UUID
    user_id: UUID
    rating: float
    total_trips: int
    reliability_rate: float

    class Config:
        from_attributes = True


class TruckOut(BaseModel):
    id: UUID
    carrier_id: UUID
    head_type: str | None = None
    model: str | None = None
    year: int | None = None
    trailer_type: str | None = None
    max_weight_tons: float | None = None
    current_location: str | None = None
    routes: str | None = None
    available_from: datetime | None = None
    approximate_price: float | None = None
    has_return_load: bool = False

    class Config:
        from_attributes = True


class DealCreate(BaseModel):
    load_id: UUID
    truck_id: UUID | None = None
    carrier_id: UUID | None = None
    customer_price: float | None = Field(default=None, ge=0, le=MAX_PRICE_SAR)
    carrier_price: float | None = Field(default=None, ge=0, le=MAX_PRICE_SAR)
    operating_cost: float = Field(default=0.0, ge=0, le=MAX_PRICE_SAR)


class DealStatusUpdate(BaseModel):
    target_status: str
    # is_admin intentionally NOT here — it used to be a client-supplied
    # bool, which meant anyone could set {"is_admin": true} in the request
    # body and bypass the deal lifecycle's admin gate entirely. Admin
    # status is now derived server-side from the authenticated user's role
    # (see api/deals.py).


class DealOut(DealCreate):
    id: UUID
    status: str
    customer_paid: bool
    carrier_paid: bool

    class Config:
        from_attributes = True


class PageParams(BaseModel):
    """Shared pagination bounds -- list_loads/list_carriers/list_deals were
    previously unbounded SELECTs with no LIMIT at all, fine at MVP scale
    and a real problem the moment any of those tables has thousands of rows."""
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
