"""
Точка входа Админ-бота Apex.

Запуск:
    python bot.py

Независим от FastAPI (main.py): только aiogram polling + SQLite.
На Railway Start Command: python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Корень проекта в sys.path (на случай запуска не из /app)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_IDS, BOT_TOKEN, DATABASE_PATH, SEED_DEMO_USERS
from database import db
from handlers import setup_routers
from middlewares import AdminOnlyMiddleware


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def on_startup(bot: Bot) -> None:
    await db.connect()
    seeded = 0
    if SEED_DEMO_USERS:
        seeded = await db.seed_demo_users()

    # Админов в список клиентов НЕ добавляем —
    # туда попадают только /start у бота приложения

    me = await bot.get_me()
    users_count = await db.get_users_count()
    logging.info("Bot started: @%s (id=%s)", me.username, me.id)
    logging.info("Database: %s", DATABASE_PATH)
    logging.info("App users in DB: %s", users_count)
    logging.info("Admins: %s", ADMIN_IDS or "(не заданы!)")
    if seeded:
        logging.info("Seeded %s demo users into empty database", seeded)

    # Проталкиваем локальные балансы/тарифы в API Mini App (если API_URL задан)
    try:
        from api_client import set_balance_remote, set_tariff_remote

        page = 0
        pushed = 0
        while True:
            batch = await db.get_users_page(page, 50)
            if not batch:
                break
            for u in batch:
                uid = int(u["user_id"])
                if uid < 10_000:
                    continue
                ok_b = set_balance_remote(
                    uid,
                    float(u.get("balance") or 0),
                    description="startup sync admin→api",
                    mode="set",
                )
                tariff = str(u.get("tariff") or "LITE")
                ok_t = set_tariff_remote(uid, tariff)
                if ok_b or ok_t:
                    pushed += 1
            if len(batch) < 50:
                break
            page += 1
        logging.info("Synced %s users to Mini App API on startup", pushed)
    except Exception as exc:
        logging.warning("Startup API sync skipped: %s", exc)

    # Синхронизация заявок из бэкенда в локальную БД
    try:
        from api_client import sync_applications_from_api

        synced = await sync_applications_from_api(db)
        logging.info("Synced %s applications from API to local DB", synced)
    except Exception as exc:
        logging.warning("Applications sync skipped: %s", exc)


async def on_shutdown(bot: Bot) -> None:
    await db.close()
    logging.info("Bot stopped, database closed")


async def main() -> None:
    setup_logging()

    if not BOT_TOKEN:
        logging.error(
            "BOT_TOKEN не задан. Укажите BOT_TOKEN или ADMIN_BOT_TOKEN "
            "в переменных окружения / .env (см. .env.example)"
        )
        sys.exit(1)

    if not ADMIN_IDS:
        logging.warning(
            "ADMIN_IDS пуст — никто не сможет пользоваться ботом. "
            "Укажите ID в .env"
        )

    logging.info("Entry: bot.py | cwd=%s | db=%s", os.getcwd(), DATABASE_PATH)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Доступ только админам — на все update
    dp.message.middleware(AdminOnlyMiddleware())
    dp.callback_query.middleware(AdminOnlyMiddleware())

    setup_routers(dp)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:
        logging.warning("delete_webhook: %s", exc)

    logging.info("Starting aiogram polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
