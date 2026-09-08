"""Доменные ошибки. Сервисы бросают их, API-слой превращает в HTTP-коды."""


class AppError(Exception):
    pass


class NotFoundError(AppError):
    """Запись не найдена."""


class ConflictError(AppError):
    """Нарушение бизнес-правила или уникальности."""


class ValidationError(AppError):
    """Некорректные входные данные, которые нельзя поймать схемой."""
