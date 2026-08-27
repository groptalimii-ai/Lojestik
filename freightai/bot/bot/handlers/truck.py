from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import RateLimitExceeded, backend
from bot.keyboards import yes_no_kb
from bot.states import AddTruckFlow

router = Router()


async def start_add_truck(message: Message, state: FSMContext, carrier_id: str):
    await state.update_data(carrier_id=carrier_id)
    await state.set_state(AddTruckFlow.waiting_for_head_type)
    await message.answer("🚛 إضافة شاحنة جديدة\nما نوع الرأس؟ (مثال: Actros, Volvo FH...)")


@router.message(Command("mytrucks"))
async def cmd_mytrucks(message: Message, state: FSMContext):
    await state.set_state(AddTruckFlow.waiting_for_phone_lookup)
    await message.answer(
        "لعرض شاحناتك أو إضافة شاحنة جديدة، أرسل رقم الجوال المسجّل به حسابك كناقل:"
    )


@router.message(AddTruckFlow.waiting_for_phone_lookup)
async def lookup_carrier_by_phone(message: Message, state: FSMContext):
    carrier = await backend.get_carrier_by_phone(message.text.strip(), message.from_user.id)
    if not carrier:
        await message.answer(
            "لم أجد ناقلًا مسجّلًا بهذا الرقم. سجّل أولًا عبر /registercarrier"
        )
        await state.clear()
        return

    trucks = await backend.list_carrier_trucks(carrier["id"], message.from_user.id)
    if trucks:
        lines = [
            f"🚛 {t.get('head_type') or '—'} | {t.get('trailer_type') or '—'} | "
            f"{t.get('max_weight_tons') or '—'} طن | 📍 {t.get('current_location') or '—'}"
            for t in trucks
        ]
        await message.answer("شاحناتك المسجّلة:\n" + "\n".join(lines))

    await start_add_truck(message, state, carrier["id"])


@router.message(AddTruckFlow.waiting_for_head_type)
async def receive_head_type(message: Message, state: FSMContext):
    await state.update_data(head_type=message.text)
    await state.set_state(AddTruckFlow.waiting_for_trailer_type)
    await message.answer("ما نوع المقطورة؟ (ستارة / صندوق / سطحة / مبرّدة...)")


@router.message(AddTruckFlow.waiting_for_trailer_type)
async def receive_trailer_type(message: Message, state: FSMContext):
    await state.update_data(trailer_type=message.text)
    await state.set_state(AddTruckFlow.waiting_for_max_weight)
    await message.answer("ما الحمولة القصوى بالطن؟")


@router.message(AddTruckFlow.waiting_for_max_weight)
async def receive_max_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip())
    except ValueError:
        await message.answer("الرجاء إدخال رقم صحيح للوزن، مثال: 30")
        return
    await state.update_data(max_weight_tons=weight)
    await state.set_state(AddTruckFlow.waiting_for_current_location)
    await message.answer("ما الموقع الحالي للشاحنة؟")


@router.message(AddTruckFlow.waiting_for_current_location)
async def receive_current_location(message: Message, state: FSMContext):
    await state.update_data(current_location=message.text)
    await state.set_state(AddTruckFlow.waiting_for_routes)
    await message.answer("ما الخطوط التي تعمل عليها الشاحنة؟ (افصل بينها بفاصلة، مثال: Riyadh,Amman)")


@router.message(AddTruckFlow.waiting_for_routes)
async def receive_routes(message: Message, state: FSMContext):
    await state.update_data(routes=message.text)
    await state.set_state(AddTruckFlow.waiting_for_available_date)
    await message.answer("متى تصبح الشاحنة متاحة؟ (مثال: 2026-08-25 أو \"الخميس\")")


@router.message(AddTruckFlow.waiting_for_available_date)
async def receive_available_date(message: Message, state: FSMContext):
    await state.update_data(available_date_raw=message.text)
    await state.set_state(AddTruckFlow.waiting_for_price)
    await message.answer("ما السعر التقريبي المطلوب (بالريال)؟ اكتب 0 إذا لم تحدده الآن")


@router.message(AddTruckFlow.waiting_for_price)
async def receive_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("الرجاء إدخال رقم، مثال: 9000 أو 0")
        return
    await state.update_data(approximate_price=price or None)
    await state.set_state(AddTruckFlow.waiting_for_return_load)
    await message.answer(
        "هل لدى الشاحنة حمولة عودة متاحة؟",
        reply_markup=yes_no_kb("truck:return:yes", "truck:return:no"),
    )


@router.callback_query(F.data.in_({"truck:return:yes", "truck:return:no"}), AddTruckFlow.waiting_for_return_load)
async def receive_return_load(callback: CallbackQuery, state: FSMContext):
    has_return = callback.data.endswith("yes")
    data = await state.get_data()

    payload = {
        "carrier_id": data["carrier_id"],
        "head_type": data.get("head_type"),
        "trailer_type": data.get("trailer_type"),
        "max_weight_tons": data.get("max_weight_tons"),
        "current_location": data.get("current_location"),
        "routes": data.get("routes"),
        "approximate_price": data.get("approximate_price"),
        "has_return_load": has_return,
        # Sent as raw text; the backend normalizes it into a real datetime
        # via app.services.date_normalizer before storing it.
        "available_from_text": data.get("available_date_raw"),
    }

    try:
        await backend.add_truck(payload, callback.from_user.id)
        await callback.message.answer("✅ تمت إضافة الشاحنة بنجاح. يمكنك إضافة شاحنة أخرى عبر /mytrucks")
    except RateLimitExceeded as e:
        await callback.message.answer(f"🚫 {e.detail}")
    except Exception:
        await callback.message.answer("⚠️ تعذر حفظ بيانات الشاحنة. تواصل مع الدعم /support")

    await state.clear()
    await callback.answer()
