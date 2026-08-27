from pydantic import BaseModel, Field

from app.models.pricing_schema import TruckType


class PricingRequestIn(BaseModel):
    # No driver identity field here -- it comes from the authenticated
    # caller (get_current_user), never from the request body.
    origin_city: str = Field(..., min_length=2)
    destination_city: str = Field(..., min_length=2)
    truck_type: TruckType
    weight_tons: float = Field(..., gt=0, le=100)
    requested_price: float | None = Field(default=None, ge=0)
    raw_text: str | None = None


class PricingRequestOut(BaseModel):
    shipment_id: str
    origin_city: str
    destination_city: str
    truck_type: TruckType
    weight_tons: float
    status: str
    rate_limit_remaining: int
    distance_km: float | None = None
    suggested_price: float | None = None
    suggested_price_sample_size: int = 0
    suggested_price_source: str = "none"  # "closed_deals" | "manual_asks" | "none"
    suggested_price_confidence: str = "none"  # "low" | "medium" | "none"

    model_config = {"from_attributes": True}
