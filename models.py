from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    user_id: int
    username: Optional[str]
    full_name: Optional[str]
    balance: float = 0.0
    tariff: str = "LITE"
    bonus_balance: float = 0.0
    is_blocked: bool = False
    registered_at: Optional[str] = None
    last_active: Optional[str] = None

@dataclass
class Transaction:
    id: Optional[int]
    user_id: int
    type: str
    amount: float
    description: str
    created_at: Optional[str] = None
    admin_id: Optional[int] = None