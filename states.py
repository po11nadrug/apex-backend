"""
FSM-состояния для диалогов администратора.
"""

from aiogram.fsm.state import State, StatesGroup


class SearchUser(StatesGroup):
    """Поиск пользователя по ID или username."""
    waiting_query = State()


class DepositUser(StatesGroup):
    """Пополнение: данные → подтверждение → зачисление."""
    waiting_data = State()
    waiting_confirm = State()


class ChangeBalance(StatesGroup):
    """Изменение баланса пользователя."""
    waiting_action = State()
    waiting_amount = State()


class ChangeTariff(StatesGroup):
    """Смена тарифа пользователя."""
    waiting_tariff = State()


class AccrueBonus(StatesGroup):
    """Начисление бонуса."""
    waiting_amount = State()
    waiting_comment = State()


class SendMessage(StatesGroup):
    """Отправка системного сообщения пользователю."""
    waiting_text = State()


class ChangeRequisites(StatesGroup):
    """Изменение реквизитов пользователя."""
    waiting_requisites = State()


class ChangeDepositRequisites(StatesGroup):
    """Изменение реквизитов для пополнения (пополнение в Mini App)."""
    waiting_template = State()
    waiting_input = State()
    waiting_confirmation = State()
