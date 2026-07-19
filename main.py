import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import ADMIN_BOT_TOKEN
from database import init_db
from api.routes import router as api_router
from bot.handlers import router as admin_router

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== БОТ ==================
bot = Bot(
    token=ADMIN_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ================== ЗАПУСК ==================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных готова")

    # Подключаем обработчики админ-бота
    dp.include_router(admin_router)

    # Запускаем бота
    asyncio.create_task(dp.start_polling(bot))
    logger.info("Админ-бот запущен")

    yield

    await bot.session.close()
    logger.info("Бот остановлен")

# ================== FASTAPI ==================
app = FastAPI(title="Apex Backend", lifespan=lifespan)
app.include_router(api_router, prefix="/api")

@app.get("/")
async def root():
    return {"status": "ok", "message": "Apex Backend работает"}

# ================== СТАРТ ==================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)