"""Бизнес-логика по пользователям. С БД общается только через репозитории."""

from typing import Any, Dict, Optional

from app.db import connection
from app.errors import ConflictError, NotFoundError
from app.repositories import orders as orders_repo
from app.repositories import users as users_repo
from app.repositories._sql import build_order_by

SORTABLE = {"id": "id", "full_name": "full_name", "created_at": "created_at"}


def list_users(
    page: int, page_size: int, city: Optional[str], search: Optional[str], sort: Optional[str]
) -> Dict[str, Any]:
    order_by = build_order_by(sort, SORTABLE, default="created_at DESC")
    offset = (page - 1) * page_size

    with connection(readonly=True) as conn:
        total = users_repo.count(conn, city=city, search=search)
        items = users_repo.list_users(
            conn, limit=page_size, offset=offset, city=city, search=search, order_by=order_by
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_user(user_id: int) -> Dict[str, Any]:
    with connection(readonly=True) as conn:
        user = users_repo.get_by_id(conn, user_id)

    if user is None:
        raise NotFoundError(f"Пользователь {user_id} не найден")
    return user


def create_user(email: str, full_name: str, city: Optional[str]) -> Dict[str, Any]:
    with connection() as conn:
        if users_repo.email_exists(conn, email):
            raise ConflictError(f"Пользователь с email {email} уже существует")
        return users_repo.create(conn, email, full_name, city)


def update_user(user_id: int, email: str, full_name: str, city: Optional[str]) -> Dict[str, Any]:
    with connection() as conn:
        if users_repo.email_exists(conn, email, exclude_id=user_id):
            raise ConflictError(f"Пользователь с email {email} уже существует")

        user = users_repo.update(conn, user_id, email, full_name, city)

    if user is None:
        raise NotFoundError(f"Пользователь {user_id} не найден")
    return user


def delete_user(user_id: int) -> None:
    with connection() as conn:
        deleted = users_repo.delete(conn, user_id)

    if not deleted:
        raise NotFoundError(f"Пользователь {user_id} не найден")


def list_user_orders(user_id: int, page: int, page_size: int, status: Optional[str]) -> Dict[str, Any]:
    """Заказы конкретного пользователя: GET /api/users/{id}/orders."""
    offset = (page - 1) * page_size

    with connection(readonly=True) as conn:
        if users_repo.get_by_id(conn, user_id) is None:
            raise NotFoundError(f"Пользователь {user_id} не найден")

        total = orders_repo.count(conn, user_id=user_id, status=status)
        items = orders_repo.list_orders(
            conn, limit=page_size, offset=offset, user_id=user_id, status=status
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}
