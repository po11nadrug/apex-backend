"""Middlewares пакета Админ-бота."""

from .admin import AdminOnlyMiddleware

__all__ = ["AdminOnlyMiddleware"]
