"""
Быстрые ответы на callback — меньше лагов и дублей меню.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

# user_id → message_id последнего меню (чтобы /start не плодил сообщения)
_last_menu_msg: dict[int, int] = {}


async def answer_cb(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception:
        pass


async def edit_screen(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    answer_text: str | None = None,
) -> None:
    """Сначала answer (кнопка «отпускается»), потом edit — без второго сообщения."""
    await answer_cb(callback, answer_text)
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
        if callback.from_user:
            _last_menu_msg[callback.from_user.id] = callback.message.message_id
        return
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        if "message to edit not found" in err or "message can't be edited" in err:
            msg = await callback.message.answer(text, reply_markup=reply_markup)
            if callback.from_user:
                _last_menu_msg[callback.from_user.id] = msg.message_id
            return
        logger.warning("edit_screen: %s", e)
    except Exception as e:
        logger.warning("edit_screen error: %s", e)
        try:
            msg = await callback.message.answer(text, reply_markup=reply_markup)
            if callback.from_user:
                _last_menu_msg[callback.from_user.id] = msg.message_id
        except Exception:
            pass


async def send_or_edit_menu(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """
    /start и /menu: правим старое меню, если есть, иначе шлём одно новое.
    Так не дублируется панель.
    """
    uid = message.from_user.id if message.from_user else 0
    mid = _last_menu_msg.get(uid)
    if mid and message.bot:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=mid,
                reply_markup=reply_markup,
            )
            return message  # type: ignore[return-value]
        except Exception:
            pass
    msg = await message.answer(text, reply_markup=reply_markup)
    _last_menu_msg[uid] = msg.message_id
    return msg


def remember_menu(user_id: int, message_id: int) -> None:
    _last_menu_msg[user_id] = message_id
