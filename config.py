"""
Конфигурация Apex Backend / Admin-bot.

Все переменные опциональны: при отсутствии — разумные дефолты.
Импорт config никогда не должен падать из-за пустого .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Telegram-токены
# ---------------------------------------------------------------------------

# Токен АДМИН-бота (панель)
ADMIN_BOT_TOKEN = _env("ADMIN_BOT_TOKEN")

# Токен бота ПРИЛОЖЕНИЯ (клиенты жмут /start)
USER_BOT_TOKEN = _env("USER_BOT_TOKEN")

# Совместимость: bot.py ждёт BOT_TOKEN
# Приоритет: BOT_TOKEN → ADMIN_BOT_TOKEN → USER_BOT_TOKEN
BOT_TOKEN = _env("BOT_TOKEN") or ADMIN_BOT_TOKEN or USER_BOT_TOKEN or ""

# ---------------------------------------------------------------------------
# Админы
# ---------------------------------------------------------------------------

_admin_ids_raw = _env("ADMIN_IDS")
ADMIN_IDS: list[int] = []
if _admin_ids_raw:
    for part in _admin_ids_raw.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.append(int(part))

# ---------------------------------------------------------------------------
# Секреты API
# ---------------------------------------------------------------------------

SECRET_KEY = _env("SECRET_KEY")

# Ключ, которым admin-bot ходит в HTTP API (часто = SECRET_KEY)
API_SECRET_KEY = _env("API_SECRET_KEY") or SECRET_KEY or ""

# Базовый URL бэкенда для api_client / remote sync
API_URL = _env("API_URL", "http://127.0.0.1:8000")

WEBAPP_URL = _env("WEBAPP_URL")

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

# Явный DATABASE_PATH → иначе Volume на Railway → иначе database.db рядом с кодом
_db_explicit = _env("DATABASE_PATH")
_volume = _env("RAILWAY_VOLUME_MOUNT_PATH")

if _db_explicit:
    DATABASE_PATH = _db_explicit
elif _volume:
    DATABASE_PATH = str(Path(_volume).expanduser() / "database.db")
else:
    # Локально — database.db; на многих хостингах volume = /data
    _data_default = Path("/data/database.db")
    if _data_default.parent.is_dir():
        DATABASE_PATH = str(_data_default)
    else:
        DATABASE_PATH = str(Path(__file__).resolve().parent / "database.db")

# ---------------------------------------------------------------------------
# Прочее
# ---------------------------------------------------------------------------

# Засеять демо-пользователей при пустой БД (admin-bot startup)
SEED_DEMO_USERS = _env_bool("SEED_DEMO_USERS", default=False)
