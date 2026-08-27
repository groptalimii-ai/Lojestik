from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import main_menu
from bot.states import NewLoadFlow, RegisterCarrierFlow

router = Router()

WELCOME = (
    "أهلًا بك في FreightAI Saudi 🚛\n\n"
    "منصة ذكية لربط أصحاب الحمولات بالناقلين.\n"
    "اختر ما تريد فعله:"
)

HELP_TEXT = (
    "الأوامر المتاحة:\n"
    "/newload - إضافة حمولة جديدة\n"
    "/myloads - عرض طلباتي\n"
    "/findtruck - البحث عن شاحنة\n"
    "/registercarrier - تسجيل كناقل\n"
    "/mytrucks - شاحناتي\n"
    "/mydeals - صفقاتي وأرباحي\n"
    "/support - التواصل مع الدعم"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("support"))
async def cmd_support(message: Message):
    await message.answer("📞 للتواصل مع الدعم، أرسل رسالتك هنا وسيتم الرد عليك في أقرب وقت.")


@router.callback_query(F.data == "menu:newload")
async def menu_newload(callback: CallbackQuery, state: FSMContext):
    from bot.handlers.newload import prompt_for_load_text
    await prompt_for_load_text(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "menu:registercarrier")
async def menu_register_carrier(callback: CallbackQuery, state: FSMContext):
    from bot.handlers.carrier import prompt_for_company_name
    await prompt_for_company_name(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def menu_support(callback: CallbackQuery):
    await callback.message.answer("📞 أرسل رسالتك وسيتواصل معك فريق الدعم.")
    await callback.answer()


@router.callback_query(F.data.in_({"menu:findload", "menu:myloads", "menu:mydeals"}))
async def menu_placeholder(callback: CallbackQuery):
    await callback.message.answer("هذه الميزة قيد التطوير في المرحلة القادمة 🚧")
    await callback.answer()
