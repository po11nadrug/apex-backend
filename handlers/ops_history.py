"""
Общая история операций (все пополнения, списания, бонусы…).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from config import HISTORY_PER_PAGE
from database import db, format_dt, format_money
from keyboards import ops_history_kb
from ui import edit_screen

router = Router(name="ops_history")

TX_LABELS = {
    "deposit": "💳 Пополнение",
    "balance_add": "➕ Пополнение",
    "balance_sub": "➖ Списание",
    "balance_set": "✏️ Установка баланса",
    "bonus": "🎁 Бонус",
    "transfer_out": "📤 Перевод (исх.)",
    "transfer_in": "📥 Перевод (вх.)",
    "tariff_change": "📦 Смена тарифа",
    "admin_adjust": "⚙️ Корректировка",
}


def render_ops(items: list[dict], page: int, total: int) -> str:
    if not items:
        return (
            "<b>📜 История операций</b>\n\n"
            "Операций пока нет.\n"
            "Пополнения появятся здесь после раздела «Пополнение»."
        )

    total_pages = max(1, (total + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE)
    lines = [
        f"<b>📜 История операций</b>",
        f"Всего: <b>{total}</b> · стр. <b>{page + 1}/{total_pages}</b>\n",
    ]
    for tx in items:
        label = TX_LABELS.get(tx.get("type") or "", tx.get("type") or "—")
        amount = float(tx.get("amount") or 0)
        sign = "+" if amount > 0 else ""
        amount_str = f"{sign}{format_money(amount)}" if amount != 0 else "—"
        uid = tx.get("user_id")
        comment = tx.get("comment") or ""
        if len(comment) > 50:
            comment = comment[:47] + "…"
        lines.append(
            f"<b>{format_dt(tx.get('created_at'))}</b>  {label}\n"
            f"  ID <code>{uid}</code> · {amount_str}"
            + (f"\n  <i>{comment}</i>" if comment else "")
        )
        lines.append("")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    return text


@router.callback_query(F.data.startswith("ops:list:"))
async def cb_ops_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    if page < 0:
        page = 0

    total = await db.get_all_transactions_count()
    items = await db.get_all_transactions(page=page, per_page=HISTORY_PER_PAGE)
    await edit_screen(
        callback,
        render_ops(items, page, total),
        ops_history_kb(page, total, HISTORY_PER_PAGE),
    )
