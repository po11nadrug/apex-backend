"""
Асинхронный слой работы с SQLite для Админ-бота Apex.

Таблицы:
  - users         — пользователи крипто-приложения
  - transactions  — история всех финансовых операций
  - admin_logs    — лог действий администраторов
"""

from __future__ import annotations

import aiosqlite
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import DATABASE_PATH, TARIFFS
from models import User


def _now_iso() -> str:
    """Текущее время в ISO-формате (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_money(amount: float | int | None) -> str:
    """Форматирование суммы в рублях: 1 234.56 ₽"""
    if amount is None:
        amount = 0.0
    return f"{float(amount):,.2f} ₽".replace(",", " ")


def format_dt(value: str | None) -> str:
    """Человекочитаемая дата из ISO-строки."""
    if not value:
        return "—"
    try:
        # Поддержка нескольких форматов
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value[:19], fmt)
                return dt.strftime("%d.%m.%Y %H:%M")
            except ValueError:
                continue
        return value
    except Exception:
        return value


class Database:
    """Обёртка над aiosqlite с удобными методами."""

    def __init__(self, path: str = DATABASE_PATH) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    # ── lifecycle ──────────────────────────────────────────────

    async def connect(self) -> None:
        # Родительская папка для Volume/Railway (например /data/database.db)
        parent = Path(self.path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self.path, timeout=30.0)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA busy_timeout = 15000")
        await self.init_tables()
        await self._ensure_compatible_schema()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call await db.connect()")
        return self._conn

    # ── schema ─────────────────────────────────────────────────

    async def init_tables(self) -> None:
        """Создание таблиц, если их ещё нет."""
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                full_name     TEXT,
                balance       REAL    NOT NULL DEFAULT 0,
                tariff        TEXT    NOT NULL DEFAULT 'LITE',
                bonus_balance REAL    NOT NULL DEFAULT 0,
                is_blocked    INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT    NOT NULL,
                last_active   TEXT,
                requisites    TEXT    NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER,
                type          TEXT    NOT NULL,
                amount        REAL    NOT NULL,
                balance_after REAL,
                comment       TEXT,
                related_user  INTEGER,
                admin_id      INTEGER,
                created_at    TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                type          TEXT    NOT NULL, -- e.g. 'withdrawal_request', 'investment_request'
                status        TEXT    NOT NULL DEFAULT 'pending',
                amount        REAL,
                details       TEXT,   -- JSON or description
                created_at    TEXT    NOT NULL,
                processed_at  TEXT,
                processed_by  INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS admin_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id   INTEGER NOT NULL,
                action     TEXT    NOT NULL,
                target_id  INTEGER,
                details    TEXT,
                created_at TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_username
                ON users(username);
            CREATE INDEX IF NOT EXISTS idx_tx_user
                ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_tx_type
                ON transactions(type);
            CREATE INDEX IF NOT EXISTS idx_tx_created
                ON transactions(created_at);
            CREATE INDEX IF NOT EXISTS idx_admin_logs_created
                ON admin_logs(created_at);

            CREATE TABLE IF NOT EXISTS requisites (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                key          TEXT NOT NULL,           -- e.g. 'deposit_card'
                value        TEXT NOT NULL,           -- JSON or formatted string
                updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_requisites_key
                ON requisites(key);
            """
        )
        await self.conn.commit()

    async def _table_columns(self, table: str) -> set[str]:
        async with self.conn.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
            return {str(r["name"]) for r in rows}

    async def _ensure_compatible_schema(self) -> None:
        """
        Бэкенд и админ-бот делят одну SQLite.
        Бэкенд: transactions.description, admin_logs.target_user_id
        Админ:  transactions.comment / balance_after, admin_logs.target_id
        Добавляем недостающие колонки, чтобы оба писали без ошибок.
        """
        try:
            tx_cols = await self._table_columns("transactions")
            for col, decl in (
                ("comment", "TEXT"),
                ("description", "TEXT"),
                ("balance_after", "REAL"),
                ("related_user", "INTEGER"),
                ("admin_id", "INTEGER"),
                ("created_at", "TEXT"),
            ):
                if col not in tx_cols:
                    await self.conn.execute(
                        f"ALTER TABLE transactions ADD COLUMN {col} {decl}"
                    )

            # Users table — add requisites if missing
            users_cols = await self._table_columns("users")
            for col, decl in (
                ("requisites", "TEXT NOT NULL DEFAULT '{}'"),
                ("bot_id", "INTEGER"),
                ("source", "TEXT"),
                ("from_bot", "INTEGER"),
            ):
                if col not in users_cols:
                    await self.conn.execute(
                        f"ALTER TABLE users ADD COLUMN {col} {decl}"
                    )

            log_cols = await self._table_columns("admin_logs")
            for col, decl in (
                ("target_id", "INTEGER"),
                ("target_user_id", "INTEGER"),
                ("details", "TEXT"),
                ("created_at", "TEXT"),
            ):
                if col not in log_cols:
                    await self.conn.execute(
                        f"ALTER TABLE admin_logs ADD COLUMN {col} {decl}"
                    )
            await self.conn.commit()
        except Exception:
            # Не валим старт бота из‑за миграции
            pass

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        # унификация полей истории
        if d.get("comment") is None and d.get("description") is not None:
            d["comment"] = d["description"]
        if d.get("description") is None and d.get("comment") is not None:
            d["description"] = d["comment"]
        return d

    @staticmethod
    def _rows_to_list(rows: list[aiosqlite.Row]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            d = dict(r)
            if d.get("comment") is None and d.get("description") is not None:
                d["comment"] = d["description"]
            out.append(d)
        return out

    # ── users: read ────────────────────────────────────────────

    async def get_users_count(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) AS c FROM users") as cur:
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

    async def get_users_page(self, page: int = 0, per_page: int = 10) -> list[dict]:
        """Страница списка пользователей (новые сверху)."""
        offset = page * per_page
        async with self.conn.execute(
            """
            SELECT user_id, username, full_name, balance, tariff,
                   bonus_balance, is_blocked, registered_at, last_active,
                   bot_id, source, from_bot
            FROM users
            ORDER BY COALESCE(last_active, registered_at) DESC, user_id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ) as cur:
            rows = await cur.fetchall()
            return self._rows_to_list(rows)

    async def get_user(self, user_id: int) -> dict | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ) as cur:
            return self._row_to_dict(await cur.fetchone())

    async def find_user_by_username(self, username: str) -> dict | None:
        username = username.lstrip("@").strip().lower()
        async with self.conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = ?",
            (username,),
        ) as cur:
            return self._row_to_dict(await cur.fetchone())

    async def search_users(self, query: str) -> list[dict]:
        """
        Поиск: если query — число, ищем по user_id;
        иначе — по username (частичное совпадение, без @).
        """
        query = query.strip()
        if not query:
            return []

        if query.lstrip("-").isdigit():
            user = await self.get_user(int(query))
            return [user] if user else []

        username = query.lstrip("@").lower()
        async with self.conn.execute(
            """
            SELECT * FROM users
            WHERE LOWER(username) LIKE ?
               OR LOWER(full_name) LIKE ?
            ORDER BY registered_at DESC
            LIMIT 20
            """,
            (f"%{username}%", f"%{username}%"),
        ) as cur:
            return self._rows_to_list(await cur.fetchall())

    # ── users: write ───────────────────────────────────────────

    async def ensure_user(
        self,
        user_id: int,
        username: str | None = None,
        full_name: str | None = None,
    ) -> dict:
        """
        Создать пользователя при первом запуске бота / обновить профиль.

        Вызывается при /start и любом сообщении — чтобы в списке
        «Пользователи» были реальные люди, а не только демо-записи.
        """
        existing = await self.get_user(user_id)
        now = _now_iso()

        if existing:
            # Обновляем username/имя и last_active, если пришли свежие данные
            new_username = username if username is not None else existing.get("username")
            new_full_name = full_name if full_name is not None else existing.get("full_name")
            await self.conn.execute(
                """
                UPDATE users
                SET username = ?, full_name = ?, last_active = ?
                WHERE user_id = ?
                """,
                (new_username, new_full_name, now, user_id),
            )
            await self.conn.commit()
            user = await self.get_user(user_id)
            assert user is not None
            return user

        await self.conn.execute(
            """
            INSERT INTO users (
                user_id, username, full_name, balance, tariff,
                bonus_balance, is_blocked, registered_at, last_active
            ) VALUES (?, ?, ?, 0, 'LITE', 0, 0, ?, ?)
            """,
            (user_id, username, full_name, now, now),
        )
        await self.conn.commit()
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def set_balance(
        self,
        user_id: int,
        new_balance: float,
        *,
        tx_type: str,
        comment: str | None,
        admin_id: int | None,
        related_user: int | None = None,
    ) -> dict | None:
        """Установить абсолютное значение баланса + запись в transactions."""
        user = await self.get_user(user_id)
        if not user:
            return None

        new_balance = round(float(new_balance), 2)
        await self.conn.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id),
        )
        await self._add_transaction(
            user_id=user_id,
            tx_type=tx_type,
            amount=new_balance - float(user["balance"]),
            balance_after=new_balance,
            comment=comment,
            admin_id=admin_id,
            related_user=related_user,
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def change_balance(
        self,
        user_id: int,
        delta: float,
        *,
        tx_type: str,
        comment: str | None,
        admin_id: int | None,
        related_user: int | None = None,
    ) -> dict | None:
        """Изменить баланс на delta (может быть отрицательным)."""
        user = await self.get_user(user_id)
        if not user:
            return None
        new_balance = round(float(user["balance"]) + float(delta), 2)
        return await self.set_balance(
            user_id,
            new_balance,
            tx_type=tx_type,
            comment=comment,
            admin_id=admin_id,
            related_user=related_user,
        )

    async def set_tariff(
        self,
        user_id: int,
        tariff: str,
        *,
        admin_id: int | None = None,
    ) -> dict | None:
        if tariff not in TARIFFS:
            raise ValueError(f"Unknown tariff: {tariff}")
        user = await self.get_user(user_id)
        if not user:
            return None

        old = user["tariff"]
        await self.conn.execute(
            "UPDATE users SET tariff = ? WHERE user_id = ?",
            (tariff, user_id),
        )
        await self._add_transaction(
            user_id=user_id,
            tx_type="tariff_change",
            amount=0,
            balance_after=float(user["balance"]),
            comment=f"{old} → {tariff}",
            admin_id=admin_id,
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def add_bonus(
        self,
        user_id: int,
        amount: float,
        *,
        comment: str | None,
        admin_id: int | None,
    ) -> dict | None:
        user = await self.get_user(user_id)
        if not user:
            return None

        amount = round(float(amount), 2)
        new_bonus = round(float(user["bonus_balance"]) + amount, 2)
        await self.conn.execute(
            "UPDATE users SET bonus_balance = ? WHERE user_id = ?",
            (new_bonus, user_id),
        )
        await self._add_transaction(
            user_id=user_id,
            tx_type="bonus",
            amount=amount,
            balance_after=float(user["balance"]),
            comment=comment or f"Бонус +{amount}",
            admin_id=admin_id,
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def set_blocked(self, user_id: int, blocked: bool) -> dict | None:
        user = await self.get_user(user_id)
        if not user:
            return None
        await self.conn.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (1 if blocked else 0, user_id),
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    # ── transactions ───────────────────────────────────────────

    async def _add_transaction(
        self,
        *,
        user_id: int | None,
        tx_type: str,
        amount: float,
        balance_after: float | None,
        comment: str | None,
        admin_id: int | None = None,
        related_user: int | None = None,
    ) -> int:
        cols = await self._table_columns("transactions")
        amt = round(float(amount), 2)
        now = _now_iso()
        note = comment

        # Совместимость с схемой бэкенда (description) и админа (comment)
        fields: list[str] = ["user_id", "type", "amount"]
        values: list[Any] = [user_id, tx_type, amt]

        if "description" in cols:
            fields.append("description")
            values.append(note)
        if "comment" in cols:
            fields.append("comment")
            values.append(note)
        if "balance_after" in cols:
            fields.append("balance_after")
            values.append(balance_after)
        if "related_user" in cols:
            fields.append("related_user")
            values.append(related_user)
        if "admin_id" in cols:
            fields.append("admin_id")
            values.append(admin_id)
        if "created_at" in cols:
            fields.append("created_at")
            values.append(now)

        placeholders = ", ".join("?" for _ in fields)
        sql = f"INSERT INTO transactions ({', '.join(fields)}) VALUES ({placeholders})"
        cur = await self.conn.execute(sql, tuple(values))
        return int(cur.lastrowid)

    async def get_user_transactions(
        self,
        user_id: int,
        page: int = 0,
        per_page: int = 10,
    ) -> list[dict]:
        offset = page * per_page
        async with self.conn.execute(
            """
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, offset),
        ) as cur:
            return self._rows_to_list(await cur.fetchall())

    async def get_user_transactions_count(self, user_id: int) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM transactions WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

    async def get_all_transactions(
        self,
        page: int = 0,
        per_page: int = 10,
    ) -> list[dict]:
        """Общая история операций (все пользователи)."""
        offset = page * per_page
        async with self.conn.execute(
            """
            SELECT * FROM transactions
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ) as cur:
            return self._rows_to_list(await cur.fetchall())

    async def get_all_transactions_count(self) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM transactions"
        ) as cur:
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

    # ── transfers ──────────────────────────────────────────────

    async def create_transfer(
        self,
        from_id: int,
        to_id: int,
        amount: float,
        *,
        comment: str | None,
        admin_id: int | None,
    ) -> tuple[bool, str]:
        """
        Списать amount у from_id и зачислить to_id.
        Возвращает (ok, message).
        """
        amount = round(float(amount), 2)
        if amount <= 0:
            return False, "Сумма должна быть больше нуля."

        sender = await self.get_user(from_id)
        receiver = await self.get_user(to_id)
        if not sender:
            return False, f"Отправитель {from_id} не найден."
        if not receiver:
            return False, f"Получатель {to_id} не найден."
        if from_id == to_id:
            return False, "Нельзя перевести самому себе."

        if float(sender["balance"]) < amount:
            return (
                False,
                f"Недостаточно средств у отправителя "
                f"(баланс {format_money(sender['balance'])}).",
            )

        note = comment or "Ручной перевод (админ)"
        # Списание
        await self.change_balance(
            from_id,
            -amount,
            tx_type="transfer_out",
            comment=f"{note} → {to_id}",
            admin_id=admin_id,
            related_user=to_id,
        )
        # Зачисление
        await self.change_balance(
            to_id,
            amount,
            tx_type="transfer_in",
            comment=f"{note} ← {from_id}",
            admin_id=admin_id,
            related_user=from_id,
        )
        return True, (
            f"Перевод {format_money(amount)} выполнен:\n"
            f"  {from_id} → {to_id}"
        )

    async def get_transfers(
        self,
        page: int = 0,
        per_page: int = 10,
    ) -> list[dict]:
        """Список переводов (исходящие transfer_out)."""
        offset = page * per_page
        async with self.conn.execute(
            """
            SELECT * FROM transactions
            WHERE type = 'transfer_out'
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ) as cur:
            return self._rows_to_list(await cur.fetchall())

    async def get_transfers_count(self) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM transactions WHERE type = 'transfer_out'"
        ) as cur:
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

    async def get_all_applications_count(self, status: str | None = None) -> int:
        """Количество всех заявок, с опциональным фильтром по статусу."""
        sql = "SELECT COUNT(*) AS c FROM applications"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

    # ── applications / requests ─────────────────────────────────────

    async def create_application(
        self, user_id: int, app_type: str, amount: float = 0.0, details: str = ""
    ) -> dict | None:
        """Создать новую заявку/приложение."""
        now = _now_iso()
        await self.conn.execute(
            """
            INSERT INTO applications (user_id, type, amount, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, app_type, amount, details, now),
        )
        await self.conn.commit()
        app_id = (await self.conn.execute("SELECT last_insert_rowid()")).fetchone()[0]
        return await self.get_application(app_id)

    async def get_application(self, app_id: int) -> dict | None:
        async with self.conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ) as cur:
            row = await cur.fetchone()
            return self._row_to_dict(row)

    async def get_user_applications(
        self,
        user_id: int,
        status: str | None = None,
        page: int = 0,
        per_page: int = 10,
    ) -> list[dict]:
        offset = page * per_page
        sql = "SELECT * FROM applications WHERE user_id = ?"
        params = [user_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        async with self.conn.execute(sql, params) as cur:
            return self._rows_to_list(await cur.fetchall())

    async def get_all_applications(
        self, status: str | None = None, page: int = 0, per_page: int = 10
    ) -> list[dict]:
        offset = page * per_page
        sql = "SELECT * FROM applications"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        async with self.conn.execute(sql, params) as cur:
            return self._rows_to_list(await cur.fetchall())

    async def update_application_status(
        self, app_id: int, status: str, processed_by: int | None = None
    ) -> bool:
        now = _now_iso()
        await self.conn.execute(
            """
            UPDATE applications
            SET status = ?, processed_at = ?, processed_by = ?
            WHERE id = ?
            """,
            (status, now, processed_by, app_id),
        )
        await self.conn.commit()
        return True

    async def set_user_requisites(
        self, user_id: int, requisites: dict
    ) -> dict | None:
        """Обновить реквизиты пользователя."""
        user = await self.get_user(user_id)
        if not user:
            return None
        req_str = json.dumps(requisites)  # requires import json at top
        await self.conn.execute(
            "UPDATE users SET requisites = ? WHERE user_id = ?",
            (req_str, user_id),
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def get_requisites(self, key: str = "deposit_card") -> dict | None:
        """Получить реквизиты по ключу (например, для пополнения)."""
        async with self.conn.execute(
            "SELECT value FROM requisites WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return json.loads(row["value"])

    async def set_requisites(self, key: str = "deposit_card", value: dict = None) -> bool:
        """Сохранить новые реквизиты."""
        if value is None:
            value = {}
        req_str = json.dumps(value)
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO requisites (key, value, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            """,
            (key, req_str),
        )
        await self.conn.commit()
        return True

    # ── statistics ─────────────────────────────────────────────

    async def get_statistics(self) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "total_users": 0,
            "total_balance": 0.0,
            "total_bonus": 0.0,
            "blocked_users": 0,
            "by_tariff": {t: 0 for t in TARIFFS},
            "bonus_sum_accrued": 0.0,
        }

        async with self.conn.execute(
            """
            SELECT
                COUNT(*) AS total_users,
                COALESCE(SUM(balance), 0) AS total_balance,
                COALESCE(SUM(bonus_balance), 0) AS total_bonus,
                COALESCE(SUM(CASE WHEN is_blocked = 1 THEN 1 ELSE 0 END), 0)
                    AS blocked_users
            FROM users
            """
        ) as cur:
            row = await cur.fetchone()
            if row:
                stats["total_users"] = int(row["total_users"])
                stats["total_balance"] = float(row["total_balance"])
                stats["total_bonus"] = float(row["total_bonus"])
                stats["blocked_users"] = int(row["blocked_users"])

        async with self.conn.execute(
            """
            SELECT tariff, COUNT(*) AS c
            FROM users
            GROUP BY tariff
            """
        ) as cur:
            for r in await cur.fetchall():
                tariff = r["tariff"]
                if tariff in stats["by_tariff"]:
                    stats["by_tariff"][tariff] = int(r["c"])
                else:
                    stats["by_tariff"][tariff] = int(r["c"])

        # Сумма всех начисленных бонусов (только положительные bonus)
        async with self.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS s
            FROM transactions
            WHERE type = 'bonus' AND amount > 0
            """
        ) as cur:
            row = await cur.fetchone()
            if row:
                stats["bonus_sum_accrued"] = float(row["s"])

        return stats

    # ── admin logs ─────────────────────────────────────────────

    async def log_admin(
        self,
        admin_id: int,
        action: str,
        target_id: int | None = None,
        details: str | None = None,
    ) -> None:
        cols = await self._table_columns("admin_logs")
        fields = ["admin_id", "action"]
        values: list[Any] = [admin_id, action]
        if "target_id" in cols:
            fields.append("target_id")
            values.append(target_id)
        if "target_user_id" in cols:
            fields.append("target_user_id")
            values.append(target_id)
        if "details" in cols:
            fields.append("details")
            values.append(details)
        if "created_at" in cols:
            fields.append("created_at")
            values.append(_now_iso())
        ph = ", ".join("?" for _ in fields)
        await self.conn.execute(
            f"INSERT INTO admin_logs ({', '.join(fields)}) VALUES ({ph})",
            tuple(values),
        )
        await self.conn.commit()

    async def get_admin_logs(self, limit: int = 50) -> list[dict]:
        async with self.conn.execute(
            """
            SELECT * FROM admin_logs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = self._rows_to_list(await cur.fetchall())
            for r in rows:
                if r.get("target_id") is None and r.get("target_user_id") is not None:
                    r["target_id"] = r["target_user_id"]
            return rows

    # ── demo seed (опционально) ────────────────────────────────

    async def seed_demo_users(self) -> int:
        """
        Добавить несколько демо-пользователей, если база пуста.
        Возвращает количество созданных записей.
        """
        count = await self.get_users_count()
        if count > 0:
            return 0

        demo = [
            (100001, "ivan_crypto", "Иван Петров", 15000.50, "POWER", 500.0),
            (100002, "maria_apex", "Мария Сидорова", 3200.00, "LITE", 100.0),
            (100003, "alex_power", "Алексей Козлов", 87500.00, "POWER+", 2500.0),
            (100004, "olga_trade", "Ольга Новикова", 0.00, "LITE", 0.0),
            (100005, "dmitry_pro", "Дмитрий Волков", 42100.75, "POWER", 800.0),
            (100006, "anna_lite", "Анна Морозова", 980.00, "LITE", 50.0),
            (100007, "sergey_plus", "Сергей Орлов", 120000.00, "POWER+", 5000.0),
            (100008, "elena_fx", "Елена Соколова", 5400.25, "POWER", 200.0),
            (100009, "pavel_user", "Павел Лебедев", 150.00, "LITE", 0.0),
            (100010, "natalia_k", "Наталья Кузнецова", 21000.00, "POWER", 1000.0),
            (100011, "igor_trade", "Игорь Смирнов", 6700.00, "LITE", 150.0),
            (100012, "kate_apex", "Екатерина Попова", 99000.00, "POWER+", 3000.0),
        ]
        now = _now_iso()
        for uid, uname, fname, bal, tariff, bonus in demo:
            await self.conn.execute(
                """
                INSERT INTO users (
                    user_id, username, full_name, balance, tariff,
                    bonus_balance, is_blocked, registered_at, last_active
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (uid, uname, fname, bal, tariff, bonus, now, now),
            )
        await self.conn.commit()
        return len(demo)


# Глобальный экземпляр (инициализируется в bot.py / main.py через init_db)
db = Database()

# ---------------------------------------------------------------------------
# Совместимость с main.py, api/routes.py, bot/user_bot.py, bot/handlers.py
# (старый функциональный API поверх class-based Database)
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(DATABASE_PATH)
DB_NAME: str = str(DB_PATH)


def _to_user(data: dict | None) -> User | None:
    """dict из SQLite → dataclass User (для API и встроенных ботов)."""
    if not data:
        return None
    return User(
        user_id=int(data["user_id"]),
        username=data.get("username"),
        full_name=data.get("full_name"),
        balance=float(data.get("balance") or 0),
        tariff=data.get("tariff") or "LITE",
        bonus_balance=float(data.get("bonus_balance") or 0),
        is_blocked=bool(data.get("is_blocked")),
        registered_at=data.get("registered_at"),
        last_active=data.get("last_active"),
    )


async def _ensure_connected() -> None:
    """Подключить глобальный db, если ещё не подключён (FastAPI / bot)."""
    if db._conn is None:
        await db.connect()


async def init_db() -> None:
    """Инициализация БД при старте main.py (lifespan)."""
    await _ensure_connected()


async def db_status() -> dict:
    """Health-check для / и /api/health/db."""
    await _ensure_connected()
    path = Path(db.path)
    size = path.stat().st_size if path.exists() else 0
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": size,
        "users": await db.get_users_count(),
    }


async def get_user(user_id: int) -> User | None:
    await _ensure_connected()
    return _to_user(await db.get_user(int(user_id)))


async def create_user(
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> User:
    """Создать или обновить пользователя (ensure_user)."""
    await _ensure_connected()
    row = await db.ensure_user(int(user_id), username=username, full_name=full_name)
    user = _to_user(row)
    assert user is not None
    return user


async def update_balance(
    user_id: int,
    amount: float,
    description: str = "Изменение баланса",
    admin_id: int | None = None,
) -> User | None:
    """Установить абсолютный баланс (старое имя update_balance)."""
    await _ensure_connected()
    row = await db.set_balance(
        int(user_id),
        float(amount),
        tx_type="admin_set",
        comment=description,
        admin_id=admin_id,
    )
    return _to_user(row)


async def change_tariff(
    user_id: int,
    tariff: str,
    admin_id: int | None = None,
) -> User | None:
    await _ensure_connected()
    row = await db.set_tariff(int(user_id), tariff, admin_id=admin_id)
    return _to_user(row)


async def add_bonus(
    user_id: int,
    amount: float,
    description: str = "Бонус от администратора",
    admin_id: int | None = None,
) -> User | None:
    await _ensure_connected()
    row = await db.add_bonus(
        int(user_id),
        float(amount),
        comment=description,
        admin_id=admin_id,
    )
    return _to_user(row)


async def set_blocked(
    user_id: int,
    is_blocked: bool,
    admin_id: int | None = None,
) -> User | None:
    await _ensure_connected()
    row = await db.set_blocked(int(user_id), bool(is_blocked))
    return _to_user(row)


async def get_all_users() -> list[User]:
    """Все пользователи (для /api/users и встроенной админ-панели)."""
    await _ensure_connected()
    result: list[User] = []
    page = 0
    per_page = 200
    while True:
        batch = await db.get_users_page(page=page, per_page=per_page)
        if not batch:
            break
        for row in batch:
            user = _to_user(row)
            if user:
                result.append(user)
        if len(batch) < per_page:
            break
        page += 1
    return result


async def count_users() -> int:
    await _ensure_connected()
    return await db.get_users_count()
