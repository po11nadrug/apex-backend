import os
from dotenv import load_dotenv

load_dotenv()

# Токен АДМИН-бота (панель). Может совпадать со старым токеном.
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()

# Токен бота ПРИЛОЖЕНИЯ (клиенты жмут /start здесь)
USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN", "").strip()

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

# Хотя бы один бот должен быть настроен для Telegram
if not ADMIN_BOT_TOKEN and not USER_BOT_TOKEN:
    raise ValueError(
        "Укажите USER_BOT_TOKEN (бот приложения) и/или ADMIN_BOT_TOKEN в .env"
    )
