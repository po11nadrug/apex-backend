"""
Админ-панель, встроенная в бэкенд (Railway).

Важно: сюда попадают апдейты, если на Railway включён polling
с тем же токеном, что и у локального админ-бота.
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS
from database import (
    get_all_users,
    get_user,
    update_balance,
    change_tariff,
    add_bonus,
    create_user,
)
from bot.keyboards import main_menu, user_actions, tariffs_keyboard

router = Router()
logger = logging.getLogger(__name__)


class EditBalance(StatesGroup):
    waiting_for_amount = State()


class AddBonus(StatesGroup):
    waiting_for_amount = State()


def _full_name(user) -> str | None:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or None


async def _register(message_or_cb) -> None:
    u = message_or_cb.from_user
    if not u:
        return
    try:
        user = await create_user(
            user_id=u.id,
            username=u.username,
            full_name=_full_name(u),
        )
        logger.info(
            "ADMIN register OK user_id=%s username=%s",
            user.user_id,
            user.username,
        )
    except Exception as exc:
        logger.exception("ADMIN register FAIL user_id=%s: %s", u.id, exc)


def _format_users_text(users) -> str:
    if not users:
        return (
            "<b>👥 Пользователи</b>\n\n"
            "В базе <b>0</b> пользователей.\n\n"
            "Они появляются, когда:\n"
            "• человек пишет боту <b>/start</b>\n"
            "• или открывает Mini App (POST /api/user/register)\n\n"
            "Напишите /start сами — вы должны появиться в списке."
        )

    lines = [f"<b>👥 Пользователи</b> · всего: <b>{len(users)}</b>\n"]
    for i, user in enumerate(users[:30], start=1):
        uname = f"@{user.username}" if user.username else "—"
        lines.append(
            f"{i}. <code>{user.user_id}</code> · {uname}\n"
            f"   {user.full_name or '—'} · <b>{user.tariff}</b> · "
            f"{user.balance:.2f} ₽"
        )
    if len(users) > 30:
        lines.append(f"\n… и ещё {len(users) - 30}")
    lines.append("\nНажмите кнопку пользователя ниже (если есть) или /start.")
    return "\n".join(lines)


async def _safe_edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            await callback.message.answer(text, reply_markup=reply_markup)
    try:
        await callback.answer()
    except Exception:
        pass


# ================== СТАРТ ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    await _register(message)
    logger.info(" /start from %s", message.from_user.id)

    if message.from_user.id not in ADMIN_IDS:
        await message.answer(
            "👋 Вы зарегистрированы в <b>Apex</b>.\n"
            f"ID: <code>{message.from_user.id}</code>\n\n"
            "Этот бот — панель администратора."
        )
        return

    await message.answer(
        "<b>⚡ Apex Admin Panel</b>\n\n"
        "Панель управления пользователями крипто-приложения Apex.\n\n"
        "Выберите раздел или команду /users:",
        reply_markup=main_menu(),
    )


@router.message(Command("users"))
async def cmd_users(message: Message):
    await _register(message)
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Нет доступа.")
        return
    users = await get_all_users()
    await message.answer(_format_users_text(users), reply_markup=main_menu())


# ================== СПИСОК ==================
@router.callback_query(F.data == "users_list")
async def users_list(callback: CallbackQuery):
    await _register(callback)
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    users = await get_all_users()
    logger.info("users_list: %s users", len(users))
    await _safe_edit(callback, _format_users_text(users), main_menu())


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    await _register(callback)
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

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
    await _safe_edit(callback, text, main_menu())


@router.callback_query(F.data.in_({"user_search", "transfers", "admin_logs"}))
async def soon(callback: CallbackQuery):
    await callback.answer("Этот раздел скоро будет добавлен", show_alert=True)


# Опциональные экшены (если кнопки есть)
@router.callback_query(F.data.startswith("edit_balance:"))
async def edit_balance_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(EditBalance.waiting_for_amount)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer(
        f"Введите новый баланс для <code>{user_id}</code>:"
    )
    await callback.answer()


@router.message(EditBalance.waiting_for_amount)
async def edit_balance_amount(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    user_id = data.get("target_user_id")
    try:
        amount = float((message.text or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer("Введите число.")
        return
    await update_balance(user_id, amount, admin_id=message.from_user.id)
    await state.clear()
    await message.answer(f"✅ Баланс {user_id} = {amount:.2f} ₽")


@router.callback_query(F.data.startswith("set_tariff:"))
async def set_tariff_cb(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔", show_alert=True)
        return
    _, uid, tariff = callback.data.split(":", 2)
    await change_tariff(int(uid), tariff, admin_id=callback.from_user.id)
    await callback.answer("Тариф обновлён")
    await callback.message.answer(f"✅ Тариф {uid} → {tariff}")


@router.callback_query(F.data.startswith("add_bonus:"))
async def add_bonus_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(AddBonus.waiting_for_amount)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer(f"Сумма бонуса для <code>{user_id}</code>:")
    await callback.answer()


@router.message(AddBonus.waiting_for_amount)
async def add_bonus_amount(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    user_id = data.get("target_user_id")
    try:
        amount = float((message.text or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer("Введите число.")
        return
    await add_bonus(user_id, amount, admin_id=message.from_user.id)
    await state.clear()
    await message.answer(f"✅ Бонус +{amount:.2f} ₽ пользователю {user_id}")
