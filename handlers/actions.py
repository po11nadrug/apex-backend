"""
Действия над пользователем:
  - баланс (add / sub / set)
  - бонус
  - блокировка
  - системное сообщение
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from api_client import (
    add_bonus_remote,
    set_balance_remote,
    set_blocked_remote,
)
from database import db, format_money
from keyboards import (
    balance_action_kb,
    cancel_to_user_kb,
    confirm_block_kb,
    user_card_kb,
)
from states import AccrueBonus, ChangeBalance, SendMessage
from ui import answer_cb, edit_screen

from .users import render_user_card

router = Router(name="actions")


def _parse_amount(text: str) -> float | None:
    """Парсинг суммы: допускает запятую и пробелы."""
    raw = (text or "").strip().replace(" ", "").replace(",", ".")
    # Убрать символ рубля, если вставили
    raw = raw.replace("₽", "").replace("руб.", "").replace("руб", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value


# ══════════════════════════════════════════════════════════════
#  БАЛАНС
# ══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("user:balance:"))
async def cb_balance_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await answer_cb(callback, "Пользователь не найден", show_alert=True)
        return

    await edit_screen(
        callback,
        f"<b>💰 Изменение баланса</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n"
        f"Текущий баланс: <b>{format_money(user['balance'])}</b>\n\n"
        f"Выберите действие:",
        balance_action_kb(user_id),
    )


@router.callback_query(F.data.startswith("balance:"))
async def cb_balance_action(callback: CallbackQuery, state: FSMContext) -> None:
    # balance:{add|sub|set}:{user_id}
    parts = callback.data.split(":")
    action = parts[1]
    user_id = int(parts[2])

    user = await db.get_user(user_id)
    if not user:
        await answer_cb(callback, "Пользователь не найден", show_alert=True)
        return

    labels = {
        "add": "➕ Добавить к балансу",
        "sub": "➖ Убавить с баланса",
        "set": "✏️ Установить баланс",
    }
    prompts = {
        "add": "Введите сумму для <b>добавления</b> (₽):",
        "sub": "Введите сумму для <b>списания</b> (₽):",
        "set": "Введите <b>новое значение</b> баланса (₽):",
    }

    await state.set_state(ChangeBalance.waiting_amount)
    await state.update_data(balance_action=action, target_user_id=user_id)

    await edit_screen(
        callback,
        f"<b>{labels[action]}</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n"
        f"Текущий баланс: <b>{format_money(user['balance'])}</b>\n\n"
        f"{prompts[action]}",
        cancel_to_user_kb(user_id),
    )


@router.message(ChangeBalance.waiting_amount)
async def msg_balance_amount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get("balance_action")
    user_id = data.get("target_user_id")
    amount = _parse_amount(message.text or "")

    if amount is None:
        await message.answer(
            "❌ Некорректная сумма. Введите число, например: <code>1500.50</code>",
            reply_markup=cancel_to_user_kb(user_id),
        )
        return

    if action in ("add", "sub") and amount <= 0:
        await message.answer(
            "❌ Сумма должна быть больше нуля.",
            reply_markup=cancel_to_user_kb(user_id),
        )
        return

    if action == "set" and amount < 0:
        await message.answer(
            "❌ Баланс не может быть отрицательным.",
            reply_markup=cancel_to_user_kb(user_id),
        )
        return

    user = await db.get_user(user_id)
    if not user:
        await state.clear()
        await message.answer("Пользователь не найден.")
        return

    old_balance = float(user["balance"])
    admin_id = message.from_user.id

    if action == "add":
        updated = await db.change_balance(
            user_id,
            amount,
            tx_type="balance_add",
            comment=f"Админ +{amount}",
            admin_id=admin_id,
        )
        detail = f"+{format_money(amount)}"
    elif action == "sub":
        if old_balance < amount:
            await message.answer(
                f"❌ Недостаточно средств (баланс {format_money(old_balance)}).",
                reply_markup=cancel_to_user_kb(user_id),
            )
            return
        updated = await db.change_balance(
            user_id,
            -amount,
            tx_type="balance_sub",
            comment=f"Админ −{amount}",
            admin_id=admin_id,
        )
        detail = f"−{format_money(amount)}"
    else:  # set
        updated = await db.set_balance(
            user_id,
            amount,
            tx_type="balance_set",
            comment=f"Админ set → {amount}",
            admin_id=admin_id,
        )
        detail = f"set → {format_money(amount)}"

    await state.clear()

    if not updated:
        await message.answer("Ошибка обновления баланса.")
        return

    # Дублируем баланс в API — чтобы Mini App увидел то же значение
    api_ok = set_balance_remote(
        user_id,
        float(updated["balance"]),
        description=f"Админ {action}: {detail}",
    )

    await db.log_admin(
        admin_id=admin_id,
        action="change_balance",
        target_id=user_id,
        details=f"{action}: {detail}; was {format_money(old_balance)}; api={api_ok}",
    )

    api_note = (
        "✅ Баланс отправлен в приложение (API)"
        if api_ok
        else "⚠️ Локально обновлено, но API бэкенда недоступен — в Mini App баланс может не совпасть"
    )

    await message.answer(
        f"✅ Баланс обновлён\n"
        f"Было: {format_money(old_balance)}\n"
        f"Стало: <b>{format_money(updated['balance'])}</b>\n"
        f"{api_note}\n\n"
        + render_user_card(updated),
        reply_markup=user_card_kb(updated),
    )


# ══════════════════════════════════════════════════════════════
#  БОНУС
# ══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("user:bonus:"))
async def cb_bonus_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await state.set_state(AccrueBonus.waiting_amount)
    await state.update_data(target_user_id=user_id)

    await edit_screen(
        callback,
        f"<b>🎁 Начисление бонуса</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n"
        f"Текущие бонусы: <b>{format_money(user['bonus_balance'])}</b>\n\n"
        f"Введите сумму бонуса (₽):",
        cancel_to_user_kb(user_id),
    )


@router.message(AccrueBonus.waiting_amount)
async def msg_bonus_amount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user_id = data.get("target_user_id")
    amount = _parse_amount(message.text or "")

    if amount is None or amount <= 0:
        await message.answer(
            "❌ Введите положительное число, например: <code>500</code>",
            reply_markup=cancel_to_user_kb(user_id),
        )
        return

    await state.update_data(bonus_amount=amount)
    await state.set_state(AccrueBonus.waiting_comment)
    await message.answer(
        f"Сумма: <b>{format_money(amount)}</b>\n\n"
        f"Введите комментарий к бонусу (или отправьте «-» без комментария):",
        reply_markup=cancel_to_user_kb(user_id),
    )


@router.message(AccrueBonus.waiting_comment)
async def msg_bonus_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user_id = data.get("target_user_id")
    amount = float(data.get("bonus_amount", 0))
    comment = (message.text or "").strip()
    if comment == "-":
        comment = None

    desc = comment or f"Бонус от админа +{amount}"
    updated = await db.add_bonus(
        user_id,
        amount,
        comment=desc,
        admin_id=message.from_user.id,
    )
    await state.clear()

    if not updated:
        await message.answer("Пользователь не найден.")
        return

    # На бэкенде бонус также зачисляется на основной баланс — зеркалим локально
    updated = await db.change_balance(
        user_id,
        amount,
        tx_type="bonus_to_balance",
        comment=desc,
        admin_id=message.from_user.id,
    ) or updated

    api_ok = add_bonus_remote(user_id, amount, description=desc)

    await db.log_admin(
        admin_id=message.from_user.id,
        action="accrue_bonus",
        target_id=user_id,
        details=f"+{amount}; comment={comment!r}; api={api_ok}",
    )

    api_note = (
        "✅ Бонус отправлен в приложение (API)"
        if api_ok
        else "⚠️ Локально начислено, но API бэкенда недоступен"
    )

    await message.answer(
        f"✅ Начислен бонус <b>{format_money(amount)}</b>\n"
        f"Бонусный баланс: <b>{format_money(updated['bonus_balance'])}</b>\n"
        f"Баланс: <b>{format_money(updated['balance'])}</b>\n"
        f"{api_note}\n\n"
        + render_user_card(updated),
        reply_markup=user_card_kb(updated),
    )


# ══════════════════════════════════════════════════════════════
#  БЛОКИРОВКА
# ══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("user:block:"))
async def cb_block_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    will_block = not bool(user.get("is_blocked"))
    action_word = "заблокировать" if will_block else "разблокировать"

    await edit_screen(
        callback,
        f"<b>⚠️ Подтверждение</b>\n\n"
        f"Вы уверены, что хотите <b>{action_word}</b> пользователя "
        f"<code>{user_id}</code>?",
        confirm_block_kb(user_id, will_block),
    )


@router.callback_query(F.data.startswith("user:block_yes:"))
async def cb_block_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    updated = await db.set_blocked(user_id, True)
    if not updated:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    api_ok = set_blocked_remote(user_id, True)

    await db.log_admin(
        admin_id=callback.from_user.id,
        action="block_user",
        target_id=user_id,
        details=f"blocked=True; api={api_ok}",
    )

    api_note = "✅ В приложении" if api_ok else "⚠️ API недоступен"
    await edit_screen(
        callback,
        f"🔒 Пользователь <code>{user_id}</code> <b>заблокирован</b>.\n"
        f"{api_note}\n\n"
        + render_user_card(updated),
        user_card_kb(updated),
        answer_text="Пользователь заблокирован",
    )


@router.callback_query(F.data.startswith("user:unblock_yes:"))
async def cb_unblock_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    updated = await db.set_blocked(user_id, False)
    if not updated:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    api_ok = set_blocked_remote(user_id, False)

    await db.log_admin(
        admin_id=callback.from_user.id,
        action="unblock_user",
        target_id=user_id,
        details=f"blocked=False; api={api_ok}",
    )

    api_note = "✅ В приложении" if api_ok else "⚠️ API недоступен"
    await edit_screen(
        callback,
        f"🔓 Пользователь <code>{user_id}</code> <b>разблокирован</b>.\n"
        f"{api_note}\n\n"
        + render_user_card(updated),
        user_card_kb(updated),
        answer_text="Пользователь разблокирован",
    )


# ══════════════════════════════════════════════════════════════
#  СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЮ
# ══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("user:message:"))
async def cb_message_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await state.set_state(SendMessage.waiting_text)
    await state.update_data(target_user_id=user_id)

    display_name = (
        f"@{user['username']}"
        if user.get("username")
        else (user.get("full_name") or "")
    )
    await edit_screen(
        callback,
        f"<b>✉️ Системное сообщение</b>\n\n"
        f"Получатель: <code>{user_id}</code>\n"
        f"{display_name}\n\n"
        f"Введите текст сообщения.\n"
        f"Оно будет отправлено от имени бота с пометкой «Apex System».",
        cancel_to_user_kb(user_id),
    )


@router.message(SendMessage.waiting_text)
async def msg_send_system(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user_id = data.get("target_user_id")
    text = (message.text or "").strip()

    if not text:
        await message.answer(
            "Сообщение не может быть пустым.",
            reply_markup=cancel_to_user_kb(user_id),
        )
        return

    payload = (
        "<b>🔔 Сообщение от системы Apex</b>\n"
        f"{'─' * 24}\n"
        f"{text}"
    )

    try:
        await bot.send_message(chat_id=user_id, text=payload)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 — показываем админу причину
        ok = False
        error = str(exc)

    await state.clear()
    user = await db.get_user(user_id)

    await db.log_admin(
        admin_id=message.from_user.id,
        action="send_message",
        target_id=user_id,
        details=f"ok={ok}; text={text[:200]!r}" + (f"; err={error}" if error else ""),
    )

    if ok:
        reply = f"✅ Сообщение отправлено пользователю <code>{user_id}</code>."
    else:
        reply = (
            f"❌ Не удалось отправить сообщение пользователю <code>{user_id}</code>.\n"
            f"<i>{error}</i>\n\n"
            f"Частые причины: пользователь не запускал этого бота, "
            f"заблокировал бота, или ID неверный."
        )

    if user:
        await message.answer(
            reply + "\n\n" + render_user_card(user),
            reply_markup=user_card_kb(user),
        )
    else:
        await message.answer(reply)
