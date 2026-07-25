"""
Система переводов между пользователями:
  - просмотр истории переводов
  - ручное создание перевода (админ)
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import TRANSFERS_PER_PAGE
from database import db, format_dt, format_money
from keyboards import cancel_transfer_kb, transfers_list_kb
from states import CreateTransfer

router = Router(name="transfers")


def _parse_amount(text: str) -> float | None:
    raw = (text or "").strip().replace(" ", "").replace(",", ".")
    raw = raw.replace("₽", "").replace("руб.", "").replace("руб", "")
    try:
        return float(raw)
    except ValueError:
        return None


def render_transfers(items: list[dict], page: int, total: int) -> str:
    if not items:
        return (
            "<b>💸 Переводы</b>\n\n"
            "Переводов пока нет.\n"
            "Создайте перевод вручную кнопкой ниже."
        )

    lines = [
        f"<b>💸 Переводы между пользователями</b>\n"
        f"Всего: <b>{total}</b>\n"
    ]
    for tx in items:
        amount = abs(float(tx["amount"] or 0))
        from_id = tx.get("user_id")
        to_id = tx.get("related_user")
        comment = tx.get("comment") or ""
        if len(comment) > 50:
            comment = comment[:47] + "…"
        lines.append(
            f"<b>{format_dt(tx.get('created_at'))}</b>\n"
            f"  <code>{from_id}</code> → <code>{to_id}</code>\n"
            f"  💰 {format_money(amount)}"
            + (f"\n  <i>{comment}</i>" if comment else "")
        )
        lines.append("")

    total_pages = max(1, (total + TRANSFERS_PER_PAGE - 1) // TRANSFERS_PER_PAGE)
    lines.append(f"Стр. {page + 1}/{total_pages}")
    return "\n".join(lines)


# ── Список ────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("transfers:list:"))
async def cb_transfers_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    page = int(callback.data.split(":")[-1])
    total = await db.get_transfers_count()
    items = await db.get_transfers(page=page, per_page=TRANSFERS_PER_PAGE)

    await callback.message.edit_text(
        render_transfers(items, page, total),
        reply_markup=transfers_list_kb(page, total, TRANSFERS_PER_PAGE),
    )
    await callback.answer()


# ── Создание перевода (FSM) ───────────────────────────────────


@router.callback_query(F.data == "transfers:create")
async def cb_transfer_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateTransfer.waiting_from_id)
    await callback.message.edit_text(
        "<b>➕ Создание перевода</b>\n\n"
        "Шаг 1/4. Введите <b>Telegram ID отправителя</b> "
        "(с кого списать):",
        reply_markup=cancel_transfer_kb(),
    )
    await callback.answer()


@router.message(CreateTransfer.waiting_from_id)
async def msg_transfer_from(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "Введите числовой Telegram ID.",
            reply_markup=cancel_transfer_kb(),
        )
        return

    from_id = int(raw)
    user = await db.get_user(from_id)
    if not user:
        await message.answer(
            f"❌ Пользователь <code>{from_id}</code> не найден.",
            reply_markup=cancel_transfer_kb(),
        )
        return

    await state.update_data(from_id=from_id)
    await state.set_state(CreateTransfer.waiting_to_id)
    await message.answer(
        f"Отправитель: <code>{from_id}</code> "
        f"(баланс {format_money(user['balance'])})\n\n"
        f"Шаг 2/4. Введите <b>Telegram ID получателя</b>:",
        reply_markup=cancel_transfer_kb(),
    )


@router.message(CreateTransfer.waiting_to_id)
async def msg_transfer_to(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "Введите числовой Telegram ID.",
            reply_markup=cancel_transfer_kb(),
        )
        return

    to_id = int(raw)
    data = await state.get_data()
    from_id = data.get("from_id")

    if to_id == from_id:
        await message.answer(
            "❌ Отправитель и получатель не могут совпадать.",
            reply_markup=cancel_transfer_kb(),
        )
        return

    user = await db.get_user(to_id)
    if not user:
        await message.answer(
            f"❌ Пользователь <code>{to_id}</code> не найден.",
            reply_markup=cancel_transfer_kb(),
        )
        return

    await state.update_data(to_id=to_id)
    await state.set_state(CreateTransfer.waiting_amount)
    await message.answer(
        f"Получатель: <code>{to_id}</code>\n\n"
        f"Шаг 3/4. Введите <b>сумму перевода</b> (₽):",
        reply_markup=cancel_transfer_kb(),
    )


@router.message(CreateTransfer.waiting_amount)
async def msg_transfer_amount(message: Message, state: FSMContext) -> None:
    amount = _parse_amount(message.text or "")
    if amount is None or amount <= 0:
        await message.answer(
            "❌ Введите положительную сумму, например: <code>1000.50</code>",
            reply_markup=cancel_transfer_kb(),
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(CreateTransfer.waiting_comment)
    await message.answer(
        f"Сумма: <b>{format_money(amount)}</b>\n\n"
        f"Шаг 4/4. Введите <b>комментарий</b> "
        f"(или «-» без комментария):",
        reply_markup=cancel_transfer_kb(),
    )


@router.message(CreateTransfer.waiting_comment)
async def msg_transfer_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    from_id = int(data["from_id"])
    to_id = int(data["to_id"])
    amount = float(data["amount"])
    comment = (message.text or "").strip()
    if comment == "-":
        comment = "Ручной перевод (админ)"

    ok, result_msg = await db.create_transfer(
        from_id,
        to_id,
        amount,
        comment=comment,
        admin_id=message.from_user.id,
    )
    await state.clear()

    await db.log_admin(
        admin_id=message.from_user.id,
        action="create_transfer",
        target_id=from_id,
        details=f"{from_id} → {to_id}; amount={amount}; ok={ok}; {comment!r}",
    )

    if ok:
        total = await db.get_transfers_count()
        items = await db.get_transfers(page=0, per_page=TRANSFERS_PER_PAGE)
        await message.answer(
            f"✅ {result_msg}\n"
            f"Комментарий: <i>{comment}</i>\n\n"
            + render_transfers(items, 0, total),
            reply_markup=transfers_list_kb(0, total, TRANSFERS_PER_PAGE),
        )
    else:
        await message.answer(
            f"❌ {result_msg}",
            reply_markup=cancel_transfer_kb(),
        )
