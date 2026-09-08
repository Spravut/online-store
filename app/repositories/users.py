"""Доступ к таблице users. Только SQL, никакой бизнес-логики."""

from typing import Any, Dict, List, Optional

from psycopg import Connection

COLUMNS = "id, email, full_name, city, created_at"


def count(conn: Connection, city: Optional[str], search: Optional[str]) -> int:
    sql = "SELECT COUNT(*) AS total FROM users WHERE (%s::text IS NULL OR city = %s) AND (%s::text IS NULL OR full_name ILIKE '%%' || %s || '%%')"
    with conn.cursor() as cur:
        cur.execute(sql, (city, city, search, search))
        return cur.fetchone()["total"]


def list_users(
    conn: Connection,
    limit: int,
    offset: int,
    city: Optional[str] = None,
    search: Optional[str] = None,
    order_by: str = "created_at DESC",
) -> List[Dict[str, Any]]:
    sql = f"""
        SELECT {COLUMNS}
        FROM users
        WHERE (%s::text IS NULL OR city = %s)
          AND (%s::text IS NULL OR full_name ILIKE '%%' || %s || '%%')
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (city, city, search, search, limit, offset))
        return cur.fetchall()


def get_by_id(conn: Connection, user_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {COLUMNS} FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def create(conn: Connection, email: str, full_name: str, city: Optional[str]) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO users (email, full_name, city)
            VALUES (%s, %s, %s)
            RETURNING {COLUMNS}
            """,
            (email, full_name, city),
        )
        return cur.fetchone()


def update(
    conn: Connection, user_id: int, email: str, full_name: str, city: Optional[str]
) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users
            SET email = %s, full_name = %s, city = %s
            WHERE id = %s
            RETURNING {COLUMNS}
            """,
            (email, full_name, city, user_id),
        )
        return cur.fetchone()


def delete(conn: Connection, user_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return cur.rowcount > 0


def email_exists(conn: Connection, email: str, exclude_id: Optional[int] = None) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE email = %s AND (%s::bigint IS NULL OR id <> %s) LIMIT 1",
            (email, exclude_id, exclude_id),
        )
        return cur.fetchone() is not None
