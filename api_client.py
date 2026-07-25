"""
Связь админ-бота с API бэкенда Apex (Mini App).

Задачи:
  - регистрация пользователя при /start (POST /api/user/register)
  - подтянуть список (GET /api/users)
  - выставить баланс после пополнения (POST /api/user/{id}/balance)
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import API_SECRET_KEY, API_URL
from database import _now_iso

logger = logging.getLogger(__name__)

# Telegram ID обычно ≥ 5–6 цифр; 1 = тестовый мусор
MIN_REAL_TELEGRAM_ID = 10_000


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _headers(json_body: bool = False) -> dict[str, str]:
    h = {"x-secret-key": API_SECRET_KEY, "Accept": "application/json"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _request(
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 5.0,
) -> Any | None:
    if not API_URL or not API_SECRET_KEY:
        return None

    url = API_URL.rstrip("/") + path
    data = None
    headers = _headers(json_body=body is not None)
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        logger.warning("API %s %s → HTTP %s %s", method, path, e.code, err_body)
        return None
    except URLError as e:
        logger.warning("API %s %s недоступен: %s", method, path, e.reason)
        return None
    except Exception as e:
        logger.warning("API %s %s ошибка: %s", method, path, e)
        return None


def register_user_remote(
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> bool:
    """POST /api/user/register — создать пользователя на бэкенде для Mini App."""
    if user_id < MIN_REAL_TELEGRAM_ID:
        return False
    result = _request(
        "POST",
        "/api/user/register",
        {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
        },
    )
    ok = result is not None
    if ok:
        logger.info("API register ok user_id=%s", user_id)
    return ok


def set_balance_remote(
    user_id: int,
    amount: float,
    description: str = "Админ",
    *,
    mode: str = "set",
) -> bool:
    """
    POST /api/user/{id}/balance
    mode=set — абсолютное значение, mode=add — прибавить к текущему.
    """
    # На всякий случай регистрируем клиента в API (Mini App / бэкенд)
    register_user_remote(user_id)
    result = _request(
        "POST",
        f"/api/user/{user_id}/balance",
        {
            "amount": float(amount),
            "mode": mode if mode in ("set", "add") else "set",
            "description": description,
        },
    )
    ok = result is not None
    if ok:
        logger.info(
            "API balance ok user_id=%s mode=%s amount=%s",
            user_id,
            mode,
            amount,
        )
    return ok


def set_tariff_remote(user_id: int, tariff: str) -> bool:
    """POST /api/user/{id}/tariff — LITE / POWER / POWER+"""
    if user_id < MIN_REAL_TELEGRAM_ID:
        return False
    register_user_remote(user_id)
    result = _request(
        "POST",
        f"/api/user/{user_id}/tariff",
        {"tariff": str(tariff)},
    )
    ok = result is not None
    if ok:
        logger.info("API tariff ok user_id=%s tariff=%s", user_id, tariff)
    return ok


def add_bonus_remote(
    user_id: int,
    amount: float,
    description: str = "Бонус от администратора",
) -> bool:
    """POST /api/user/{id}/bonus — на бэкенде бонус идёт и в bonus_balance, и в balance."""
    if user_id < MIN_REAL_TELEGRAM_ID:
        return False
    register_user_remote(user_id)
    result = _request(
        "POST",
        f"/api/user/{user_id}/bonus",
        {
            "amount": float(amount),
            "description": description,
        },
    )
    ok = result is not None
    if ok:
        logger.info("API bonus ok user_id=%s amount=%s", user_id, amount)
    return ok


def set_blocked_remote(user_id: int, is_blocked: bool) -> bool:
    """POST /api/user/{id}/block"""
    if user_id < MIN_REAL_TELEGRAM_ID:
        return False
    register_user_remote(user_id)
    result = _request(
        "POST",
        f"/api/user/{user_id}/block",
        {"is_blocked": bool(is_blocked)},
    )
    ok = result is not None
    if ok:
        logger.info("API block ok user_id=%s blocked=%s", user_id, is_blocked)
    return ok




def fetch_remote_users(timeout: float = 12.0) -> list[dict[str, Any]]:
    """GET /api/users — только реальные Telegram ID."""
    data = _request("GET", "/api/users", timeout=timeout)
    if not isinstance(data, list):
        return []

    users: list[dict[str, Any]] = []
    for item in data:
        try:
            uid = int(item.get("user_id") or item.get("id"))
        except (TypeError, ValueError):
            continue
        if uid < MIN_REAL_TELEGRAM_ID:
            continue
        users.append(item)
    return users


async def sync_users_from_api(db) -> int:
    """Upsert пользователей с API в локальную БД. Возвращает число записей."""
    remote = fetch_remote_users()
    if not remote:
        return 0

    count = 0
    for item in remote:
        try:
            uid = int(item.get("user_id") or item.get("id"))
        except (TypeError, ValueError):
            continue
        if uid < MIN_REAL_TELEGRAM_ID:
            continue

        await db.ensure_user(
            uid,
            username=item.get("username"),
            full_name=item.get("full_name"),
        )

        try:
            balance = item.get("balance")
            tariff = item.get("tariff")
            bonus = item.get("bonus_balance")
            blocked = item.get("is_blocked")
            requisites = item.get("requisites")
            if any(v is not None for v in (balance, tariff, bonus, blocked, requisites)):
                await db.conn.execute(
                    """
                    UPDATE users SET
                        balance = COALESCE(?, balance),
                        tariff = COALESCE(?, tariff),
                        bonus_balance = COALESCE(?, bonus_balance),
                        is_blocked = COALESCE(?, is_blocked),
                        requisites = COALESCE(?, requisites)
                    WHERE user_id = ?
                    """,
                    (
                        float(balance) if balance is not None else None,
                        tariff,
                        float(bonus) if bonus is not None else None,
                        int(bool(blocked)) if blocked is not None else None,
                        requisites if requisites is not None else None,
                        uid,
                    ),
                )
                await db.conn.commit()
        except Exception as e:
            logger.debug("sync fields %s: %s", uid, e)
        count += 1
    return count


async def register_user_everywhere(
    db,
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> dict:
    """
    Полная регистрация: локальная БД + API бэкенда.
    Именно это вызывается на /start.
    """
    user = await db.ensure_user(user_id, username=username, full_name=full_name)
    register_user_remote(user_id, username=username, full_name=full_name)
    return user


async def sync_applications_from_api(db) -> int:
    """Sync applications from backend API to local DB (for admin-bot to see Mini App created requests)."""
    logger = logging.getLogger(__name__)
    apps = get_all_applications_remote()
    if not apps:
        logger.info("No applications fetched from API (API_URL or SECRET_KEY not set?)")
        return 0

    count = 0
    for app in apps:
        app_id = app.get("id")
        if not app_id:
            continue
        try:
            await db.conn.execute(
                """
                INSERT OR REPLACE INTO applications 
                (id, user_id, type, status, amount, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_id,
                    int(app.get("user_id") or 0),
                    app.get("type") or "deposit_request",
                    app.get("status") or "pending",
                    float(app.get("amount") or 0),
                    json.dumps(app.get("details") or {}),
                    app.get("created_at") or _now_iso(),
                ),
            )
            count += 1
            logger.info("Upserted app: id=%s, user_id=%s", app_id, app.get("user_id"))
        except Exception as e:
            logger.debug("Failed to upsert app %s: %s", app_id, e)
    await db.conn.commit()
    logger.info("Sync completed: %s applications upserted", count)
    return count


