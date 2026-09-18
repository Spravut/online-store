"""Единственное место, где приложение подключается к PostgreSQL.

Пулов два:

* `_primary_pool` — запись и всё, что требует свежих данных;
* `_replica_pool` — читающие запросы, уходят на реплику.

Репозитории про это не знают: они получают готовое соединение через
`connection(readonly=...)`. Поэтому переезд чтения на реплику не потребовал
правок ни в одном SQL-запросе.

Если `DATABASE_REPLICA_URL` не задан, оба режима работают с primary —
сервис поднимается и без реплики.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)


def _build_pool(conninfo: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo=conninfo,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )


_primary_pool = _build_pool(settings.database_url)
_replica_pool: Optional[ConnectionPool] = (
    _build_pool(settings.database_replica_url) if settings.database_replica_url else None
)

# Совместимость со старым кодом, который импортировал `pool` напрямую.
pool = _primary_pool


def replica_enabled() -> bool:
    return _replica_pool is not None


def open_pool() -> None:
    _primary_pool.open()
    _primary_pool.wait(timeout=30)
    logger.info("пул primary открыт")

    if _replica_pool is not None:
        try:
            _replica_pool.open()
            _replica_pool.wait(timeout=30)
            logger.info("пул реплики открыт: чтение уходит на реплику")
        except Exception as exc:  # noqa: BLE001
            # Недоступная реплика не должна мешать сервису подняться:
            # чтение просто вернётся на primary.
            logger.error("реплика недоступна (%s), чтение идёт в primary", exc)
            _disable_replica()
    else:
        logger.info("DATABASE_REPLICA_URL не задан: чтение идёт в primary")


def _disable_replica() -> None:
    global _replica_pool
    if _replica_pool is not None:
        try:
            _replica_pool.close()
        except Exception:  # noqa: BLE001
            pass
        _replica_pool = None


def close_pool() -> None:
    _primary_pool.close()
    if _replica_pool is not None:
        _replica_pool.close()


@contextmanager
def connection(readonly: bool = False) -> Iterator[Connection]:
    """Соединение из подходящего пула.

    `readonly=True` — запрос только читает, его можно отдать реплике.
    Всё остальное идёт в primary.

    Важное следствие: сразу после записи читать через реплику нельзя —
    изменение могло ещё не доехать (replication lag). В таких местах
    используется `connection()` без флага.
    """
    target = _replica_pool if (readonly and _replica_pool is not None) else _primary_pool
    with target.connection() as conn:
        yield conn


# --------------------------------------------------------------- диагностика
def primary_replication_status() -> List[Dict[str, Any]]:
    """`pg_stat_replication` на primary: кто подключён и насколько отстаёт."""
    with _primary_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT application_name,
                   client_addr::text AS client_addr,
                   state,
                   sync_state,
                   sent_lsn::text,
                   replay_lsn::text,
                   COALESCE(
                       EXTRACT(milliseconds FROM replay_lag)::int, 0
                   ) AS replay_lag_ms
            FROM pg_stat_replication
            """
        )
        return cur.fetchall()


def replica_status() -> Optional[Dict[str, Any]]:
    """Состояние реплики: в режиме восстановления и на сколько отстала."""
    if _replica_pool is None:
        return None

    try:
        with _replica_pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_is_in_recovery() AS in_recovery,
                       pg_last_wal_replay_lsn()::text AS replay_lsn,
                       -- float8, а не numeric: Decimal не сериализуется в JSON
                       COALESCE(
                           ROUND(EXTRACT(epoch FROM now() - pg_last_xact_replay_timestamp())::numeric, 3),
                           0
                       )::float8 AS lag_seconds
                """
            )
            return cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
