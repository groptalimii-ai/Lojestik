from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.api_client import RateLimitExceeded, backend
from bot.states import RegisterCarrierFlow

router = Router()


async def prompt_for_company_name(message: Message, state: FSMContext):
    await state.set_state(RegisterCarrierFlow.waiting_for_company_name)
    await message.answer("🚛 تسجيل ناقل جديد\nما اسم الشركة أو المالك؟")


@router.message(Command("registercarrier"))
async def cmd_registercarrier(message: Message, state: FSMContext):
    await prompt_for_company_name(message, state)


@router.message(RegisterCarrierFlow.waiting_for_company_name)
async def receive_company_name(message: Message, state: FSMContext):
    await state.update_data(company_name=message.text)
    await state.set_state(RegisterCarrierFlow.waiting_for_phone)
    await message.answer("ما رقم الجوال للتواصل؟")


@router.message(RegisterCarrierFlow.waiting_for_phone)
async def receive_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    # user_id is derived server-side from the JWT (see api/carriers.py) --
    # never sent by the client.
    payload = {
        "company_name": data.get("company_name"),
        "phone": message.text,
    }
    try:
        carrier = await backend.register_carrier(payload, message.from_user.id)
        await message.answer("✅ تم تسجيلك كناقل بنجاح.")
        from bot.handlers.truck import start_add_truck
        await start_add_truck(message, state, carrier["id"])
        return  # start_add_truck sets its own state; don't clear it below
    except RateLimitExceeded as e:
        await message.answer(f"🚫 {e.detail}")
    except Exception:
        await message.answer("⚠️ تعذر إتمام التسجيل. تواصل مع الدعم /support")
    await state.clear()
