"""Аналитические запросы: JOIN-ы через несколько таблиц + агрегация.

Именно эти запросы первыми деградируют при росте объёма данных,
поэтому они вынесены в отдельный репозиторий.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from psycopg import Connection

# Отменённые заказы не считаем выручкой.
EXCLUDED_STATUS = "CANCELLED"


def sales_by_category(
    conn: Connection,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Агрегирующий запрос: продажи по категориям.

    categories -> products -> order_items -> orders
    COUNT(DISTINCT ...), SUM, AVG, GROUP BY, HAVING.
    """
    sql = """
        SELECT c.id                                          AS category_id,
               c.name                                        AS category_name,
               COUNT(DISTINCT o.id)                          AS orders_count,
               COALESCE(SUM(oi.quantity), 0)                 AS items_sold,
               COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) AS revenue,
               COALESCE(ROUND(AVG(oi.quantity * oi.price_at_purchase), 2), 0) AS avg_order_item
        FROM categories c
        JOIN products    p  ON p.category_id = c.id
        JOIN order_items oi ON oi.product_id = p.id
        JOIN orders      o  ON o.id = oi.order_id
        WHERE o.status <> %s
          AND (%s::timestamptz IS NULL OR o.created_at >= %s)
          AND (%s::timestamptz IS NULL OR o.created_at <  %s)
        GROUP BY c.id, c.name
        HAVING SUM(oi.quantity) > 0
        ORDER BY revenue DESC
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (EXCLUDED_STATUS, created_from, created_from, created_to, created_to),
        )
        return cur.fetchall()


def top_products(
    conn: Connection,
    limit: int = 10,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """JOIN-запрос №2: топ товаров по выручке с категорией и рейтингом.

    products -> categories -> order_items -> orders, плюс подзапрос
    с агрегацией по reviews (отдельно, чтобы отзывы не размножали строки).
    """
    sql = """
        SELECT p.id                                          AS product_id,
               p.name                                        AS product_name,
               c.name                                        AS category_name,
               SUM(oi.quantity)                              AS units_sold,
               SUM(oi.quantity * oi.price_at_purchase)       AS revenue,
               ROUND(r.avg_rating, 2)                        AS avg_rating,
               COALESCE(r.reviews_count, 0)                  AS reviews_count
        FROM products p
        JOIN categories  c  ON c.id = p.category_id
        JOIN order_items oi ON oi.product_id = p.id
        JOIN orders      o  ON o.id = oi.order_id
        LEFT JOIN (
            SELECT product_id,
                   AVG(rating)::numeric AS avg_rating,
                   COUNT(*)             AS reviews_count
            FROM reviews
            GROUP BY product_id
        ) AS r ON r.product_id = p.id
        WHERE o.status <> %s
          AND (%s::timestamptz IS NULL OR o.created_at >= %s)
          AND (%s::timestamptz IS NULL OR o.created_at <  %s)
        GROUP BY p.id, p.name, c.name, r.avg_rating, r.reviews_count
        ORDER BY revenue DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (EXCLUDED_STATUS, created_from, created_from, created_to, created_to, limit),
        )
        return cur.fetchall()


def user_stats(conn: Connection, user_id: int) -> Optional[Dict[str, Any]]:
    """Агрегация по конкретному пользователю: сколько заказов и на какую сумму."""
    sql = """
        SELECT u.id                                        AS user_id,
               u.full_name,
               COUNT(o.id)                                 AS orders_count,
               COALESCE(SUM(o.total_amount), 0)            AS total_spent,
               COALESCE(ROUND(AVG(o.total_amount), 2), 0)  AS avg_order_amount,
               MAX(o.created_at)                           AS last_order_at
        FROM users u
        LEFT JOIN orders o ON o.user_id = u.id AND o.status <> %s
        WHERE u.id = %s
        GROUP BY u.id, u.full_name
    """
    with conn.cursor() as cur:
        cur.execute(sql, (EXCLUDED_STATUS, user_id))
        return cur.fetchone()
