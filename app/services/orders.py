"""Бизнес-логика по заказам — основной растущей сущности."""

from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.db import connection
from app.errors import NotFoundError, ValidationError
from app.repositories import orders as orders_repo
from app.repositories import products as products_repo
from app.repositories import users as users_repo
from app.repositories._sql import build_order_by

ALLOWED_STATUSES = ("NEW", "PAID", "SHIPPED", "DELIVERED", "CANCELLED")


def list_orders(
    page: int,
    page_size: int,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    min_amount: Optional[Decimal] = None,
    sort: Optional[str] = None,
) -> Dict[str, Any]:
    if status is not None and status not in ALLOWED_STATUSES:
        raise ValidationError(f"Недопустимый статус '{status}'. Доступны: {', '.join(ALLOWED_STATUSES)}")

    order_by = build_order_by(sort, orders_repo.SORTABLE, default="o.created_at DESC")
    offset = (page - 1) * page_size

    with connection(readonly=True) as conn:
        total = orders_repo.count(
            conn,
            status=status,
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
            min_amount=min_amount,
        )
        items = orders_repo.list_orders(
            conn,
            limit=page_size,
            offset=offset,
            status=status,
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
            min_amount=min_amount,
            order_by=order_by,
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_order(order_id: int) -> Dict[str, Any]:
    """Заказ целиком: шапка с покупателем + позиции с товарами и категориями."""
    with connection(readonly=True) as conn:
        order = orders_repo.get_header_with_user(conn, order_id)
        if order is None:
            raise NotFoundError(f"Заказ {order_id} не найден")

        order["items"] = orders_repo.list_items(conn, order_id)

    return order


def list_order_items(order_id: int) -> List[Dict[str, Any]]:
    with connection(readonly=True) as conn:
        if orders_repo.get_by_id(conn, order_id) is None:
            raise NotFoundError(f"Заказ {order_id} не найден")
        return orders_repo.list_items(conn, order_id)


def _merge_items(items: Sequence[Any]) -> List[Tuple[int, int]]:
    """Схлопывает повторяющиеся товары в одну позицию (order_items уникален по паре)."""
    merged: "OrderedDict[int, int]" = OrderedDict()
    for item in items:
        merged[item.product_id] = merged.get(item.product_id, 0) + item.quantity
    return list(merged.items())


def create_order(user_id: int, items: Sequence[Any]) -> Dict[str, Any]:
    merged = _merge_items(items)

    with connection() as conn:
        if users_repo.get_by_id(conn, user_id) is None:
            raise NotFoundError(f"Пользователь {user_id} не найден")

        requested_ids = [product_id for product_id, _ in merged]
        found_ids = set(products_repo.existing_ids(conn, requested_ids))
        missing = [str(pid) for pid in requested_ids if pid not in found_ids]
        if missing:
            raise NotFoundError(f"Товары не найдены: {', '.join(missing)}")

        # Заказ и все его позиции пишутся в одной транзакции:
        # соединение из пула коммитится при выходе из блока `with`.
        order = orders_repo.create(conn, user_id, merged)

    return get_order(order["id"])


def update_order_status(order_id: int, status: str) -> Dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValidationError(f"Недопустимый статус '{status}'. Доступны: {', '.join(ALLOWED_STATUSES)}")

    with connection() as conn:
        order = orders_repo.update_status(conn, order_id, status)

    if order is None:
        raise NotFoundError(f"Заказ {order_id} не найден")
    return order


def delete_order(order_id: int) -> None:
    with connection() as conn:
        deleted = orders_repo.delete(conn, order_id)

    if not deleted:
        raise NotFoundError(f"Заказ {order_id} не найден")
