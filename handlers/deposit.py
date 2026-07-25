"""
Пополнение баланса:
  1) ID + сумма
  2) подтверждение (кнопки с данными в callback_data — без потери FSM)
  3) зачисление + история + API Mini App
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api_client import set_balance_remote
from database import db, format_money
from keyboards import cancel_deposit_kb, deposit_kb, user_card_kb
from states import DepositUser
from ui import answer_cb, edit_screen
from .users import render_user_card

router = Router(name="deposit")
logger = logging.getLogger(__name__)

DEPOSIT_HELP = (
    "<b>💳 Пополнение баланса</b>\n\n"
    "Зачислите средства клиенту после подтверждения платежа.\n\n"
    "Нажмите «Пополнить баланс» и отправьте данные по шаблону."
)

DEPOSIT_TEMPLATE = (
    "<b>💳 Пополнение</b>\n\n"
    "Отправьте <b>одним сообщением</b> ID и сумму:\n\n"
    "<code>ID_ПОЛЬЗОВАТЕЛЯ СУММА</code>\n\n"
    "<b>Примеры:</b>\n"
    "• <code>8271488006 1500</code>\n"
    "• <code>8271488006 1500.50</code>\n\n"
    "После ввода придёт <b>подтверждение</b> операции."
)


def _parse_deposit(text: str) -> tuple[int, float] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.match(
        r"^(\d{5,15})\s*[;,\s]+\s*([0-9]+(?:[.,][0-9]+)?)\s*$",
        raw.replace("\n", " "),
    )
    if m:
        return int(m.group(1)), float(m.group(2).replace(",", "."))
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 2 and lines[0].isdigit():
        try:
            return int(lines[0]), float(lines[1].replace(",", ".").replace(" ", ""))
        except ValueError:
            return None
    return None


def _confirm_text(user: dict, amount: float) -> str:
    uid = user["user_id"]
    uname = f"@{user['username']}" if user.get("username") else "—"
    old = float(user.get("balance") or 0)
    new = round(old + amount, 2)
    return (
        f"<b>⚠️ Подтверждение пополнения</b>\n"
        f"{'─' * 28}\n\n"
        f"<b>ID:</b> <code>{uid}</code>\n"
        f"<b>Username:</b> {uname}\n"
        f"<b>Имя:</b> {user.get('full_name') or '—'}\n\n"
        f"<b>Сумма пополнения:</b> +{format_money(amount)}\n"
        f"<b>Баланс сейчас:</b> {format_money(old)}\n"
        f"<b>Станет:</b> <b>{format_money(new)}</b>\n\n"
        f"Нажмите <b>Подтвердить</b>, чтобы зачислить средства\n"
        f"в базу и в Mini App, или <b>Отмена</b>."
    )


def deposit_confirm_kb(user_id: int, amount: float) -> InlineKeyboardMarkup:
    """
    ID и сумма в callback_data — подтверждение работает
    даже если FSM сбросился (рестарт бота и т.п.).
    Telegram limit ~64 байта.
    """
    # amount как целое в копейках, чтобы не было точки в callback
    cents = int(round(float(amount) * 100))
    data_ok = f"deposit:ok:{user_id}:{cents}"
    if len(data_ok) > 64:
        # fallback — только id, сумму не влезло (маловероятно)
        data_ok = f"deposit:ok:{user_id}:{cents}"[:64]
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=data_ok),
        InlineKeyboardButton(text="❌ Отмена", callback_data="deposit:no"),
    )
    return builder.as_markup()


@router.callback_query(F.data == "deposit:start")
async def cb_deposit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_screen(callback, DEPOSIT_HELP, deposit_kb())


@router.callback_query(F.data == "deposit:form")
async def cb_deposit_form(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DepositUser.waiting_data)
    await edit_screen(callback, DEPOSIT_TEMPLATE, cancel_deposit_kb())


@router.message(DepositUser.waiting_data)
async def msg_deposit_data(message: Message, state: FSMContext) -> None:
    parsed = _parse_deposit(message.text or "")
    if not parsed:
        await message.answer(
            "❌ Неверный формат.\n\n"
            "Нужно: <code>ID СУММА</code>\n"
            "Пример: <code>8271488006 1500</code>",
            reply_markup=cancel_deposit_kb(),
        )
        return

    user_id, amount = parsed
    if amount <= 0:
        await message.answer(
            "❌ Сумма должна быть больше нуля.",
            reply_markup=cancel_deposit_kb(),
        )
        return

    user = await db.get_user(user_id)
    if not user:
        await db.ensure_user(user_id)
        user = await db.get_user(user_id)
    if not user:
        await message.answer(
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            reply_markup=cancel_deposit_kb(),
        )
        return

    # FSM больше не обязателен для confirm — данные в кнопке
    await state.clear()
    amount = round(float(amount), 2)

    await message.answer(
        _confirm_text(user, amount),
        reply_markup=deposit_confirm_kb(user_id, amount),
    )


@router.callback_query(F.data == "deposit:no")
async def cb_deposit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_screen(
        callback,
        "❌ <b>Пополнение отменено</b>\n\nОперация не выполнена.",
        deposit_kb(),
    )


@router.callback_query(F.data.startswith("deposit:ok:"))
async def cb_deposit_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Подтверждение: сразу answer (кнопка «отпускается»),
    потом БД → API → сообщение об успехе.
    """
    await state.clear()
    # Мгновенно гасим «часики» на кнопке
    await answer_cb(callback, "Зачисляю…")

    try:
        parts = callback.data.split(":")
        # deposit:ok:{user_id}:{cents}
        user_id = int(parts[2])
        cents = int(parts[3])
        amount = round(cents / 100.0, 2)
    except (IndexError, ValueError) as e:
        logger.exception("bad deposit callback: %s", callback.data)
        await edit_screen(
            callback,
            "❌ Ошибка данных кнопки. Начните пополнение заново.",
            deposit_kb(),
        )
        return

    if amount <= 0:
        await edit_screen(callback, "❌ Некорректная сумма.", deposit_kb())
        return

    try:
        user = await db.get_user(user_id)
        if not user:
            await db.ensure_user(user_id)
            user = await db.get_user(user_id)
        if not user:
            await edit_screen(
                callback,
                f"❌ Пользователь <code>{user_id}</code> не найден.",
                deposit_kb(),
            )
            return

        old = float(user["balance"] or 0)
        admin_id = callback.from_user.id if callback.from_user else None

        updated = await db.change_balance(
            user_id,
            amount,
            tx_type="deposit",
            comment=f"Пополнение +{amount}",
            admin_id=admin_id,
        )
        if not updated:
            await edit_screen(
                callback,
                "❌ Не удалось обновить баланс в базе.",
                deposit_kb(),
            )
            return

        # Mini App API — в try, чтобы ошибка сети не «съела» ответ
        api_ok = False
        try:
            api_ok = set_balance_remote(
                user_id,
                float(updated["balance"]),
                description=f"Пополнение +{amount}",
                mode="set",
            )
        except Exception:
            logger.exception("set_balance_remote failed")

        try:
            await db.log_admin(
                admin_id=admin_id or 0,
                action="deposit",
                target_id=user_id,
                details=f"+{amount}; {old} → {updated['balance']}; api={api_ok}",
            )
        except Exception:
            logger.exception("log_admin failed")

        api_note = (
            "✅ Баланс обновлён в Mini App"
            if api_ok
            else "⚠️ Локально зачислено; API Mini App недоступен "
            "(запустите бэкенд: python main.py)"
        )

        text = (
            f"✅ <b>Баланс успешно пополнен</b>\n\n"
            f"ID: <code>{user_id}</code>\n"
            f"Сумма: <b>+{format_money(amount)}</b>\n"
            f"Было: {format_money(old)}\n"
            f"Стало: <b>{format_money(updated['balance'])}</b>\n"
            f"{api_note}\n\n"
            f"Операция добавлена в историю.\n\n"
            + render_user_card(updated)
        )

        # edit_screen снова answer — уже ответили, answer_cb глотает ошибку
        try:
            await callback.message.edit_text(text, reply_markup=user_card_kb(updated))
        except Exception as e:
            logger.warning("edit after deposit failed: %s — send new", e)
            await callback.message.answer(text, reply_markup=user_card_kb(updated))

        logger.info(
            "deposit ok user=%s amount=%s new=%s api=%s",
            user_id,
            amount,
            updated["balance"],
            api_ok,
        )
    except Exception:
        logger.exception("deposit confirm crashed")
        try:
            await callback.message.edit_text(
                "❌ Ошибка при пополнении. Смотрите логи бота.",
                reply_markup=deposit_kb(),
            )
        except Exception:
            await callback.message.answer(
                "❌ Ошибка при пополнении. Смотрите логи бота.",
                reply_markup=deposit_kb(),
            )
