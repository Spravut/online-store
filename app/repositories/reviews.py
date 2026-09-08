"""Доступ к таблице reviews."""

from typing import Any, Dict, List, Optional

from psycopg import Connection

COLUMNS = "r.id, r.product_id, r.user_id, r.rating, r.comment, r.created_at"


def count_by_product(conn: Connection, product_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM reviews WHERE product_id = %s", (product_id,))
        return cur.fetchone()["total"]


def list_by_product(
    conn: Connection, product_id: int, limit: int, offset: int
) -> List[Dict[str, Any]]:
    """Отзывы на товар вместе с именем автора."""
    sql = f"""
        SELECT {COLUMNS}, u.full_name AS user_full_name
        FROM reviews r
        JOIN users u ON u.id = r.user_id
        WHERE r.product_id = %s
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (product_id, limit, offset))
        return cur.fetchall()


def get_by_id(conn: Connection, review_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {COLUMNS} FROM reviews r WHERE r.id = %s", (review_id,))
        return cur.fetchone()


def create(
    conn: Connection, product_id: int, user_id: int, rating: int, comment: Optional[str]
) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO reviews AS r (product_id, user_id, rating, comment)
            VALUES (%s, %s, %s, %s)
            RETURNING {COLUMNS}
            """,
            (product_id, user_id, rating, comment),
        )
        return cur.fetchone()


def delete(conn: Connection, review_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        return cur.rowcount > 0


def exists(conn: Connection, product_id: int, user_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM reviews WHERE product_id = %s AND user_id = %s LIMIT 1",
            (product_id, user_id),
        )
        return cur.fetchone() is not None
