from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from database import get_all_users, get_user, update_balance, change_tariff, add_bonus
from bot.keyboards import main_menu, user_actions, tariffs_keyboard

router = Router()

class EditBalance(StatesGroup):
    waiting_for_amount = State()

class AddBonus(StatesGroup):
    waiting_for_amount = State()

# ================== СТАРТ ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет доступа.")
        return

    await message.answer(
        "<b>⚡ Apex Admin Panel</b>\n\n"
        "Панель управления пользователями крипто-приложения Apex.\n\n"
        "Выберите раздел:",
        reply_markup=main_menu()
    )

# ================== ГЛАВНОЕ МЕНЮ ==================
@router.callback_query(F.data == "users_list")
async def users_list(callback: CallbackQuery):
    users = await get_all_users()

    if not users:
        await callback.message.edit_text("Пользователей пока нет.", reply_markup=main_menu())
        return

    text = "<b>👥 Список пользователей:</b>\n\n"
    for user in users[:15]:  # показываем первых 15
        text += (
            f"ID: <code>{user.user_id}</code>\n"
            f"Имя: {user.full_name or '—'}\n"
            f"Тариф: <b>{user.tariff}</b> | Баланс: <b>{user.balance:.2f} ₽</b>\n"
            f"──────────────\n"
        )

    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()

@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    users = await get_all_users()
    total_users = len(users)
    total_balance = sum(u.balance for u in users)
    
    lite = sum(1 for u in users if u.tariff == "LITE")
    power = sum(1 for u in users if u.tariff == "POWER")
    power_plus = sum(1 for u in users if u.tariff == "POWER+")

    text = (
        f"<b>📊 Статистика</b>\n\n"
        f"Всего пользователей: <b>{total_users}</b>\n"
        f"Общий баланс: <b>{total_balance:.2f} ₽</b>\n\n"
        f"LITE: {lite}\n"
        f"POWER: {power}\n"
        f"POWER+: {power_plus}"
    )
    await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()

@router.callback_query(F.data.in_({"user_search", "transfers", "admin_logs"}))
async def soon(callback: CallbackQuery):
    await callback.answer("Этот раздел скоро будет добавлен", show_alert=True)