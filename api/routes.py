from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
import logging
import secrets

import database as db
from config import SECRET_KEY

logger = logging.getLogger(__name__)

# ================== МОДЕЛИ ЗАПРОСОВ ==================

class BalanceUpdate(BaseModel):
    amount: float
    mode: str = "set"          # "set" — установить, "add" — добавить
    description: str = "Изменение баланса"

class TariffUpdate(BaseModel):
    tariff: str                # LITE / POWER / POWER+

class BonusAdd(BaseModel):
    amount: float
    description: str = "Бонус от администратора"

class RegisterUser(BaseModel):
    user_id: int
    username: Optional[str] = None
    full_name: Optional[str] = None

class BlockUpdate(BaseModel):
    is_blocked: bool

# ================== ПРОВЕРКА СЕКРЕТНОГО КЛЮЧА ==================

def _mask_key(value: str) -> str:
    """Первые 4 символа ключа для логов (или пометка, что пусто)."""
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return value
    return f"{value[:4]}…"


def _extract_secret(request: Request) -> str:
    """
    Достаём секрет из любого поддерживаемого места.
    HTTP-заголовки case-insensitive, но явно читаем оба варианта имён
    и query-параметры key / secret.
    """
    headers = request.headers
    # Starlette Headers — case-insensitive; дублируем имена для ясности
    from_header = (
        headers.get("x-secret-key")
        or headers.get("X-Secret-Key")
        or ""
    )

    qp = request.query_params
    from_query = qp.get("key") or qp.get("secret") or ""

    # Приоритет: заголовок, затем query
    raw = from_header if str(from_header).strip() else from_query
    return str(raw or "").strip()


async def verify_secret(request: Request) -> bool:
    """
    Проверка SECRET_KEY для всех API-эндпоинтов.

    Источники ключа (после .strip()):
      1. заголовок x-secret-key / X-Secret-Key
      2. query ?key=
      3. query ?secret=
    """
    provided = _extract_secret(request)
    expected = (SECRET_KEY or "").strip()

    logger.info(
        "Auth %s %s | provided=%s expected=%s | has_header=%s query_keys=%s",
        request.method,
        request.url.path,
        _mask_key(provided),
        _mask_key(expected),
        bool(
            (request.headers.get("x-secret-key") or request.headers.get("X-Secret-Key") or "").strip()
        ),
        list(request.query_params.keys()),
    )

    if not provided:
        raise HTTPException(
            status_code=403,
            detail=(
                "Секретный ключ не передан. "
                "Укажите заголовок x-secret-key / X-Secret-Key "
                "или query-параметр ?key= / ?secret="
            ),
        )

    # compare_digest — устойчивое сравнение; при разной длине — обычное !=
    keys_match = (
        secrets.compare_digest(provided, expected)
        if len(provided) == len(expected)
        else provided == expected
    )

    if not keys_match:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Неверный секретный ключ "
                f"(пришло {_mask_key(provided)}, ожидается {_mask_key(expected)})"
            ),
        )

    return True


# Зависимость на уровне роутера — действует на ВСЕ эндпоинты /api/*
router = APIRouter(dependencies=[Depends(verify_secret)])

# ================== ЭНДПОИНТЫ ==================

@router.get("/user/{user_id}")
async def get_user_info(user_id: int):
    """Получить информацию о пользователе"""
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return {
        "user_id": user.user_id,
        "username": user.username,
        "full_name": user.full_name,
        "balance": user.balance,
        "tariff": user.tariff,
        "bonus_balance": user.bonus_balance,
        "is_blocked": user.is_blocked
    }

@router.post("/user/register")
async def register_user(data: RegisterUser):
    """Регистрация пользователя (вызывается при первом входе в Mini App)"""
    user = await db.create_user(
        user_id=data.user_id,
        username=data.username,
        full_name=data.full_name
    )
    return {
        "status": "ok",
        "user_id": user.user_id,
        "balance": user.balance,
        "tariff": user.tariff
    }

@router.post("/user/{user_id}/balance")
async def update_user_balance(user_id: int, data: BalanceUpdate):
    """Изменить баланс пользователя"""
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if data.mode == "add":
        new_balance = user.balance + data.amount
    else:
        new_balance = data.amount

    await db.update_balance(user_id, new_balance, description=data.description)
    
    return {
        "status": "ok",
        "new_balance": new_balance
    }

@router.post("/user/{user_id}/tariff")
async def update_user_tariff(user_id: int, data: TariffUpdate):
    """Изменить тариф пользователя"""
    if data.tariff not in ["LITE", "POWER", "POWER+"]:
        raise HTTPException(status_code=400, detail="Недопустимый тариф")

    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.change_tariff(user_id, data.tariff)
    
    return {
        "status": "ok",
        "new_tariff": data.tariff
    }

@router.post("/user/{user_id}/bonus")
async def add_user_bonus(user_id: int, data: BonusAdd):
    """Начислить бонус"""
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.add_bonus(user_id, data.amount, description=data.description)
    
    updated_user = await db.get_user(user_id)
    return {
        "status": "ok",
        "new_balance": updated_user.balance,
        "new_bonus_balance": updated_user.bonus_balance
    }

@router.post("/user/{user_id}/block")
async def update_user_block(user_id: int, data: BlockUpdate):
    """Заблокировать / разблокировать пользователя (админ-бот)"""
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.set_blocked(user_id, data.is_blocked)
    updated = await db.get_user(user_id)
    return {
        "status": "ok",
        "is_blocked": updated.is_blocked,
    }

@router.get("/users")
async def get_all_users():
    """Получить список всех пользователей (для админки)"""
    users = await db.get_all_users()
    return [
        {
            "user_id": u.user_id,
            "username": u.username,
            "full_name": u.full_name,
            "balance": u.balance,
            "tariff": u.tariff,
            "is_blocked": u.is_blocked
        }
        for u in users
    ]


@router.get("/health/db")
async def health_db():
    """Проверка, что SQLite доступна и пишет на диск."""
    return await db.db_status()


# Заглушки под клиентские пути — та же auth-зависимость роутера.
# Пока нет бизнес-логики/таблиц: 501 после успешного auth (не путать с 403).

@router.api_route("/applications", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def applications_stub():
    """Заявки (эндпоинт зарезервирован, проверка SECRET_KEY уже пройдена)."""
    raise HTTPException(
        status_code=501,
        detail="Эндпоинт /api/applications пока не реализован (auth OK)",
    )


@router.api_route("/requisites", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def requisites_stub():
    """Реквизиты (эндпоинт зарезервирован, проверка SECRET_KEY уже пройдена)."""
    raise HTTPException(
        status_code=501,
        detail="Эндпоинт /api/requisites пока не реализован (auth OK)",
    )
