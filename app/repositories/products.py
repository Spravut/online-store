"""Доступ к таблице products.

Здесь живут поиск (ILIKE), фильтрация по категории и цене, сортировка
и пагинация — то есть ровно те запросы, которые станут интересными,
когда товаров станет много.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from psycopg import Connection

from app.repositories._sql import build_where

SORTABLE = {
    "id": "p.id",
    "name": "p.name",
    "price": "p.price",
    "created_at": "p.created_at",
}

COLUMNS = "p.id, p.category_id, p.name, p.description, p.price, p.stock, p.created_at"


def _filters(
    search: Optional[str],
    category_id: Optional[int],
    min_price: Optional[Decimal],
    max_price: Optional[Decimal],
) -> Tuple[str, List[Any]]:
    return build_where(
        [
            ("p.name ILIKE '%%' || %s || '%%'", search),
            ("p.category_id = %s", category_id),
            ("p.price >= %s", min_price),
            ("p.price <= %s", max_price),
        ]
    )


def count(
    conn: Connection,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
) -> int:
    where, params = _filters(search, category_id, min_price, max_price)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM products p {where}", params)
        return cur.fetchone()["total"]


def list_products(
    conn: Connection,
    limit: int,
    offset: int,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    order_by: str = "p.created_at DESC",
) -> List[Dict[str, Any]]:
    """JOIN #1 (простой): товары вместе с названием категории."""
    where, params = _filters(search, category_id, min_price, max_price)
    sql = f"""
        SELECT {COLUMNS}, c.name AS category_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        {where}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params + [limit, offset])
        return cur.fetchall()


def get_by_id(conn: Connection, product_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {COLUMNS} FROM products p WHERE p.id = %s", (product_id,))
        return cur.fetchone()


def create(
    conn: Connection,
    category_id: int,
    name: str,
    description: Optional[str],
    price: Decimal,
    stock: int,
) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO products AS p (category_id, name, description, price, stock)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {COLUMNS}
            """,
            (category_id, name, description, price, stock),
        )
        return cur.fetchone()


def update(
    conn: Connection,
    product_id: int,
    category_id: int,
    name: str,
    description: Optional[str],
    price: Decimal,
    stock: int,
) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE products AS p
            SET category_id = %s, name = %s, description = %s, price = %s, stock = %s
            WHERE p.id = %s
            RETURNING {COLUMNS}
            """,
            (category_id, name, description, price, stock, product_id),
        )
        return cur.fetchone()


def delete(conn: Connection, product_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        return cur.rowcount > 0


def existing_ids(conn: Connection, product_ids: List[int]) -> List[int]:
    """Из переданного списка id возвращает те, что реально есть в базе."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM products WHERE id = ANY(%s)", (product_ids,))
        return [row["id"] for row in cur.fetchall()]
