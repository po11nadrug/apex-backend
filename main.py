"""
Apex Backend:
  - FastAPI /api  — регистрация Mini App, баланс, список юзеров
  - USER bot      — клиенты жмут /start → появляются в базе
  - ADMIN bot     — опционально (лучше отдельный локальный админ-бот)

Важно: у одного токена может быть только ОДИН getUpdates (polling).
Не запускайте тот же бот локально и на Railway одновременно —
будет TelegramConflictError.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError

from config import ADMIN_BOT_TOKEN, USER_BOT_TOKEN
from database import init_db, db_status, DB_NAME
from api.routes import router as api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RUN_ADMIN_BOT = os.getenv("RUN_ADMIN_BOT", "0").strip().lower() in {
    "1", "true", "yes", "on",
}
# Бот приложения по умолчанию ВКЛ — это источник пользователей
RUN_USER_BOT = os.getenv("RUN_USER_BOT", "1").strip().lower() in {
    "1", "true", "yes", "on",
}

user_bot: Bot | None = None
admin_bot: Bot | None = None


def _bot_id(token: str) -> str:
    """Числовой id бота из токена (до ':')."""
    return token.split(":", 1)[0].strip() if token else ""


async def _start_polling(
    *,
    label: str,
    token: str,
    router,
    tasks: list[asyncio.Task],
    active_bot_ids: set[str],
) -> Bot | None:
    """
    Запускает polling для бота. Пропускает дубликат токена
    (два poller'а на один bot id = гарантированный Conflict).
    """
    bid = _bot_id(token)
    if not bid:
        logger.error("%s: пустой токен — polling не запущен", label)
        return None
    if bid in active_bot_ids:
        logger.error(
            "%s: токен уже используется другим poller'ом (bot id=%s). "
            "Один токен = один instance. Пропуск.",
            label,
            bid,
        )
        return None

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    try:
        # Снимаем webhook и ждём, чтобы предыдущий instance (redeploy)
        # успел отпустить getUpdates — снижает Conflict при деплое.
        await bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(1.5)
        me = await bot.get_me()
        active_bot_ids.add(bid)
        tasks.append(
            asyncio.create_task(
                dp.start_polling(bot, handle_signals=False),
                name=f"poll-{label}",
            )
        )
        logger.info("%s polling ВКЛЮЧЁН: @%s (id=%s)", label, me.username, me.id)
        return bot
    except TelegramUnauthorizedError:
        logger.error(
            "%s: Unauthorized — неверный/отозванный токен. Обновите в env.",
            label,
        )
        await bot.session.close()
        return None
    except TelegramConflictError:
        logger.error(
            "%s: Conflict — другой процесс уже делает getUpdates для этого бота. "
            "Остановите локальный main.py / второй реплик Railway / дубль сервиса. "
            "Должен остаться ровно один poller.",
            label,
        )
        await bot.session.close()
        return None
    except Exception as exc:
        logger.error(
            "%s не стартовал: %s. API продолжит работу.",
            label,
            exc,
        )
        await bot.session.close()
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global user_bot, admin_bot

    logger.info("Инициализация базы данных → %s", DB_NAME)
    await init_db()
    status = await db_status()
    logger.info(
        "База готова: users=%s size=%s path=%s",
        status["users"],
        status["size_bytes"],
        status["path"],
    )

    tasks: list[asyncio.Task] = []
    active_bot_ids: set[str] = set()

    # ——— Бот ПРИЛОЖЕНИЯ (клиенты) ———
    if RUN_USER_BOT and USER_BOT_TOKEN:
        from bot.user_bot import router as user_router

        user_bot = await _start_polling(
            label="USER-бот",
            token=USER_BOT_TOKEN,
            router=user_router,
            tasks=tasks,
            active_bot_ids=active_bot_ids,
        )
    else:
        logger.warning(
            "USER-бот НЕ запущен. На Railway: USER_BOT_TOKEN + RUN_USER_BOT=1. "
            "Локально держите RUN_USER_BOT=0, если бот уже крутится на Railway."
        )

    # ——— Админ-бот (обычно выключен на Railway — панель локально) ———
    if RUN_ADMIN_BOT and ADMIN_BOT_TOKEN:
        from bot.handlers import router as admin_router

        admin_bot = await _start_polling(
            label="ADMIN-бот",
            token=ADMIN_BOT_TOKEN,
            router=admin_router,
            tasks=tasks,
            active_bot_ids=active_bot_ids,
        )
    else:
        logger.info("ADMIN-бот polling выключен (RUN_ADMIN_BOT=0)")

    yield

    for t in tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    if user_bot:
        await user_bot.session.close()
    if admin_bot:
        await admin_bot.session.close()
    logger.info("Остановка backend")


app = FastAPI(title="Apex Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # credentials=True + origins=* ломает CORS в WebView Telegram
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    try:
        status = await db_status()
    except Exception as exc:
        status = {"error": str(exc), "path": DB_NAME}
    return {
        "status": "ok",
        "message": "Apex Backend",
        "user_bot": bool(RUN_USER_BOT and USER_BOT_TOKEN),
        "admin_bot": bool(RUN_ADMIN_BOT and ADMIN_BOT_TOKEN),
        "database": status,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
