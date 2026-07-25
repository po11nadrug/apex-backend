"""
Админ-бот: доступ только ADMIN_IDS.
Пользователей приложения сюда НЕ пишем — они приходят из API (бот приложения / Mini App).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or getattr(user, "is_bot", False):
            return None

        if user.id not in ADMIN_IDS:
            if isinstance(event, Message):
                await event.answer(
                    "⛔ Это <b>админ-бот</b> Apex.\n\n"
                    "Клиентам нужен <b>бот приложения</b> (где /start и Mini App).\n"
                    "Сюда пишут только администраторы."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Только для администраторов", show_alert=True)
            return None

        return await handler(event, data)
