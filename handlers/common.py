"""
Команды админ-панели.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards import main_menu_kb
from ui import edit_screen, send_or_edit_menu

router = Router(name="common")

ADMIN_WELCOME = (
    "<b>⚡ Apex Admin Panel</b>\n\n"
    "Клиенты: бот приложения <b>@ApexDomainAppBot</b> → /start.\n\n"
    "• <b>Пользователи</b> — список и поиск\n"
    "• <b>Пополнение</b> — зачислить баланс после оплаты\n"
    "• <b>История операций</b> — все начисления\n\n"
    "Выберите раздел:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    # одно меню, без дублей при повторном /start
    await send_or_edit_menu(message, ADMIN_WELCOME, main_menu_kb())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_or_edit_menu(message, ADMIN_WELCOME, main_menu_kb())


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_screen(callback, ADMIN_WELCOME, main_menu_kb())


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    from ui import answer_cb
    await answer_cb(callback)
