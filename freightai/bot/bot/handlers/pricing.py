from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot.api_client import RateLimitExceeded, backend
from bot.states import PricingRequestFlow

router = Router()

TRUCK_TYPE_LABELS = {
    "flatbed": "سطحة",
    "curtain": "ستارة",
    "reefer": "مبرّدة",
    "box": "صندوق مغلق",
    "lowbed": "لوبد",
    "tanker": "صهريج",
    "dyna": "دينا",
    "other": "أخرى",
}


def _truck_type_kb() -> ReplyKeyboardMarkup:
    rows, row = [], []
    for i, label in enumerate(TRUCK_TYPE_LABELS.values(), start=1):
        row.append(KeyboardButton(text=label))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def _truck_type_from_label(label: str) -> str:
    for key, value in TRUCK_TYPE_LABELS.items():
        if value == label.strip():
            return key
    return "other"


@router.message(Command("price"))
async def cmd_price(message: Message, state: FSMContext):
    """Entry point: driver asks for a price -> collect trip details."""
    await state.set_state(PricingRequestFlow.waiting_for_origin)
    await message.answer(
        "🚚 طلب تسعير جديد\n\nمن أين نقطة التحميل؟ (اسم المدينة)",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(PricingRequestFlow.waiting_for_origin)
async def receive_origin(message: Message, state: FSMContext):
    await state.update_data(origin_city=message.text.strip())
    await state.set_state(PricingRequestFlow.waiting_for_destination)
    await message.answer("إلى أين الوجهة؟ (اسم المدينة)")


@router.message(PricingRequestFlow.waiting_for_destination)
async def receive_destination(message: Message, state: FSMContext):
    await state.update_data(destination_city=message.text.strip())
    await state.set_state(PricingRequestFlow.waiting_for_truck_type)
    await message.answer("ما نوع الشاحنة؟", reply_markup=_truck_type_kb())


@router.message(PricingRequestFlow.waiting_for_truck_type)
async def receive_truck_type(message: Message, state: FSMContext):
    await state.update_data(truck_type=_truck_type_from_label(message.text))
    await state.set_state(PricingRequestFlow.waiting_for_weight)
    await message.answer("ما الوزن بالطن؟ (رقم فقط)", reply_markup=ReplyKeyboardRemove())


@router.message(PricingRequestFlow.waiting_for_weight)
async def receive_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip())
        if weight <= 0 or weight > 100:
            raise ValueError
    except ValueError:
        await message.answer("الرجاء إدخال رقم صحيح للوزن بالطن (مثال: 22).")
        return

    await state.update_data(weight_tons=weight)
    await state.set_state(PricingRequestFlow.waiting_for_price_opt)
    await message.answer("هل لديك سعر مبدئي تطلبه؟ أرسله الآن، أو أرسل «تخطي».")


@router.message(PricingRequestFlow.waiting_for_price_opt)
async def receive_price_and_submit(message: Message, state: FSMContext):
    text = message.text.strip()
    requested_price = None
    if text not in ("تخطي", "skip", "-"):
        try:
            requested_price = float(text)
        except ValueError:
            await message.answer("الرجاء إدخال رقم، أو أرسل «تخطي».")
            return

    data = await state.get_data()
    payload = {
        # No driver id in the payload -- backend derives it from the JWT
        # (see bot.api_client.request_pricing -> backend /auth/telegram).
        "origin_city": data["origin_city"],
        "destination_city": data["destination_city"],
        "truck_type": data["truck_type"],
        "weight_tons": data["weight_tons"],
        "requested_price": requested_price,
        "raw_text": f"{data['origin_city']} -> {data['destination_city']}",
    }

    await message.answer("⏳ جارٍ تسجيل طلب التسعير...")
    try:
        # backend.request_pricing() -> POST /pricing/request, which itself
        # runs the rate limiter (Depends) before touching the database.
        result = await backend.request_pricing(payload, message.from_user.id)
    except RateLimitExceeded as e:
        await message.answer(f"🚫 {e.detail}")
        await state.clear()
        return
    except Exception:
        await message.answer("⚠️ تعذر تسجيل الطلب. حاول مرة أخرى أو تواصل مع الدعم /support")
        await state.clear()
        return

    confidence_labels = {"medium": "بيانات كافية", "low": "بيانات محدودة", "none": ""}
    reply_lines = [
        "✅ تم تسجيل طلب التسعير.",
        f"رقم الطلب: {result['shipment_id']}",
        f"من {result['origin_city']} إلى {result['destination_city']}",
    ]
    if result.get("distance_km"):
        reply_lines.append(f"المسافة التقديرية: {result['distance_km']} كم")
    if result.get("suggested_price"):
        conf = confidence_labels.get(result.get("suggested_price_confidence", ""), "")
        n = result.get("suggested_price_sample_size", 0)
        reply_lines.append(
            f"💡 السعر المقترح (بناءً على {n} رحلة سابقة، {conf}): "
            f"{result['suggested_price']:.0f} ريال"
        )
    reply_lines.append(f"الطلبات المتبقية اليوم: {result['rate_limit_remaining']}")

    await message.answer("\n".join(reply_lines))
    await state.clear()
