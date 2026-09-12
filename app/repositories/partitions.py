"""Доступ к системным каталогам PostgreSQL для работы с партициями.

Только SQL: создание партиций, чтение списка существующих и хранение состояния
алерта. Логика «какие партиции нужны» живёт в app/services/partitions.py.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from psycopg import Connection, sql

STATE_TABLE = "partition_alert_state"


def is_partitioned(conn: Connection, table: str) -> bool:
    """Является ли таблица партиционированной (relkind = 'p')."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relkind = 'p' AS partitioned
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s AND n.nspname = current_schema()
            """,
            (table,),
        )
        row = cur.fetchone()
        return bool(row and row["partitioned"])


def list_partitions(conn: Connection, parent: str) -> List[Dict[str, Any]]:
    """Список партиций таблицы вместе с их границами и размером."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT child.relname                              AS partition_name,
                   pg_get_expr(child.relpartbound, child.oid) AS bounds,
                   pg_size_pretty(pg_relation_size(child.oid)) AS size
            FROM pg_inherits i
            JOIN pg_class parent ON parent.oid = i.inhparent
            JOIN pg_class child  ON child.oid  = i.inhrelid
            JOIN pg_namespace n  ON n.oid = parent.relnamespace
            WHERE parent.relname = %s AND n.nspname = current_schema()
            ORDER BY child.relname
            """,
            (parent,),
        )
        return cur.fetchall()


def partition_names(conn: Connection, parent: str) -> List[str]:
    return [row["partition_name"] for row in list_partitions(conn, parent)]


def create_range_partition(
    conn: Connection, parent: str, name: str, date_from: date, date_to: date
) -> None:
    """CREATE TABLE ... PARTITION OF ... FOR VALUES FROM ... TO ...

    Имена таблиц подставляются через sql.Identifier, границы — параметрами,
    поэтому склейки строк здесь нет.
    """
    statement = sql.SQL(
        "CREATE TABLE IF NOT EXISTS {child} PARTITION OF {parent} "
        "FOR VALUES FROM ({date_from}) TO ({date_to})"
    ).format(
        child=sql.Identifier(name),
        parent=sql.Identifier(parent),
        date_from=sql.Literal(date_from),
        date_to=sql.Literal(date_to),
    )
    with conn.cursor() as cur:
        cur.execute(statement)


def drop_partition(conn: Connection, name: str) -> None:
    """Удаление партиции — нужно для проверки алерта (имитация сбоя job)."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(name)))


# --------------------------------------------------------- состояние алерта
def ensure_state_table(conn: Connection) -> None:
    """Таблица, в которой запоминается последний отправленный статус.

    Нужна, чтобы не слать один и тот же alert каждые пять минут и чтобы
    отправить recovery ровно один раз.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
                table_name   TEXT PRIMARY KEY,
                status       TEXT        NOT NULL,
                details      TEXT,
                changed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_checked TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def get_alert_state(conn: Connection, table: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT table_name, status, details, changed_at, last_checked "
            f"FROM {STATE_TABLE} WHERE table_name = %s",
            (table,),
        )
        return cur.fetchone()


def save_alert_state(conn: Connection, table: str, status: str, details: str) -> None:
    """Сохраняет статус. `changed_at` обновляется только при смене статуса."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {STATE_TABLE} (table_name, status, details)
            VALUES (%s, %s, %s)
            ON CONFLICT (table_name) DO UPDATE
            SET status       = EXCLUDED.status,
                details      = EXCLUDED.details,
                last_checked = now(),
                changed_at   = CASE
                                   WHEN {STATE_TABLE}.status <> EXCLUDED.status
                                   THEN now()
                                   ELSE {STATE_TABLE}.changed_at
                               END
            """,
            (table, status, details),
        )
