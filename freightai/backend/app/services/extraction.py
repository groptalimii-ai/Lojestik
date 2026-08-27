"""
Natural language -> structured load data.
AI is used ONLY for extraction/classification here, never for pricing
confirmation or booking decisions (see project rules).
"""
import json
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.services.ai_cache import get_cached_extraction, set_cached_extraction
from app.services.ai_retry import call_with_retry
from app.services.date_normalizer import normalize_date_phrase

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


EXTRACTION_SYSTEM_PROMPT = """You are a logistics data-extraction engine for a Saudi/Gulf freight
marketplace. You receive a raw message (Arabic, Gulf dialect, English, or mixed) describing a
cargo load, and you must extract structured fields.

Return ONLY valid JSON, nothing else, no markdown fences, no preamble. Schema:

{
  "origin": string or null,
  "destination": string or null,
  "cargo_type": string or null,
  "weight_tons": number or null,
  "trailer_type": string or null,
  "loading_date": string or null (ISO date if resolvable, else the raw phrase like "الخميس"),
  "hazardous": "true" | "false" | "unknown",
  "temperature_required": boolean,
  "target_price": number or null,
  "confidence": number between 0 and 1,
  "missing_important_fields": array of field names still missing that matter for matching
}

Rules:
- Understand Modern Standard Arabic, Gulf dialects, abbreviations, misspellings, and English.
- Normalize city names to a canonical form when confident (e.g. "دمام" -> "Dammam").
- Never invent a numeric price or weight that wasn't stated or clearly implied.
- If unsure about a field, set it to null and list it in missing_important_fields.
"""


async def extract_load_from_text(text: str) -> dict[str, Any]:
    cached = await get_cached_extraction("load", text)
    if cached is not None:
        data = dict(cached)
    else:
        client = get_client()
        response = await call_with_retry(lambda: client.messages.create(
            model=settings.ai_model,
            max_tokens=800,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        ))
        raw = "".join(block.text for block in response.content if block.type == "text")
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {
                "origin": None, "destination": None, "cargo_type": None, "weight_tons": None,
                "trailer_type": None, "loading_date": None, "hazardous": "unknown",
                "temperature_required": False, "target_price": None, "confidence": 0.0,
                "missing_important_fields": ["origin", "destination", "cargo_type", "weight_tons"],
                "extraction_error": True,
            }

        if not data.get("extraction_error"):
            # Cached BEFORE date resolution -- see the note below on why.
            await set_cached_extraction("load", text, data)

    # BUG FIXED: this used to normalize the date THEN cache the result,
    # which meant a relative phrase like "الخميس" got resolved to one
    # specific calendar date and that resolved date was cached for 7
    # days. Anyone re-sending the same message text later in that window
    # (a common case: forwarded/re-pasted messages) would silently get
    # the ORIGINAL day's "next Thursday" instead of the correct one for
    # today. Resolving fresh on every call -- cache hit or miss -- fixes
    # it, and costs nothing extra since normalize_date_phrase is local,
    # non-AI, non-network logic.
    normalized = normalize_date_phrase(data.get("loading_date"))
    data["loading_date"] = normalized.date().isoformat() if normalized else None

    return data
