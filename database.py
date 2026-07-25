"""
SQLite-хранилище пользователей.

На Railway файловая система контейнера эфемерна: без Volume
database.db пропадает при каждом деплое/рестарте.

Настройка:
  DATABASE_PATH=/data/database.db   # явный путь
  или примонтируйте Volume — путь возьмётся из RAILWAY_VOLUME_MOUNT_PATH
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import aiosqlite

from models import User

logger = logging.getLogger(__name__)


def resolve_db_path() -> Path:
    """Куда писать database.db (Volume / env / рядом с кодом)."""
    explicit = (os.getenv("DATABASE_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    volume = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    if volume:
        return Path(volume).expanduser().resolve() / "database.db"

    # Локальная разработка — файл рядом с backend
    return Path(__file__).resolve().parent / "database.db"


DB_PATH: Path = resolve_db_path()
DB_NAME: str = str(DB_PATH)


def _row_to_user(row: aiosqlite.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        full_name=row["full_name"],
        balance=float(row["balance"] or 0),
        tariff=row["tariff"] or "LITE",
        bonus_balance=float(row["bonus_balance"] or 0),
        is_blocked=bool(row["is_blocked"]),
        registered_at=row["registered_at"],
        last_active=row["last_active"],
    )


@asynccontextmanager
async def _open():
    """Подключение с настройками, которые реально пишут на диск."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_NAME, timeout=60.0)
    try:
        # WAL + полный sync: данные не «висят» только в памяти
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=FULL")
        await db.execute("PRAGMA busy_timeout=30000")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA temp_store=MEMORY")
        yield db
    finally:
        await db.close()


async def _commit_durable(db: aiosqlite.Connection) -> None:
    """Commit + checkpoint, чтобы изменения оказались в database.db."""
    await db.commit()
    try:
        await db.execute("PRAGMA wal_checkpoint(FULL)")
    except Exception as exc:
        logger.warning("wal_checkpoint: %s", exc)


async def init_db() -> None:
    """Создаёт таблицы и логирует путь к файлу БД."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info("SQLite path: %s (exists=%s)", DB_NAME, DB_PATH.exists())

    async with _open() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL NOT NULL DEFAULT 0,
                tariff TEXT NOT NULL DEFAULT 'LITE',
                bonus_balance REAL NOT NULL DEFAULT 0,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT,
                last_active TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                description TEXT,
                created_at TEXT,
                admin_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user_id INTEGER,
                details TEXT,
                created_at TEXT
            )
            """
        )
        await _commit_durable(db)

    count = await count_users()
    logger.info("База готова: %s пользователей, файл %s", count, DB_NAME)


async def count_users() -> int:
    async with _open() as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_user(user_id: int) -> Optional[User]:
    async with _open() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_user(row) if row else None


async def create_user(
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> User:
    """
    Создать пользователя или обновить профиль.
    После commit читает строку обратно — если нет, считаем ошибкой записи.
    """
    uid = int(user_id)
    now = datetime.now().isoformat()
    uname = (username or None)
    fname = (full_name or None)

    async with _open() as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id, username, full_name, balance, tariff,
                bonus_balance, is_blocked, registered_at, last_active
            )
            VALUES (?, ?, ?, 0, 'LITE', 0, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                full_name = COALESCE(excluded.full_name, users.full_name),
                last_active = excluded.last_active
            """,
            (uid, uname, fname, now, now),
        )
        await _commit_durable(db)

    user = await get_user(uid)
    if user is None:
        logger.error(
            "create_user FAILED: user_id=%s не найден после commit (db=%s)",
            uid,
            DB_NAME,
        )
        raise RuntimeError(f"Не удалось сохранить пользователя {uid} в {DB_NAME}")

    logger.info(
        "create_user OK user_id=%s username=%s balance=%.2f tariff=%s db=%s",
        user.user_id,
        user.username,
        user.balance,
        user.tariff,
        DB_NAME,
    )
    return user


async def update_balance(
    user_id: int,
    new_balance: float,
    admin_id: int | None = None,
    description: str = "Изменение баланса",
) -> User:
    uid = int(user_id)
    now = datetime.now().isoformat()
    bal = float(new_balance)

    async with _open() as db:
        cur = await db.execute(
            "UPDATE users SET balance = ?, last_active = ? WHERE user_id = ?",
            (bal, now, uid),
        )
        if cur.rowcount == 0:
            raise RuntimeError(f"Пользователь {uid} не найден")

        await db.execute(
            """
            INSERT INTO transactions
                (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, "balance_change", bal, description, now, admin_id),
        )
        await _commit_durable(db)

    user = await get_user(uid)
    if user is None:
        raise RuntimeError(f"update_balance: {uid} пропал после записи")
    logger.info("update_balance OK user_id=%s balance=%.2f", uid, user.balance)
    return user


