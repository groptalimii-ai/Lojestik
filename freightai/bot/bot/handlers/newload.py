from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import RateLimitExceeded, backend
from bot.keyboards import confirm_extraction_kb
from bot.states import NewLoadFlow

router = Router()

FIELD_LABELS = {
    "origin": "من أين (نقطة التحميل)؟",
    "destination": "إلى أين (الوجهة)؟",
    "cargo_type": "ما نوع البضاعة؟",
    "weight_tons": "ما الوزن بالطن؟",
    "trailer_type": "ما نوع المقطورة المطلوبة؟",
    "loading_date": "ما تاريخ التحميل؟",
}


async def prompt_for_load_text(message: Message, state: FSMContext):
    await state.set_state(NewLoadFlow.waiting_for_text)
    await message.answer(
        "أرسل تفاصيل الحمولة في رسالة واحدة، مثال:\n"
        "«عندي 22 طن بلاستيك من الدمام إلى عمّان، التحميل يوم الخميس»"
    )


@router.message(Command("newload"))
async def cmd_newload(message: Message, state: FSMContext):
    await prompt_for_load_text(message, state)


@router.message(NewLoadFlow.waiting_for_text)
async def receive_load_text(message: Message, state: FSMContext):
    await message.answer("⏳ جارٍ تحليل الطلب...")
    try:
        extracted = await backend.extract_load(message.text, message.from_user.id)
    except RateLimitExceeded as e:
        await message.answer(f"🚫 {e.detail}")
        await state.clear()
        return
    except Exception:
        await message.answer("⚠️ حدث خطأ أثناء التحليل. حاول مرة أخرى أو تواصل مع الدعم /support")
        return

    await state.update_data(extracted=extracted, raw_text=message.text)

    missing = extracted.get("missing_important_fields") or []
    summary = _format_extraction(extracted)

    if missing:
        await message.answer(
            summary + "\n\n⚠️ يوجد بيانات ناقصة مهمة:\n" + "\n".join(f"- {FIELD_LABELS.get(m, m)}" for m in missing)
        )
        await state.set_state(NewLoadFlow.asking_missing_field)
        await message.answer(f"الرجاء الإجابة: {FIELD_LABELS.get(missing[0], missing[0])}")
    else:
        await state.set_state(NewLoadFlow.confirming)
        await message.answer(summary, reply_markup=confirm_extraction_kb())


@router.message(NewLoadFlow.asking_missing_field)
async def receive_missing_field(message: Message, state: FSMContext):
    data = await state.get_data()
    extracted = data.get("extracted", {})
    missing = extracted.get("missing_important_fields") or []
    if missing:
        field = missing.pop(0)
        extracted[field] = message.text
        extracted["missing_important_fields"] = missing
        await state.update_data(extracted=extracted)

    if missing:
        await message.answer(f"الرجاء الإجابة: {FIELD_LABELS.get(missing[0], missing[0])}")
    else:
        await state.set_state(NewLoadFlow.confirming)
        await message.answer(_format_extraction(extracted), reply_markup=confirm_extraction_kb())


@router.callback_query(F.data == "load:confirm", NewLoadFlow.confirming)
async def confirm_load(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    extracted = data.get("extracted", {})
    # shipper_id is derived server-side from the JWT (see api/loads.py) --
    # never sent by the client.
    payload = {
        "origin": extracted.get("origin") or "",
        "destination": extracted.get("destination") or "",
        "cargo_type": extracted.get("cargo_type"),
        "weight_tons": extracted.get("weight_tons"),
        "trailer_type": extracted.get("trailer_type"),
        "hazardous": extracted.get("hazardous", "unknown"),
        "temperature_required": bool(extracted.get("temperature_required", False)),
        "target_price": extracted.get("target_price"),
        "raw_text": data.get("raw_text"),
        "extraction_confidence": extracted.get("confidence"),
    }
    try:
        load = await backend.create_load(payload, callback.from_user.id)
        await callback.message.answer(f"✅ تم تسجيل الحمولة بنجاح.\nرقم الطلب: {load['id']}")

        # Now that the load exists, show any decent truck matches right
        # away instead of leaving the shipper to wonder what happens next
        # -- the matching engine existed but nothing ever called it.
        try:
            matches = await backend.find_matches(load["id"], callback.from_user.id)
        except Exception:
            matches = []
        good_matches = [m for m in matches if m.get("score", 0) >= 50][:3]
        if good_matches:
            lines = ["🎯 وجدنا شاحنات محتملة لحمولتك:"]
            for m in good_matches:
                reasons = "، ".join(m.get("reasons", [])[:2])
                lines.append(f"• تطابق {m['score']:.0f}% — {reasons}")
            await callback.message.answer("\n".join(lines))
    except RateLimitExceeded as e:
        await callback.message.answer(f"🚫 {e.detail}")
    except Exception:
        await callback.message.answer("⚠️ تعذر حفظ الحمولة. تواصل مع الدعم /support")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "load:cancel")
async def cancel_load(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("تم الإلغاء.")
    await callback.answer()


@router.callback_query(F.data == "load:edit")
async def edit_load(callback: CallbackQuery, state: FSMContext):
    await state.set_state(NewLoadFlow.waiting_for_text)
    await callback.message.answer("أرسل تفاصيل الحمولة الصحيحة من جديد:")
    await callback.answer()


def _format_extraction(extracted: dict) -> str:
    lines = [
        "📦 ملخص الحمولة:",
        f"من: {extracted.get('origin') or '—'}",
        f"إلى: {extracted.get('destination') or '—'}",
        f"نوع البضاعة: {extracted.get('cargo_type') or '—'}",
        f"الوزن: {extracted.get('weight_tons') or '—'} طن",
        f"نوع المقطورة: {extracted.get('trailer_type') or '—'}",
        f"تاريخ التحميل: {extracted.get('loading_date') or '—'}",
        f"بضاعة خطرة: {extracted.get('hazardous') or 'unknown'}",
    ]
    # Surfaces AI extraction confidence explicitly instead of only storing
    # it silently -- this is the actual "catch a hallucination" mechanism
    # right now: a low score prompts the shipper to double-check the
    # fields above before confirming, rather than trusting them blindly.
    confidence = extracted.get("confidence")
    if confidence is not None and confidence < 0.6:
        lines.append("\n⚠️ الثقة بالاستخراج منخفضة — راجع البيانات أعلاه بعناية قبل التأكيد.")
    return "\n".join(lines)
