from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Пользователи", callback_data="users_list"),
            InlineKeyboardButton(text="🔍 Поиск", callback_data="user_search")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="💸 Переводы", callback_data="transfers")
        ],
        [
            InlineKeyboardButton(text="📋 Логи админов", callback_data="admin_logs")
        ]
    ])
    return keyboard

def user_actions(user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"edit_balance:{user_id}"),
            InlineKeyboardButton(text="📈 Изменить тариф", callback_data=f"edit_tariff:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🎁 Начислить бонус", callback_data=f"add_bonus:{user_id}")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="users_list")
        ]
    ])
    return keyboard

def tariffs_keyboard(user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="LITE", callback_data=f"set_tariff:{user_id}:LITE"),
            InlineKeyboardButton(text="POWER", callback_data=f"set_tariff:{user_id}:POWER")
        ],
        [
            InlineKeyboardButton(text="POWER+", callback_data=f"set_tariff:{user_id}:POWER+")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"user:{user_id}")
        ]
    ])
    return keyboard