async def change_tariff(
    user_id: int,
    new_tariff: str,
    admin_id: int | None = None,
) -> User:
    uid = int(user_id)
    now = datetime.now().isoformat()
    tariff = (new_tariff or "LITE").strip()

    async with _open() as db:
        cur = await db.execute(
            "UPDATE users SET tariff = ?, last_active = ? WHERE user_id = ?",
            (tariff, now, uid),
        )
        if cur.rowcount == 0:
            raise RuntimeError(f"Пользователь {uid} не найден")

        await db.execute(
            """
            INSERT INTO transactions
                (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                "tariff_change",
                0,
                f"Тариф изменён на {tariff}",
                now,
                admin_id,
            ),
        )
        await _commit_durable(db)

    user = await get_user(uid)
    if user is None:
        raise RuntimeError(f"change_tariff: {uid} пропал после записи")
    logger.info("change_tariff OK user_id=%s tariff=%s", uid, user.tariff)
    return user


async def add_bonus(
    user_id: int,
    amount: float,
    admin_id: int | None = None,
    description: str = "Бонус",
) -> User:
    uid = int(user_id)
    now = datetime.now().isoformat()
    amt = float(amount)

    async with _open() as db:
        cur = await db.execute(
            """
            UPDATE users
            SET bonus_balance = bonus_balance + ?,
                balance = balance + ?,
                last_active = ?
            WHERE user_id = ?
            """,
            (amt, amt, now, uid),
        )
        if cur.rowcount == 0:
            raise RuntimeError(f"Пользователь {uid} не найден")

        await db.execute(
            """
            INSERT INTO transactions
                (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, "bonus", amt, description, now, admin_id),
        )
        await _commit_durable(db)

    user = await get_user(uid)
    if user is None:
        raise RuntimeError(f"add_bonus: {uid} пропал после записи")
    logger.info(
        "add_bonus OK user_id=%s +%.2f balance=%.2f",
        uid,
        amt,
        user.balance,
    )
    return user


async def set_blocked(
    user_id: int,
    is_blocked: bool,
    admin_id: int | None = None,
) -> User:
    uid = int(user_id)
    now = datetime.now().isoformat()
    flag = 1 if is_blocked else 0

    async with _open() as db:
        cur = await db.execute(
            "UPDATE users SET is_blocked = ?, last_active = ? WHERE user_id = ?",
            (flag, now, uid),
        )
        if cur.rowcount == 0:
            raise RuntimeError(f"Пользователь {uid} не найден")

        await db.execute(
            """
            INSERT INTO transactions
                (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                "block" if is_blocked else "unblock",
                0,
                "Заблокирован" if is_blocked else "Разблокирован",
                now,
                admin_id,
            ),
        )
        await _commit_durable(db)

    user = await get_user(uid)
    if user is None:
        raise RuntimeError(f"set_blocked: {uid} пропал после записи")
    return user


async def get_all_users() -> List[User]:
    async with _open() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY registered_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_user(row) for row in rows]


async def db_status() -> dict:
    """Для health-check: путь, размер, число пользователей."""
    size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "path": DB_NAME,
        "exists": DB_PATH.exists(),
        "size_bytes": size,
        "users": await count_users(),
    }
