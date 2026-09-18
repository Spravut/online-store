"""Пулы соединений к шардам.

Шардов несколько и они полностью независимы: между ними нет ни репликации,
ни общих транзакций. Поэтому на каждый — свой пул, а какой именно взять,
решает router (`app/sharding/router.py`).

Адреса берутся из `SHARD_URLS` — список через запятую, порядок задаёт
номера шардов: первый URL это shard 0, второй — shard 1 и так далее.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Dict, Iterator, List

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings
from app.sharding.router import ShardRouter, build_router

logger = logging.getLogger(__name__)


def shard_urls() -> List[str]:
    """Список адресов шардов из конфигурации."""
    raw = settings.shard_urls.strip()
    if not raw:
        return []
    return [url.strip() for url in raw.split(",") if url.strip()]


_urls = shard_urls()
_pools: Dict[int, ConnectionPool] = {}
_router: ShardRouter | None = None


def sharding_enabled() -> bool:
    return bool(_urls)


def shard_ids() -> List[int]:
    return list(range(len(_urls)))


def shard_count() -> int:
    return len(_urls)


def router() -> ShardRouter:
    """Текущий router. Стратегия задаётся SHARD_STRATEGY."""
    global _router
    if _router is None:
        _router = build_router(
            settings.shard_strategy, shard_ids(), settings.shard_virtual_nodes
        )
    return _router


def route(key: object) -> int:
    """Номер шарда для конкретного shard key."""
    return router().route(key)


def open_shard_pools() -> None:
    """Открывает пул на каждый шард. Недоступный шард не валит запуск."""
    if not _urls:
        logger.info("SHARD_URLS не задан: шардирование выключено")
        return

    for shard_id, url in enumerate(_urls):
        pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=settings.shard_pool_max_size,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        try:
            pool.open()
            pool.wait(timeout=20)
            _pools[shard_id] = pool
            logger.info("shard %s подключён", shard_id)
        except Exception as exc:  # noqa: BLE001
            # Отказ одного шарда — сценарий из лабораторной №6: сервис
            # продолжает работать, недоступной становится только его часть.
            logger.error("shard %s недоступен: %s", shard_id, exc)

    logger.info("router: %s", router())


def close_shard_pools() -> None:
    for pool in _pools.values():
        pool.close()
    _pools.clear()


def shard_available(shard_id: int) -> bool:
    return shard_id in _pools


def available_shards() -> List[int]:
    return sorted(_pools)


class ShardUnavailable(RuntimeError):
    """Шард есть в конфигурации, но соединения к нему нет."""


@contextmanager
def shard_connection(shard_id: int) -> Iterator[Connection]:
    """Соединение с конкретным шардом по его номеру."""
    pool = _pools.get(shard_id)
    if pool is None:
        raise ShardUnavailable(f"shard {shard_id} недоступен")
    try:
        with pool.connection() as conn:
            yield conn
    except psycopg.OperationalError as exc:
        # Шард отвалился уже после старта: превращаем низкоуровневую
        # ошибку в понятную сервису, чтобы API отдал 503, а не 500.
        raise ShardUnavailable(f"shard {shard_id} недоступен: {exc}") from exc


@contextmanager
def connection_for(key: object) -> Iterator[Connection]:
    """Соединение с тем шардом, где живёт запись с этим shard key."""
    with shard_connection(route(key)) as conn:
        yield conn


def probe_shards() -> Dict[int, Dict[str, object]]:
    """Живая проверка каждого шарда: пул может быть открыт, а сервер — лежать.

    Открытый пул сам по себе ничего не гарантирует: контейнер могли
    остановить уже после старта приложения. Поэтому состояние шарда
    проверяется отдельным дешёвым запросом.
    """
    status: Dict[int, Dict[str, object]] = {}
    for shard_id in shard_ids():
        if shard_id not in _pools:
            status[shard_id] = {"ok": False, "error": "пул не открыт"}
            continue
        try:
            with _pools[shard_id].connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            status[shard_id] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            status[shard_id] = {"ok": False, "error": str(exc).splitlines()[0]}
    return status
