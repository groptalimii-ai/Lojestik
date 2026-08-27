"""
Manual data-collection channel (see api/intake.py, bot/handlers/intake.py).

Two distinct steps, deliberately kept separate:

1. classify_intake_text() -- NOT an AI call. This is the operator's own
   rule, stated verbatim: any message containing "حمولة" or "طن" is a
   load/shipper lead, everything else is a carrier lead. It's free,
   instant, and 100% precise for the operator's own message conventions
   -- there's no reason to spend an AI call (money + latency) deciding
   something the operator already told us how to decide.

2. extract_carrier_lead() / extract_load_lead() -- AI is used ONLY here,
   for structured field extraction within whichever category step 1
   already picked. Same "never invent a value" discipline as
   extraction.py. Both now also return a self-reported "confidence"
   (0-1) -- previously this pipeline had NO confidence signal at all,
   so a hallucinated field (wrong city, wrong price) had no way to be
   flagged for review; it just silently landed in the permanent DB.
   api/intake.py uses this to set needs_review on low-confidence rows.
"""
import json
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.services.ai_cache import get_cached_extraction, set_cached_extraction
from app.services.ai_retry import call_with_retry

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


LOAD_KEYWORDS = ("حمولة", "حمولات", "طن", "أطنان", "اطنان")

# Below this, a lead is flagged needs_review=True instead of silently
# trusted -- see api/intake.py.
LOW_CONFIDENCE_THRESHOLD = 0.6


def classify_intake_text(text: str) -> str:
    """Returns "load" or "carrier" -- see module docstring, this is a
    plain keyword rule, not an AI call."""
    return "load" if any(kw in text for kw in LOAD_KEYWORDS) else "carrier"


CARRIER_LEAD_PROMPT = """أنت محرك استخراج بيانات لوجستية لمنصة شحن سعودية/خليجية.
تستلم رسالة عربية غير منظمة (قد تكون عامية خليجية) تصف ناقلاً/سائقاً وشاحنته -- وليس حمولة.
أعد فقط JSON صالح، بدون أي نص إضافي أو علامات markdown، بالمخطط التالي:

{
  "contact_name": string or null,
  "phone": string or null (أرقام فقط، احذف أي رموز أو مسافات),
  "truck_type": one of ["flatbed","curtain","reefer","box","lowbed","tanker","dyna","other"],
  "origin": string or null,
  "destination": string or null,
  "confidence": number between 0 and 1 (مدى ثقتك بدقة الاستخراج ككل)
}

قواعد التحويل الشائعة: "سطحة"=flatbed، "ستارة"=curtain، "مبرّدة"/"ثلاجة"=reefer،
"صندوق"=box، "لوبد"=lowbed، "صهريج"=tanker، "دينا"=dyna.
لا تخترع رقم هاتف أو مدينة لم تُذكر صراحة في النص. أي معلومة غامضة أو غير مؤكدة
يجب أن تُخفّض قيمة confidence، وليس أن تُخترع لتعويضها."""

LOAD_LEAD_PROMPT = """أنت محرك استخراج بيانات لوجستية لمنصة شحن سعودية/خليجية.
تستلم رسالة عربية غير منظمة تصف صاحب حمولة يريد نقلها -- وليس شاحنة أو ناقل.
أعد فقط JSON صالح، بدون أي نص إضافي أو علامات markdown، بالمخطط التالي:

{
  "contact_name": string or null,
  "phone": string or null (أرقام فقط، احذف أي رموز أو مسافات),
  "origin": string or null,
  "destination": string or null,
  "weight_tons": number or null,
  "price": number or null,
  "confidence": number between 0 and 1 (مدى ثقتك بدقة الاستخراج ككل)
}

لا تخترع رقمًا أو مدينة لم تُذكر صراحة في النص. أي معلومة غامضة أو غير مؤكدة
يجب أن تُخفّض قيمة confidence، وليس أن تُخترع لتعويضها."""


async def _extract(namespace: str, text: str, system_prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
    cached = await get_cached_extraction(namespace, text)
    if cached is not None:
        return cached

    client = get_client()
    response = await call_with_retry(lambda: client.messages.create(
        model=settings.ai_model,
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": text}],
    ))
    raw = "".join(block.text for block in response.content if block.type == "text")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return dict(fallback)

    await set_cached_extraction(namespace, text, data)
    return data


async def extract_carrier_lead(text: str) -> dict[str, Any]:
    return await _extract(
        "carrier_lead",
        text,
        CARRIER_LEAD_PROMPT,
        fallback={
            "contact_name": None, "phone": None, "truck_type": "other",
            "origin": None, "destination": None, "confidence": 0.0,
        },
    )


async def extract_load_lead(text: str) -> dict[str, Any]:
    return await _extract(
        "load_lead",
        text,
        LOAD_LEAD_PROMPT,
        fallback={
            "contact_name": None, "phone": None, "origin": None,
            "destination": None, "weight_tons": None, "price": None, "confidence": 0.0,
        },
    )
