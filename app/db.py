"""Единственное место, где приложение подключается к PostgreSQL.

Здесь живёт пул соединений и контекстные менеджеры, через которые работают
репозитории. Когда на модуле появится реплика, менять нужно будет только этот
файл: в `connection(readonly=True)` подставится пул реплики.
"""

from contextlib import contextmanager
from typing import Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

pool = ConnectionPool(
    conninfo=settings.database_url,
    min_size=settings.db_pool_min_size,
    max_size=settings.db_pool_max_size,
    kwargs={"row_factory": dict_row},
    open=False,
)


def open_pool() -> None:
    pool.open()
    pool.wait(timeout=30)


def close_pool() -> None:
    pool.close()


@contextmanager
def connection(readonly: bool = False) -> Iterator[Connection]:
    """Соединение из пула.

    `readonly=True` помечает запросы, которые в будущем уйдут на реплику.
    Сейчас оба режима ходят в один и тот же primary.
    """
    with pool.connection() as conn:
        yield conn
