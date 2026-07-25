"""
Регистрация всех роутеров обработчиков.
"""

from aiogram import Dispatcher

from . import actions, common, deposit, ops_history, requests, stats, users


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(users.router)
    dp.include_router(deposit.router)
    dp.include_router(ops_history.router)
    dp.include_router(actions.router)
    dp.include_router(stats.router)
    dp.include_router(requests.router)
