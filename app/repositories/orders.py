"""Доступ к таблице orders — основной растущей сущности проекта.

Здесь собраны запросы, которые на модуле станут предметом оптимизации:
фильтрация по статусу, диапазон по created_at, сортировка, пагинация
и многотабличные JOIN-ы.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg import Connection

from app.repositories._sql import build_where

SORTABLE = {
    "id": "o.id",
    "created_at": "o.created_at",
    "updated_at": "o.updated_at",
    "total_amount": "o.total_amount",
    "status": "o.status",
}

COLUMNS = "o.id, o.user_id, o.status, o.total_amount, o.created_at, o.updated_at"


def _filters(
    status: Optional[str],
    user_id: Optional[int],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    min_amount: Optional[Decimal],
) -> Tuple[str, List[Any]]:
    return build_where(
        [
            ("o.status = %s", status),
            ("o.user_id = %s", user_id),
            ("o.created_at >= %s", created_from),
            ("o.created_at < %s", created_to),
            ("o.total_amount >= %s", min_amount),
        ]
    )


def count(
    conn: Connection,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    min_amount: Optional[Decimal] = None,
) -> int:
    where, params = _filters(status, user_id, created_from, created_to, min_amount)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM orders o {where}", params)
        return cur.fetchone()["total"]


def list_orders(
    conn: Connection,
    limit: int,
    offset: int,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    min_amount: Optional[Decimal] = None,
    order_by: str = "o.created_at DESC",
) -> List[Dict[str, Any]]:
    where, params = _filters(status, user_id, created_from, created_to, min_amount)
    sql = f"""
        SELECT {COLUMNS}
        FROM orders o
        {where}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params + [limit, offset])
        return cur.fetchall()


def get_by_id(conn: Connection, order_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {COLUMNS} FROM orders o WHERE o.id = %s", (order_id,))
        return cur.fetchone()


def get_header_with_user(conn: Connection, order_id: int) -> Optional[Dict[str, Any]]:
    """Заказ вместе с данными покупателя (JOIN orders + users)."""
    sql = f"""
        SELECT {COLUMNS},
               u.email     AS user_email,
               u.full_name AS user_full_name
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (order_id,))
        return cur.fetchone()


def list_items(conn: Connection, order_id: int) -> List[Dict[str, Any]]:
    """JOIN-запрос №1: позиции заказа с товаром и его категорией.

    orders -> order_items -> products -> categories
    """
    sql = """
        SELECT oi.id,
               oi.order_id,
               oi.product_id,
               p.name AS product_name,
               c.name AS category_name,
               oi.quantity,
               oi.price_at_purchase,
               (oi.quantity * oi.price_at_purchase) AS line_total
        FROM order_items oi
        JOIN orders     o ON o.id = oi.order_id
        JOIN products   p ON p.id = oi.product_id
        JOIN categories c ON c.id = p.category_id
        WHERE o.id = %s
        ORDER BY oi.id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (order_id,))
        return cur.fetchall()


def create(
    conn: Connection, user_id: int, items: Iterable[Tuple[int, int]]
) -> Dict[str, Any]:
    """Создаёт заказ вместе с позициями в одной транзакции.

    Цена товара фиксируется в момент покупки (price_at_purchase),
    сумма заказа пересчитывается из позиций.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (user_id) VALUES (%s) RETURNING id",
            (user_id,),
        )
        order_id = cur.fetchone()["id"]

        for product_id, quantity in items:
            cur.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
                SELECT %s, p.id, %s, p.price
                FROM products p
                WHERE p.id = %s
                """,
                (order_id, quantity, product_id),
            )

        cur.execute(
            f"""
            UPDATE orders AS o
            SET total_amount = (
                    SELECT COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)
                    FROM order_items oi
                    WHERE oi.order_id = o.id
                ),
                updated_at = now()
            WHERE o.id = %s
            RETURNING {COLUMNS}
            """,
            (order_id,),
        )
        return cur.fetchone()


def update_status(conn: Connection, order_id: int, status: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE orders AS o
            SET status = %s, updated_at = now()
            WHERE o.id = %s
            RETURNING {COLUMNS}
            """,
            (status, order_id),
        )
        return cur.fetchone()


def delete(conn: Connection, order_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        return cur.rowcount > 0
