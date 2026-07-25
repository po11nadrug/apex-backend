import os
from dotenv import load_dotenv

load_dotenv()

# Токен АДМИН-бота (панель). Может совпадать со старым токеном.
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()

# Токен бота ПРИЛОЖЕНИЯ (клиенты жмут /start здесь)
USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN", "").strip()

# Совместимость: bot.py и старые скрипты ждут BOT_TOKEN
# Приоритет: BOT_TOKEN → ADMIN_BOT_TOKEN → USER_BOT_TOKEN
BOT_TOKEN = (
    os.getenv("BOT_TOKEN", "").strip()
    or ADMIN_BOT_TOKEN
    or USER_BOT_TOKEN
    or ""
)

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = []
if admin_ids_raw.strip():
    ADMIN_IDS = [
        int(x.strip())
        for x in admin_ids_raw.split(",")
        if x.strip().isdigit()
    ]

if not SECRET_KEY:
    raise ValueError("Не указан SECRET_KEY в файле .env")

if not ADMIN_IDS:
    raise ValueError("Не указан ADMIN_IDS в файле .env")

# Токены опциональны: пустая строка вместо raise — API/сервис не падает на импорте.
# bot.py сам проверит BOT_TOKEN при старте polling.
