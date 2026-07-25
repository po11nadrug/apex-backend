"""
Обработка заявок / приложений (applications).
Админ обрабатывает заявки на пополнение и вывод. 
Пользователи самостоятельно могут создавать инвестиционные заявки, распределять финансы и менять тариф в Mini App.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from api_client import set_balance_remote, set_tariff_remote
from database import db, format_dt, format_money
from keyboards import (
    app_detail_kb,
    requests_list_kb,
)
# no FSM needed for now
from ui import answer_cb, edit_screen
from .users import render_user_card

router = Router(name="requests")


@router.callback_query(F.data.startswith("apps:list:"))
async def cb_apps_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    if page < 0:
        page = 0

    total = await db.get_all_applications_count()
    applications = await db.get_all_applications(page=page, per_page=10)

    await edit_screen(
        callback,
        render_apps(applications, page, total),
        requests_list_kb(applications, page, total, 10),
    )


def render_apps(applications: list[dict], page: int, total: int) -> str:
    if not applications:
        return (
            "<b>📋 Заявки</b>\n\n"
            "Заявок пока нет.\n"
            "Пользователи будут создавать заявки в Mini App (инвестиции, вывод и т.д.)."
        )

    total_pages = max(1, (total + 10 - 1) // 10)
    lines = [
        f"<b>📋 Заявки ({total})</b>",
        f"Стр. {page + 1}/{total_pages}\n",
    ]
    for app in applications:
        app_id = app.get("id", "—")
        uid = app.get("user_id", "—")
        uname = app.get("username") or app.get("full_name") or "—"
        app_type = app.get("type", "—")
        status = app.get("status", "pending").upper()
        amount = float(app.get("amount") or 0)
        created = app.get("created_at", "—")
        details = app.get("details") or ""

        details_str = str(details) if details else ""
        lines.append(
            f"<b>{app_id}</b> · <b>{status}</b> · {app_type}\n"
            f"  {uname} (ID <code>{uid}</code>) · {format_money(amount) if amount else '—'} · {created}\n"
            + (f"  <i>{details_str[:100]}...</i>" if len(details_str) > 100 else f"  <i>{details_str}</i>")
        )
        lines.append("")

    return "\n".join(lines)


@router.callback_query(F.data.startswith("app:detail:"))
async def cb_app_detail(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    app = await db.get_application(app_id)
    if not app:
        await answer_cb(callback, "Заявка не найдена", show_alert=True)
        return

    await edit_screen(
        callback,
        f"<b>📋 Детали заявки #{app_id}</b>\n\n"
        f"Тип: <b>{app.get('type', '—')}</b>\n"
        f"Статус: <b>{app.get('status', 'pending').upper()}</b>\n"
        f"Сумма: {format_money(float(app.get('amount') or 0))}\n"
        f"Создана: {format_dt(app.get('created_at'))}\n"
        f"Детали: <pre>{app.get('details', '')}</pre>",
        app_detail_kb(app),
    )


@router.callback_query(F.data.startswith("app:approve:"))
async def cb_app_approve(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    app = await db.get_application(app_id)
    if not app:
        await answer_cb(callback, "Заявка не найдена", show_alert=True)
        return

    app_type = app.get("type", "")
    user_id = app.get("user_id")
    amount = float(app.get("amount") or 0)

    # Process based on type
    if app_type == "withdrawal_request":
        # Example: for withdrawal, perhaps deduct from balance or mark as processed
        # For simplicity, set status and log
        pass
    elif app_type == "deposit_request":
        # For deposit, already handled separately, but if pending
        pass
    elif app_type == "investment_request":
        # User self-service, but if admin approves, e.g. approve investment
        pass
    else:
        pass

    # Update status
    updated = await db.update_application_status(app_id, "approved", processed_by=callback.from_user.id)
    if updated:
        await answer_cb(callback, "Заявка одобрена")
        # If investment, perhaps credit balance or something, but since self, just log
        await db.log_admin(
            admin_id=callback.from_user.id,
            action="approve_application",
            target_id=user_id,
            details=f"app={app_id} type={app_type} amount={amount}; status=approved",
        )
        await edit_screen(
            callback,
            f"✅ Заявка одобрена\n\nТип: {app_type}\nID: <code>{user_id}</code>",
            None,
        )
    else:
        await answer_cb(callback, "Ошибка обновления")


@router.callback_query(F.data.startswith("app:reject:"))
async def cb_app_reject(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    app_id = int(callback.data.split(":")[-1])
    app = await db.get_application(app_id)
    if not app:
        await answer_cb(callback, "Заявка не найдена", show_alert=True)
        return

    user_id = app.get("user_id")

    updated = await db.update_application_status(app_id, "rejected", processed_by=callback.from_user.id)
    if updated:
        await answer_cb(callback, "Заявка отклонена")
        await db.log_admin(
            admin_id=callback.from_user.id,
            action="reject_application",
            target_id=user_id,
            details=f"app={app_id} status=rejected",
        )
        await edit_screen(
            callback,
            f"❌ Заявка отклонена\n\nТип: {app.get('type', '—')}\nID: <code>{user_id}</code>",
            None,
        )
    else:
        await answer_cb(callback, "Ошибка обновления")


# Note: if needed, add more statuses or specific logic here
