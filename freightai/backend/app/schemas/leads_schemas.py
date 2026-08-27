from pydantic import BaseModel, Field


class IntakeMessageIn(BaseModel):
    text: str = Field(..., min_length=3, max_length=2000)


class MatchedLeadOut(BaseModel):
    """A lead on the opposite side (carrier<->load) with a matching route."""
    contact_name: str | None = None
    phone: str | None = None  # display-formatted, not the raw canonical form


class CarrierActivityOut(BaseModel):
    """Honest activity signal, NOT a reliability/trust score -- see
    CarrierProfile's docstring in models/leads.py for why."""
    total_appearances: int
    first_seen_at: str  # ISO date, keeps the schema JSON-serializable simply


class IntakeResultOut(BaseModel):
    id: str
    lead_type: str  # "load" | "carrier"
    contact_name: str | None = None
    phone: str | None = None  # display-formatted
    origin_city: str | None = None
    destination_city: str | None = None
    weight_tons: float | None = None
    price: float | None = None
    truck_type: str | None = None
    matches: list[MatchedLeadOut] = []
    carrier_activity: CarrierActivityOut | None = None  # only set for lead_type == "carrier"
    needs_review: bool = False  # True when AI extraction confidence was low
