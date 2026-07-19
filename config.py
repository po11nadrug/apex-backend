import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")

# Безопасная обработка ADMIN_IDS
admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []

if admin_ids_raw.strip():
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()]

# Проверки
if not ADMIN_BOT_TOKEN:
    raise ValueError("Не указан ADMIN_BOT_TOKEN в файле .env")

if not ADMIN_IDS:
    raise ValueError("Не указан ADMIN_IDS в файле .env или указан неправильно")

if not SECRET_KEY:
    raise ValueError("Не указан SECRET_KEY в файле .env")