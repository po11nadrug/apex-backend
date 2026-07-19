import aiosqlite
from datetime import datetime
from typing import Optional, List
from models import User, Transaction

DB_NAME = "database.db"

async def init_db():
    """Создаёт таблицы, если их ещё нет"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0,
                tariff TEXT DEFAULT 'LITE',
                bonus_balance REAL DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                registered_at TEXT,
                last_active TEXT
            )
        """)

        await db.execute("""
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
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user_id INTEGER,
                details TEXT,
                created_at TEXT
            )
        """)

        await db.commit()

async def get_user(user_id: int) -> Optional[User]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return User(
                    user_id=row["user_id"],
                    username=row["username"],
                    full_name=row["full_name"],
                    balance=row["balance"],
                    tariff=row["tariff"],
                    bonus_balance=row["bonus_balance"],
                    is_blocked=bool(row["is_blocked"]),
                    registered_at=row["registered_at"],
                    last_active=row["last_active"]
                )
            return None

async def create_user(user_id: int, username: str = None, full_name: str = None) -> User:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, registered_at, last_active)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, full_name, now, now))
        await db.commit()
    return await get_user(user_id)

async def update_balance(user_id: int, new_balance: float, admin_id: int = None, description: str = "Изменение баланса"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = ?, last_active = ? WHERE user_id = ?",
                         (new_balance, datetime.now().isoformat(), user_id))
        await db.execute("""
            INSERT INTO transactions (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, "balance_change", new_balance, description, datetime.now().isoformat(), admin_id))
        await db.commit()

async def change_tariff(user_id: int, new_tariff: str, admin_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET tariff = ?, last_active = ? WHERE user_id = ?",
                         (new_tariff, datetime.now().isoformat(), user_id))
        await db.execute("""
            INSERT INTO transactions (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, "tariff_change", 0, f"Тариф изменён на {new_tariff}", datetime.now().isoformat(), admin_id))
        await db.commit()

async def add_bonus(user_id: int, amount: float, admin_id: int = None, description: str = "Бонус"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE users 
            SET bonus_balance = bonus_balance + ?, balance = balance + ?, last_active = ?
            WHERE user_id = ?
        """, (amount, amount, datetime.now().isoformat(), user_id))
        
        await db.execute("""
            INSERT INTO transactions (user_id, type, amount, description, created_at, admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, "bonus", amount, description, datetime.now().isoformat(), admin_id))
        await db.commit()

async def get_all_users() -> List[User]:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY registered_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [
                User(
                    user_id=row["user_id"],
                    username=row["username"],
                    full_name=row["full_name"],
                    balance=row["balance"],
                    tariff=row["tariff"],
                    bonus_balance=row["bonus_balance"],
                    is_blocked=bool(row["is_blocked"]),
                    registered_at=row["registered_at"],
                    last_active=row["last_active"]
                ) for row in rows
            ]