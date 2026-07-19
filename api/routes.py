from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import database as db
from config import SECRET_KEY

router = APIRouter()

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

# ================== ПРОВЕРКА СЕКРЕТНОГО КЛЮЧА ==================

async def verify_secret(x_secret_key: str = Header(...)):
    if x_secret_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return True

# ================== ЭНДПОИНТЫ ==================

@router.get("/user/{user_id}")
async def get_user_info(user_id: int, authorized: bool = Depends(verify_secret)):
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
async def register_user(data: RegisterUser, authorized: bool = Depends(verify_secret)):
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
async def update_user_balance(user_id: int, data: BalanceUpdate, authorized: bool = Depends(verify_secret)):
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
async def update_user_tariff(user_id: int, data: TariffUpdate, authorized: bool = Depends(verify_secret)):
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
async def add_user_bonus(user_id: int, data: BonusAdd, authorized: bool = Depends(verify_secret)):
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

@router.get("/users")
async def get_all_users(authorized: bool = Depends(verify_secret)):
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