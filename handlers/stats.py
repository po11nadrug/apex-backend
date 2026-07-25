"""
Логи администраторов (статистика убрана из меню).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import db, format_dt
from keyboards import main_menu_kb
from ui import edit_screen

router = Router(name="stats")


@router.callback_query(F.data == "logs:list")
async def cb_admin_logs(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    logs = await db.get_admin_logs(limit=30)

    if not logs:
        text = (
            "<b>📋 Логи администраторов</b>\n\n"
            "Пока нет записей."
        )
    else:
        lines = [f"<b>📋 Логи администраторов</b>  ·  последние {len(logs)}\n"]
        for log in logs:
            details = log.get("details") or ""
            if len(details) > 80:
                details = details[:77] + "…"
            target = f" → <code>{log['target_id']}</code>" if log.get("target_id") else ""
            lines.append(
                f"<b>{format_dt(log.get('created_at'))}</b>\n"
                f"  admin <code>{log['admin_id']}</code> · "
                f"<code>{log['action']}</code>{target}"
                + (f"\n  <i>{details}</i>" if details else "")
            )
            lines.append("")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "…"

    await edit_screen(callback, text, main_menu_kb())
