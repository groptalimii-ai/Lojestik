"""
Manual data-collection channel.

The operator pastes free-text messages about carriers or loads directly
into their own private Telegram chat with the bot -- no commands, no FSM.
Restricted to TELEGRAM_ADMIN_CHAT_ID so this never fires on a regular
driver/shipper's free-text message anywhere else in the bot; StateFilter(None)
additionally ensures it only fires when the operator isn't mid-way through
some other flow (e.g. /newload) themselves.

Examples the operator sends here:
    ابو سعد سطحه من الدمام للرياض رقم التواصل 05xxxxxxxx
    خالد حمولة 29 طن من الرياض لجدة السعر 3000 رقم التواصل 05xxxxxxxx

The backend (see backend/app/api/intake.py) classifies each message by a
simple keyword rule ("حمولة"/"طن" => load, else carrier), extracts fields
via Claude, and stores it in the matching permanent table.
"""
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from httpx import HTTPStatusError

from bot.api_client import RateLimitExceeded, backend
from bot.config import TELEGRAM_ADMIN_CHAT_ID

router = Router()

LEAD_TYPE_LABELS = {"load": "📦 صاحب حمولة", "carrier": "🚚 ناقل"}


def _is_admin_channel(message: Message) -> bool:
    return bool(TELEGRAM_ADMIN_CHAT_ID) and str(message.chat.id) == str(TELEGRAM_ADMIN_CHAT_ID)


@router.message(StateFilter(None), _is_admin_channel)
async def handle_intake_message(message: Message):
    if not message.text:
        return  # ignore stickers/photos/etc. in this channel, text only

    try:
        result = await backend.submit_intake(message.text, message.from_user.id)
    except RateLimitExceeded as e:
        await message.answer(f"🚫 {e.detail}")
        return
    except HTTPStatusError as e:
        # BUG FIXED: this used to show the SAME "check if you're admin"
        # message for every kind of failure, which is actively misleading
        # for anything that isn't actually a 403 -- e.g. it would tell you
        # to check your admin status for a genuine 500 server bug, wasting
        # your time debugging the wrong thing. Branch on the real status.
        if e.response.status_code == 403:
            await message.answer(
                "🚫 حسابك مو مفعّل كـ admin بعد. شغّل:\n"
                "python scripts/promote_admin.py <telegram_id>"
            )
        elif e.response.status_code == 422:
            await message.answer("⚠️ الرسالة طويلة جدًا أو فيها مشكلة تنسيق (الحد الأقصى 2000 حرف).")
        else:
            detail = "-"
            try:
                detail = e.response.json().get("detail", "-")
            except Exception:
                pass
            await message.answer(f"⚠️ خطأ من الخادم ({e.response.status_code}): {detail}")
        return
    except Exception:
        await message.answer("⚠️ تعذر الاتصال بالخادم. تأكد إن الباك-إند شغّال وحاول مرة أخرى.")
        return

    lead_type = result.get("lead_type", "")
    header = "⚠️ تم الحفظ لكن يحتاج مراجعة" if result.get("needs_review") else "✅ تم الحفظ"
    lines = [f"{header} ({LEAD_TYPE_LABELS.get(lead_type, lead_type)})"]

    if result.get("contact_name"):
        lines.append(f"الاسم: {result['contact_name']}")
    if result.get("phone"):
        lines.append(f"الجوال: {result['phone']}")
    if result.get("origin_city") or result.get("destination_city"):
        lines.append(f"المسار: {result.get('origin_city') or '؟'} → {result.get('destination_city') or '؟'}")
    if lead_type == "carrier" and result.get("truck_type"):
        lines.append(f"نوع الشاحنة: {result['truck_type']}")
    if lead_type == "load":
        if result.get("weight_tons"):
            lines.append(f"الوزن: {result['weight_tons']} طن")
        if result.get("price"):
            lines.append(f"السعر: {result['price']} ريال")

    activity = result.get("carrier_activity")
    if activity:
        n = activity.get("total_appearances", 1)
        if n > 1:
            lines.append(f"📊 هذا الرقم مسجّل سابقًا {n} مرات (أول ظهور: {activity.get('first_seen_at')})")

    matches = result.get("matches") or []
    if matches:
        opposite_label = "🎯 نقلات على نفس المسار" if lead_type == "load" else "🎯 حمولات على نفس المسار"
        lines.append(f"\n{opposite_label}:")
        for m in matches:
            name = m.get("contact_name") or "بدون اسم"
            phone = m.get("phone") or "-"
            lines.append(f"• {name} — {phone}")

    await message.answer("\n".join(lines))
