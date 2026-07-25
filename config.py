"""
Конфигурация Apex Backend + Admin-bot.

Все переменные опциональны: при отсутствии — разумные дефолты.
Импорт config никогда не падает (нет raise ValueError).
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


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_database_path() -> str:
    """
    DATABASE_PATH env → Railway volume → /data/database.db (Linux/Railway)
    → database.db рядом с config.py (локальная Windows/dev).
    """
    explicit = _env("DATABASE_PATH")
    if explicit:
        return explicit

    volume = _env("RAILWAY_VOLUME_MOUNT_PATH")
    if volume:
        return str(Path(volume).expanduser() / "database.db")

    # Railway / Linux volume: /data существует как mount
    # На Windows Path('/data') → C:\\data — не используем как дефолт.
    if os.name != "nt":
        data_dir = Path("/data")
        try:
            if data_dir.is_dir():
                return str(data_dir / "database.db")
        except OSError:
            pass

    return str(Path(__file__).resolve().parent / "database.db")


# ---------------------------------------------------------------------------
# Telegram-токены
# ---------------------------------------------------------------------------

ADMIN_BOT_TOKEN: str = _env("ADMIN_BOT_TOKEN")
USER_BOT_TOKEN: str = _env("USER_BOT_TOKEN")

# Приоритет: BOT_TOKEN → ADMIN_BOT_TOKEN → USER_BOT_TOKEN
BOT_TOKEN: str = _env("BOT_TOKEN") or ADMIN_BOT_TOKEN or USER_BOT_TOKEN or ""

# ---------------------------------------------------------------------------
# Админы
# ---------------------------------------------------------------------------

ADMIN_IDS: list[int] = []
_admin_ids_raw = _env("ADMIN_IDS")
if _admin_ids_raw:
    for part in _admin_ids_raw.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.append(int(part))

# ---------------------------------------------------------------------------
# Секреты / API
# ---------------------------------------------------------------------------

SECRET_KEY: str = _env("SECRET_KEY")
API_SECRET_KEY: str = _env("API_SECRET_KEY") or SECRET_KEY or ""
API_URL: str = _env("API_URL", "http://127.0.0.1:8000")
WEBAPP_URL: str = _env("WEBAPP_URL")

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------

DATABASE_PATH: str = _resolve_database_path()

# Засеять демо-пользователей при пустой БД (admin-bot startup)
SEED_DEMO_USERS: bool = _env_bool("SEED_DEMO_USERS", default=False)

# ---------------------------------------------------------------------------
# Тарифы и пагинация (admin-bot UI)
# ---------------------------------------------------------------------------

TARIFFS: tuple[str, ...] = ("LITE", "POWER", "POWER+")

USERS_PER_PAGE: int = _env_int("USERS_PER_PAGE", 10)
TRANSFERS_PER_PAGE: int = _env_int("TRANSFERS_PER_PAGE", 10)
HISTORY_PER_PAGE: int = _env_int("HISTORY_PER_PAGE", 10)
