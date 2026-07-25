"""
Apex Backend: только FastAPI + SQLite.

Telegram-боты сюда НЕ подключаются (polling = конфликты / ImportError).
Админ-бот:  python bot.py
User-бот:   отдельный процесс, если нужен.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, db_status, DB_NAME, db as database
from api.routes import router as api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт: БД. Стоп: закрыть соединение. Без Telegram polling."""
    logger.info("Инициализация базы данных → %s", DB_NAME)
    await init_db()
    status = await db_status()
    logger.info(
        "База готова: users=%s size=%s path=%s",
        status["users"],
        status["size_bytes"],
        status["path"],
    )
    logger.info("Telegram-боты в main.py отключены. Админ-бот: python bot.py")

    yield

    try:
        await database.close()
    except Exception as exc:
        logger.warning("Ошибка закрытия БД: %s", exc)
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
        "message": "Apex Backend (API only, bots via bot.py)",
        "database": status,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
