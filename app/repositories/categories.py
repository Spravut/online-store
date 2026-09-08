"""Доступ к таблице categories."""

from typing import Any, Dict, List, Optional

from psycopg import Connection


def list_all(conn: Connection) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, slug FROM categories ORDER BY name")
        return cur.fetchall()


def get_by_id(conn: Connection, category_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, slug FROM categories WHERE id = %s", (category_id,))
        return cur.fetchone()


def create(conn: Connection, name: str, slug: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO categories (name, slug) VALUES (%s, %s) RETURNING id, name, slug",
            (name, slug),
        )
        return cur.fetchone()


def delete(conn: Connection, category_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (category_id,))
        return cur.rowcount > 0
