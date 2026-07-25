"""
Список пользователей, поиск, карточка, история пользователя.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import json
import re

from api_client import sync_users_from_api, set_requisites_remote
from config import HISTORY_PER_PAGE, USERS_PER_PAGE
from database import db, format_dt, format_money
from keyboards import (
    cancel_search_kb,
    deposit_kb,
    history_kb,
    search_results_kb,
    requisites_input_kb,
    requisites_confirm_kb,
    user_card_kb,
    users_list_kb,
    edit_requisites_kb,
    requisites_confirmation_kb,
)
from states import ChangeDepositRequisites, ChangeRequisites, SearchUser
from ui import answer_cb, edit_screen

router = Router(name="users")
logger = logging.getLogger(__name__)


def render_user_card(user: dict) -> str:
    uname = f"@{user['username']}" if user.get("username") else "—"
    status = "🚫 <b>ЗАБЛОКИРОВАН</b>" if user.get("is_blocked") else "✅ Активен"
    return (
        f"<b>👤 Карточка пользователя</b>\n"
        f"{'─' * 28}\n"
        f"<b>ID:</b> <code>{user['user_id']}</code>\n"
        f"<b>Username:</b> {uname}\n"
        f"<b>Имя:</b> {user.get('full_name') or '—'}\n"
        f"<b>Статус:</b> {status}\n\n"
        f"<b>📦 Тариф:</b> {user.get('tariff', 'LITE')}\n"
        f"<b>💰 Баланс:</b> {format_money(user.get('balance'))}\n"
        f"<b>🎁 Бонусы:</b> {format_money(user.get('bonus_balance'))}\n\n"
        f"<b>📅 Регистрация:</b> {format_dt(user.get('registered_at'))}\n"
        f"<b>🕐 Активность:</b> {format_dt(user.get('last_active'))}"
    )


TX_TYPE_LABELS = {
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


def render_history(transactions: list[dict], page: int, total: int) -> str:
    if not transactions:
        return (
            "<b>📜 История операций</b>\n\n"
            "Операций пока нет."
        )

    lines = [f"<b>📜 История операций</b>  ·  всего: {total}\n"]
    for tx in transactions:
        label = TX_TYPE_LABELS.get(tx["type"], tx["type"])
        amount = float(tx["amount"] or 0)
        sign = "+" if amount > 0 else ""
        amount_str = f"{sign}{format_money(amount)}" if amount != 0 else "—"
        comment = tx.get("comment") or ""
        if len(comment) > 60:
            comment = comment[:57] + "…"
        related = ""
        if tx.get("related_user"):
            related = f" · ↔ <code>{tx['related_user']}</code>"
        lines.append(
            f"<b>{format_dt(tx.get('created_at'))}</b>  {label}\n"
            f"  {amount_str}{related}"
            + (f"\n  <i>{comment}</i>" if comment else "")
        )
        lines.append("")

    total_pages = max(1, (total + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE)
    lines.append(f"Стр. {page + 1}/{total_pages}")
    return "\n".join(lines)


def _user_line(u: dict, idx: int) -> str:
    uname = f"@{u['username']}" if u.get("username") else "без username"
    name = u.get("full_name") or "—"
    blocked = " 🚫" if u.get("is_blocked") else ""
    return (
        f"{idx}. <code>{u['user_id']}</code>{blocked} · {uname}\n"
        f"   {name} · {u.get('tariff', 'LITE')} · {format_money(u.get('balance'))}"
    )


def build_users_list_text(users: list[dict], page: int, total: int) -> str:
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    start_idx = page * USERS_PER_PAGE + 1

    if total == 0:
        return (
            "<b>👥 Пользователи</b>\n\n"
            "Список пуст.\n\n"
            "Клиенты появляются после <b>/start</b> у бота приложения "
            "<b>@ApexDomainAppBot</b> (или через Mini App).\n\n"
            "Нажмите «🔄 Обновить» после регистрации."
        )

    lines = [
        "<b>👥 Пользователи</b>",
        f"Всего: <b>{total}</b> · стр. <b>{page + 1}/{total_pages}</b>\n",
    ]
    for i, u in enumerate(users):
        lines.append(_user_line(u, start_idx + i))
        lines.append("")
    lines.append("Нажмите на пользователя · 🔍 Найти · 🔄 Обновить")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    return text


async def _load_page(page: int, *, do_sync: bool = False) -> tuple[list[dict], int]:
    """Быстрая загрузка из локальной БД; sync с API только по кнопке Обновить."""
    if do_sync:
        try:
            n = await sync_users_from_api(db)
            if n:
                logger.info("Synced %s users from API", n)
        except Exception:
            logger.exception("sync failed")

    total = await db.get_users_count()
    users = await db.get_users_page(page=page, per_page=USERS_PER_PAGE)
    # Фильтр по источнику (бот_id / source / from_bot) можно добавить здесь,
    # если в API пришёл основной ID бота (@ApexDomainAppBot).
    # Пока просто показываем всех пользователей из таблицы (регистрация через Mini App / основной бот).
    return users, total


async def _show_users_list(
    callback: CallbackQuery,
    page: int,
    *,
    do_sync: bool = False,
) -> None:
    users, total = await _load_page(page, do_sync=do_sync)
    text = build_users_list_text(users, page, total)
    await edit_screen(callback, text, users_list_kb(users, page, total))


@router.callback_query(F.data.startswith("users:list:"))
async def cb_users_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    if page < 0:
        page = 0
    # без API на каждое нажатие — быстрее
    await _show_users_list(callback, page, do_sync=False)


@router.callback_query(F.data.startswith("users:refresh:"))
async def cb_users_refresh(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    # sync + show; edit_screen сам answer
    await _show_users_list(callback, page, do_sync=True)


@router.message(Command("users"))
async def cmd_users(message: Message, state: FSMContext) -> None:
    await state.clear()
    users, total = await _load_page(0, do_sync=False)
    await message.answer(
        build_users_list_text(users, 0, total),
        reply_markup=users_list_kb(users, 0, total),
    )


@router.callback_query(F.data == "users:search")
async def cb_users_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchUser.waiting_query)
    await edit_screen(
        callback,
        "<b>🔍 Найти пользователя</b>\n\n"
        "Отправьте <b>Telegram ID</b> или <b>username</b>.\n\n"
        "Примеры:\n"
        "• <code>123456789</code>\n"
        "• <code>@username</code>",
        cancel_search_kb(),
    )


@router.message(SearchUser.waiting_query)
async def msg_search_query(message: Message, state: FSMContext) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите ID или username.", reply_markup=cancel_search_kb())
        return

    users = await db.search_users(query)
    await state.clear()

    await db.log_admin(
        admin_id=message.from_user.id,
        action="search_user",
        details=f"query={query!r}, found={len(users)}",
    )

    if not users:
        await message.answer(
            f"По запросу <code>{query}</code> ничего не найдено.",
            reply_markup=cancel_search_kb(),
        )
        return

    if len(users) == 1:
        user = users[0]
        await message.answer(render_user_card(user), reply_markup=user_card_kb(user))
        return

    await message.answer(
        f"Найдено: <b>{len(users)}</b>\nВыберите:",
        reply_markup=search_results_kb(users),
    )


@router.callback_query(F.data.startswith("user:card:"))
async def cb_user_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await answer_cb(callback, "Пользователь не найден", show_alert=True)
        return
    await edit_screen(callback, render_user_card(user), user_card_kb(user))


@router.callback_query(F.data.startswith("user:history:"))
async def cb_user_history(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = callback.data.split(":")
    user_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    user = await db.get_user(user_id)
    if not user:
        await answer_cb(callback, "Пользователь не найден", show_alert=True)
        return

    total = await db.get_user_transactions_count(user_id)
    txs = await db.get_user_transactions(user_id, page=page, per_page=HISTORY_PER_PAGE)
    display_name = (
        f"@{user['username']}" if user.get("username") else (user.get("full_name") or "—")
    )
    text = (
        f"<b>Пользователь:</b> <code>{user_id}</code> · {display_name}\n\n"
        + render_history(txs, page, total)
    )
    await edit_screen(
        callback,
        text,
        history_kb(user_id, page, total, HISTORY_PER_PAGE),
    )


# ── Изменение реквизитов ─────────────────────────────────────

@router.callback_query(F.data.startswith("user:requisites:"))
async def cb_requisites_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_id = int(callback.data.split(":")[-1])
    user = await db.get_user(user_id)
    if not user:
        await answer_cb(callback, "Пользователь не найден", show_alert=True)
        return

    current_req = user.get("requisites") or {}
    current_text = json.dumps(current_req, ensure_ascii=False, indent=2)

    # Обновляем экран с новой кнопкой шаблона
    await edit_screen(
        callback,
        f"<b>📝 Изменение реквизитов</b>\n\n"
        f"Пользователь: <code>{user_id}</code>\n\n"
        f"<b>Текущие реквизиты:</b>\n<pre>{current_text}</pre>\n\n"
        f"Отправьте новые реквизиты в формате JSON:\n"
        f"например: <code>{{\"wallet\": \"0x123...\", \"network\": \"TON\", \"memo\": \"user123\"}}</code>\n\n"
        f"Или <code>{{}}</code> для очистки.",
        requisites_input_kb(user_id),
    )
    await state.set_state(ChangeRequisites.waiting_requisites)
    await state.update_data(target_user_id=user_id)


@router.callback_query(F.data.startswith("user:requisites:template:"))
async def cb_requisites_template(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка Получить шаблон JSON"""
    user_id = int(callback.data.split(":")[-1])
    sample = {
        "wallet": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        "network": "TON",
        "memo": "user123"
    }
    sample_text = json.dumps(sample, ensure_ascii=False, indent=2)

    await answer_cb(
        callback,
        f"📋 **Шаблон JSON для реквизитов**:\n\n<pre>{sample_text}</pre>\n\n"
        f"Скопируйте и отправьте в поле ниже.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("user:requisites:confirm:"))
async def cb_requisites_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение изменения реквизитов"""
    user_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    requisites = data.get("new_requisites") or {}

    # Успешное обновление в БД и Mini App (уже сделано в input handler)
    await db.log_admin(
        admin_id=callback.from_user.id,
        action="change_requisites_confirm",
        target_id=user_id,
        details=f"confirmed JSON len={len(json.dumps(requisites))}",
    )

    # Сообщение об успешном изменении (вместо "пополнение" как в запросе)
    success_msg = (
        f"✅ **Успешное изменение реквизитов**!\n\n"
        f"Пользователь: <code>{user_id}</code>\n"
        f"Реквизиты:\n<pre>{json.dumps(requisites, ensure_ascii=False, indent=2)}</pre>"
    )

    await callback.message.answer(success_msg, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data.startswith("user:requisites:cancel:"))
async def cb_requisites_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await answer_cb(callback, "❌ Изменение реквизитов отменено", show_alert=True)


@router.message(ChangeRequisites.waiting_requisites)
async def msg_requisites_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user_id = data.get("target_user_id")
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "❌ Введите JSON или {} .",
            reply_markup=requisites_input_kb(user_id),
        )
        return

    try:
        if text == "{}":
            requisites = {}
        else:
            requisites = json.loads(text)
            if not isinstance(requisites, dict):
                raise ValueError("Must be JSON object")

        # Сохраняем в состоянии для подтверждения
        await state.update_data(new_requisites=requisites)

        updated_user = await db.set_user_requisites(user_id, requisites)
        if not updated_user:
            await message.answer("❌ Не удалось обновить реквизиты в БД.")
            return

        # Update in Mini App API (general requisites)
        api_ok = set_requisites_remote("deposit_card", requisites)

        await db.log_admin(
            admin_id=message.from_user.id,
            action="change_requisites",
            target_id=user_id,
            details=f"JSON len={len(json.dumps(requisites))}; api_ok={api_ok}",
        )

        api_note = "✅ Реквизиты обновлены в Mini App" if api_ok else "⚠️ Локально обновлено, но API недоступен"

        # Вместо прямого успеха — показываем подтверждение
        await message.answer(
            f"📝 **Изменения внесены**\n\n"
            f"Реквизиты:\n<pre>{json.dumps(requisites, ensure_ascii=False, indent=2)}</pre>\n\n"
            f"Подтвердите действие ниже.",
            reply_markup=requisites_confirm_kb(user_id),
        )
        await state.clear()
    except json.JSONDecodeError:
        await message.answer(
            "❌ Неверный JSON. Попробуйте снова (или {} для очистки).",
            reply_markup=requisites_input_kb(user_id),
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {str(e)}\n\nПопробуйте снова.",
            reply_markup=requisites_input_kb(user_id),
        )


# ── Изменение реквизитов для пополнения ─────────────────────────────────────

@router.callback_query(F.data == "edit_requisites")
async def cb_edit_requisites(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_screen(
        callback,
        "<b>📝 Изменение реквизитов для пополнения</b>\n\n"
        "Отправьте новые реквизиты для пополнения в следующем формате:\n\n"
        "Номер карты\nБанк\nПолучатель\n\n"
        "Пример:\n"
        "2202 2085 8983 3509\n"
        "СберБанк\n"
        "Алина К.",
        edit_requisites_kb(),
    )
    await state.set_state(ChangeDepositRequisites.waiting_input)


@router.callback_query(F.data == "edit_requisites:template")
async def cb_requisites_template(callback: CallbackQuery, state: FSMContext) -> None:
    sample = (
        "2202 2085 8983 3509\n"
        "СберБанк\n"
        "Алина К."
    )
    await answer_cb(
        callback,
        f"📋 **Пример заполнения реквизитов**:\n\n<pre>{sample}</pre>",
        show_alert=True,
    )


@router.message(ChangeDepositRequisites.waiting_input)
async def msg_requisites_input(message: Message, state: FSMContext) -> None:
    try:
        text = message.text or ""

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) >= 3:
            card_number = lines[0]
            bank = lines[1]
            recipient = lines[2]
            parsed = {
                "card_number": card_number,
                "bank": bank,
                "recipient": recipient,
            }
        else:
            raise ValueError("Неверный формат шаблона. Ожидается 3 строки: номер карты, название банка, имя получателя.")

        await state.update_data(parsed_data=parsed)
        await state.set_state(ChangeDepositRequisites.waiting_confirmation)

        await message.answer(
            f"<b>📝 Распознанные реквизиты:</b>\n\n"
            f"Номер карты: <b>{parsed['card_number']}</b>\n"
            f"Банк: <b>{parsed['bank']}</b>\n"
            f"Получатель: <b>{parsed['recipient']}</b>\n\n"
            "Подтвердите изменения ниже.",
            parse_mode="HTML",
            reply_markup=requisites_confirmation_kb(),
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка парсинга: {str(e)}\n\nПопробуйте ещё раз с шаблоном.",
            reply_markup=deposit_kb(),
        )


@router.callback_query(F.data == "edit_requisites:confirm")
async def cb_requisites_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    parsed = data.get("parsed_data", {})

    # Сохраняем в базу
    await db.set_requisites("deposit_card", parsed)

    await db.log_admin(
        admin_id=callback.from_user.id,
        action="change_deposit_requisites",
        target_id=None,
        details=f"card_number={parsed.get('card_number')}; bank={parsed.get('bank')}; recipient={parsed.get('recipient')}",
    )

    await callback.message.answer(
        "✅ **Реквизиты успешно обновлены!**\n\n"
        "Теперь Mini App будет использовать эти реквизиты для пополнений.",
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "edit_requisites:cancel")
async def cb_requisites_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_screen(
        callback,
        "<b>💳 Пополнение</b>\n\n"
        "Зачислите средства клиенту после подтверждения платежа.\n\n"
        "Нажмите «Пополнить баланс» и отправьте данные по шаблону.",
        deposit_kb(),
    )