def get_requisites_remote() -> dict | None:
    """GET /api/requisites — актуальные реквизиты для Mini App."""
    data = _request("GET", "/api/requisites")
    if not data or not isinstance(data, dict):
        return None
    return data


def set_requisites_remote(key: str = "deposit_card", value: dict = None) -> bool:
    """POST /api/requisites — обновить реквизиты."""
    if value is None:
        value = {}
    result = _request("POST", "/api/requisites", {"key": key, "value": value})
    return result is not None


def create_application_remote(
    user_id: int, amount: float = 0.0, details: str = "", app_type: str = "deposit_request"
) -> dict | None:
    """POST /api/applications — создать заявку из Mini App."""
    result = _request(
        "POST",
        "/api/applications",
        {
            "user_id": user_id,
            "amount": amount,
            "details": details,
            "type": app_type,
        },
    )
    return result


def get_all_applications_remote() -> list[dict]:
    """GET /api/applications — список заявок."""
    data = _request("GET", "/api/applications")
    if not data or not isinstance(data, list):
        return []
    return data


def confirm_application_remote(app_id: int, admin_id: int) -> dict | None:
    """POST /api/applications/{id}/confirm — подтвердить заявку."""
    result = _request(
        "POST",
        f"/api/applications/{app_id}/confirm",
        {"admin_id": admin_id},
    )
    return result


def reject_application_remote(app_id: int, admin_id: int) -> dict | None:
    """POST /api/applications/{id}/reject — отклонить заявку."""
    result = _request(
        "POST",
        f"/api/applications/{app_id}/reject",
        {"admin_id": admin_id},
    )
    return result
