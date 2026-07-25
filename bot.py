"""
Точка входа Админ-бота Apex (standalone, без FastAPI).

Запуск:
    python bot.py

На Railway: Start Command = python bot.py
Параллельно main.py (API + USER-бот) можно держать в другом сервисе
с RUN_ADMIN_BOT=0, чтобы не было TelegramConflictError.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# config валидирует env при импорте
from config import ADMIN_BOT_TOKEN, ADMIN_IDS
from database import DB_NAME, db_status, init_db
from bot.handlers import router as admin_router


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()

    token = (ADMIN_BOT_TOKEN or os.getenv("BOT_TOKEN", "")).strip()
    if not token:
        logging.error(
            "Не задан ADMIN_BOT_TOKEN (или BOT_TOKEN). "
            "Укажите токен админ-бота в переменных окружения Railway / .env"
        )
        sys.exit(1)

    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS пуст — админ-панель будет недоступна")

    logging.info("Entry: bot.py | db=%s | admins=%s", DB_NAME, ADMIN_IDS)

    await init_db()
    try:
        status = await db_status()
        logging.info("DB ready: %s", status)
    except Exception as exc:
        logging.warning("db_status: %s", exc)

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:
        logging.warning("delete_webhook: %s", exc)

    me = await bot.get_me()
    logging.info("Admin bot polling: @%s (id=%s)", me.username, me.id)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
