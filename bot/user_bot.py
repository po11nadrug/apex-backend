"""
Бот ПРИЛОЖЕНИЯ Apex (клиенты).

/start и любое сообщение → запись в SQLite → ответ с данными ИЗ БД.
Если запись не удалась — пользователю видно ошибку, в логах traceback.
"""

from __future__ import annotations

import logging
import os
import traceback

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from database import create_user, get_user, DB_NAME

router = Router(name="user_bot")
logger = logging.getLogger(__name__)

WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()


def _full_name(user) -> str | None:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or None


def start_keyboard() -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть Apex",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )


async def _save_user(message: Message):
    """Сохранить пользователя и вернуть запись из БД. None при ошибке."""
    u = message.from_user
    if not u:
        return None

    try:
        existed = await get_user(u.id)
        user = await create_user(
            user_id=u.id,
            username=u.username,
            full_name=_full_name(u),
        )
        # Повторное чтение — гарантия, что файл реально содержит строку
        fresh = await get_user(u.id)
        if fresh is None:
            raise RuntimeError(
                f"После create_user user_id={u.id} не читается из {DB_NAME}"
            )
        logger.info(
            "APP save OK user_id=%s new=%s username=%s balance=%.2f db=%s",
            fresh.user_id,
            existed is None,
            fresh.username,
            fresh.balance,
            DB_NAME,
        )
        return fresh, existed is None
    except Exception as exc:
        logger.error(
            "APP save FAIL user_id=%s db=%s err=%s\n%s",
            u.id,
            DB_NAME,
            exc,
            traceback.format_exc(),
        )
        await message.answer(
            "⚠️ Не удалось сохранить данные в базу.\n"
            f"Ошибка: <code>{exc}</code>\n"
            "Напишите /start ещё раз или сообщите администратору."
        )
        return None


@router.message(CommandStart())
async def user_start(message: Message) -> None:
    result = await _save_user(message)
    if result is None:
        return

    fresh, is_new = result
    title = "Регистрация пройдена" if is_new else "С возвращением"
    text = (
        f"<b>⚡ Apex</b>\n\n"
        f"✅ <b>{title}</b>\n\n"
        f"Ваш ID: <code>{fresh.user_id}</code>\n"
        f"Тариф: <b>{fresh.tariff}</b>\n"
        f"Баланс: <b>{fresh.balance:,.2f} ₽</b>\n\n"
        f"Данные сохранены в базе.\n"
        f"Пополнить счёт самостоятельно нельзя — "
        f"после перевода напишите оператору, зачисление сделает администратор."
    )
    if not WEBAPP_URL:
        text += (
            "\n\n⚠️ Mini App: откройте через кнопку меню бота "
            "(если настроена в BotFather)."
        )

    await message.answer(text, reply_markup=start_keyboard())


@router.message(Command("id"))
async def user_id_cmd(message: Message) -> None:
    await _save_user(message)
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>"
    )


@router.message(Command("me"))
async def user_me_cmd(message: Message) -> None:
    """Показать профиль строго из БД (проверка, что запись жива)."""
    result = await _save_user(message)
    if result is None:
        return
    fresh, _ = result
    await message.answer(
        f"<b>Профиль из БД</b>\n"
        f"ID: <code>{fresh.user_id}</code>\n"
        f"Username: @{fresh.username or '—'}\n"
        f"Имя: {fresh.full_name or '—'}\n"
        f"Тариф: <b>{fresh.tariff}</b>\n"
        f"Баланс: <b>{fresh.balance:,.2f} ₽</b>\n"
        f"Бонус: <b>{fresh.bonus_balance:,.2f} ₽</b>\n"
        f"Регистрация: {fresh.registered_at or '—'}"
    )


@router.message(F.text)
async def user_any_text(message: Message) -> None:
    """Любой текст тоже пишет пользователя в БД."""
    result = await _save_user(message)
    if result is None:
        return
    await message.answer(
        "Нажмите /start, чтобы открыть Apex.\n"
        "Или /me — посмотреть профиль из базы.",
        reply_markup=start_keyboard(),
    )
