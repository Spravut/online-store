"""Бизнес-логика аналитики."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db import connection
from app.errors import NotFoundError
from app.repositories import analytics as analytics_repo


def sales_by_category(
    created_from: Optional[datetime], created_to: Optional[datetime]
) -> List[Dict[str, Any]]:
    with connection(readonly=True) as conn:
        return analytics_repo.sales_by_category(conn, created_from, created_to)


def top_products(
    limit: int, created_from: Optional[datetime], created_to: Optional[datetime]
) -> List[Dict[str, Any]]:
    with connection(readonly=True) as conn:
        return analytics_repo.top_products(conn, limit, created_from, created_to)


def user_stats(user_id: int) -> Dict[str, Any]:
    with connection(readonly=True) as conn:
        stats = analytics_repo.user_stats(conn, user_id)

    if stats is None:
        raise NotFoundError(f"Пользователь {user_id} не найден")
    return stats
