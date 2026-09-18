"""Запросы к шардированным данным (лабораторная №6).

Здесь видно главное следствие шардирования: часть запросов осталась
обычным SQL к одному PostgreSQL, а часть превратилась в scatter-gather —
backend рассылает запрос на все шарды и сам склеивает результат.

Разделение:

* `user_*`      — single-shard, в WHERE есть shard key (user_id);
* `all_*`       — distributed, shard key неизвестен, идём во все шарды;
* `*_with_user` — cross-shard JOIN, склейка выполняется в приложении.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from psycopg import Connection

from app.db import connection as main_connection
from app.sharding.pools import (
    ShardUnavailable,
    available_shards,
    connection_for,
    route,
    shard_connection,
    shard_count,
    shard_ids,
)

ORDER_COLUMNS = "o.id, o.user_id, o.status, o.total_amount, o.created_at, o.updated_at"


# ----------------------------------------------------------------- scatter
def scatter(
    fn: Callable[[Connection, int], Any],
    shards: Optional[List[int]] = None,
    parallel: bool = True,
) -> Dict[str, Any]:
    """Выполняет `fn` на каждом шарде и возвращает результаты вместе с диагностикой.

    Шарды опрашиваются параллельно: последовательный обход означал бы, что
    время запроса растёт линейно с числом шардов. Параллельный обход
    упирается в самый медленный шард — это уже max, а не сумма.

    Недоступный шард не роняет весь запрос: он попадает в `failed`, а
    ответ помечается как частичный (`partial: true`). Так сервис переживает
    сценарий "Shard 2 ✗" из задания 6.
    """
    targets = shards if shards is not None else shard_ids()

    def run_one(shard_id: int) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            with shard_connection(shard_id) as conn:
                data = fn(conn, shard_id)
            return {
                "shard": shard_id,
                "ok": True,
                "data": data,
                "ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except (ShardUnavailable, Exception) as exc:  # noqa: BLE001
            return {
                "shard": shard_id,
                "ok": False,
                "error": str(exc),
                "ms": round((time.perf_counter() - started) * 1000, 2),
            }

    started = time.perf_counter()
    if parallel and len(targets) > 1:
        with ThreadPoolExecutor(max_workers=len(targets)) as executor:
            results = list(executor.map(run_one, targets))
    else:
        results = [run_one(shard_id) for shard_id in targets]
    total_ms = round((time.perf_counter() - started) * 1000, 2)

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    return {
        "results": ok,
        "failed": failed,
        "partial": bool(failed),
        "shards_queried": len(targets),
        "total_ms": total_ms,
        "slowest_shard_ms": max((r["ms"] for r in results), default=0.0),
    }


# ------------------------------------------------------- single-shard queries
def user_orders(user_id: int, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Задание 2: single-shard query.

    В WHERE есть shard key, поэтому router точно знает адрес и остальные
    шарды не опрашиваются вообще — ни один заказ этого пользователя туда
    физически попасть не мог.
    """
    shard_id = route(user_id)
    started = time.perf_counter()
    with connection_for(user_id) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {ORDER_COLUMNS}
            FROM orders o
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        rows = cur.fetchall()
    return {
        "user_id": user_id,
        "shard": shard_id,
        "shards_queried": 1,
        "orders": rows,
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def user_order_with_items(user_id: int, order_id: int) -> Dict[str, Any]:
    """Задание 4: JOIN, который остался локальным.

    `order_items` лежит на том же шарде, что и заказ, потому что при
    загрузке ему проставили тот же shard key (user_id). Поэтому JOIN
    выполняется обычным SQL внутри одного PostgreSQL.
    """
    shard_id = route(user_id)
    with connection_for(user_id) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {ORDER_COLUMNS},
                   oi.product_id,
                   oi.quantity,
                   oi.price_at_purchase,
                   (oi.quantity * oi.price_at_purchase) AS line_total
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id AND oi.user_id = o.user_id
            WHERE o.user_id = %s AND o.id = %s
            ORDER BY oi.id
            """,
            (user_id, order_id),
        )
        rows = cur.fetchall()
    return {"user_id": user_id, "order_id": order_id, "shard": shard_id, "items": rows}


def user_stats(user_id: int) -> Dict[str, Any]:
    """Агрегация по одному пользователю — тоже single-shard.

    Агрегат распределённым становится не сам по себе, а когда в запросе
    нет shard key.
    """
    shard_id = route(user_id)
    with connection_for(user_id) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)                                  AS orders_count,
                   COALESCE(SUM(total_amount), 0)::float8    AS total_spent,
                   COALESCE(AVG(total_amount), 0)::float8    AS avg_order_amount,
                   MAX(created_at)                           AS last_order_at
            FROM orders
            WHERE user_id = %s AND status <> 'CANCELLED'
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return {"user_id": user_id, "shard": shard_id, "shards_queried": 1, **row}


# --------------------------------------------------------- distributed queries
def shard_stats() -> Dict[str, Any]:
    """Сколько заказов и уникальных пользователей лежит на каждом шарде."""

    def one(conn: Connection, shard_id: int) -> Dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)                   AS orders,
                       COUNT(DISTINCT user_id)    AS users,
                       COALESCE(SUM(total_amount), 0)::float8 AS revenue
                FROM orders
                """
            )
            return cur.fetchone()

    outcome = scatter(one)
    per_shard = [{"shard": r["shard"], **r["data"], "ms": r["ms"]} for r in outcome["results"]]
    total_orders = sum(item["orders"] for item in per_shard)
    for item in per_shard:
        item["share_pct"] = round(item["orders"] * 100 / total_orders, 2) if total_orders else 0.0

    return {
        "shards": per_shard,
        "failed": outcome["failed"],
        "partial": outcome["partial"],
        "total_orders": total_orders,
        "total_ms": outcome["total_ms"],
    }


def all_orders_count(status: Optional[str] = None) -> Dict[str, Any]:
    """Задание 3: COUNT(*) по всей системе.

    Ни один шард не знает общего числа заказов — у каждого только своя
    часть. Backend суммирует частичные COUNT'ы сам.
    """

    def one(conn: Connection, shard_id: int) -> int:
        with conn.cursor() as cur:
            if status:
                cur.execute("SELECT COUNT(*) AS n FROM orders WHERE status = %s", (status,))
            else:
                cur.execute("SELECT COUNT(*) AS n FROM orders")
            return cur.fetchone()["n"]

    outcome = scatter(one)
    return {
        "status": status,
        "per_shard": {str(r["shard"]): r["data"] for r in outcome["results"]},
        "total": sum(r["data"] for r in outcome["results"]),
        "shards_queried": outcome["shards_queried"],
        "partial": outcome["partial"],
        "failed": outcome["failed"],
        "total_ms": outcome["total_ms"],
        "slowest_shard_ms": outcome["slowest_shard_ms"],
    }


def revenue_by_status() -> Dict[str, Any]:
    """GROUP BY через все шарды.

    Каждый шард считает свой GROUP BY, приложение складывает группы с
    одинаковым ключом. SUM и COUNT складываются напрямую; AVG — нет,
    его приходится пересчитывать как SUM/COUNT, иначе получилось бы
    среднее от средних.
    """

    def one(conn: Connection, shard_id: int) -> List[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status,
                       COUNT(*)                              AS orders,
                       COALESCE(SUM(total_amount), 0)::float8 AS revenue
                FROM orders
                GROUP BY status
                """
            )
            return cur.fetchall()

    outcome = scatter(one)
    merged: Dict[str, Dict[str, Any]] = {}
    for result in outcome["results"]:
        for row in result["data"]:
            bucket = merged.setdefault(row["status"], {"status": row["status"], "orders": 0, "revenue": 0.0})
            bucket["orders"] += row["orders"]
            bucket["revenue"] += row["revenue"]

    rows = sorted(merged.values(), key=lambda item: item["revenue"], reverse=True)
    for row in rows:
        row["revenue"] = round(row["revenue"], 2)
        # AVG пересчитан из сумм, а не усреднён по шардам.
        row["avg_order_amount"] = round(row["revenue"] / row["orders"], 2) if row["orders"] else 0.0

    return {
        "rows": rows,
        "shards_queried": outcome["shards_queried"],
        "partial": outcome["partial"],
        "failed": outcome["failed"],
        "total_ms": outcome["total_ms"],
    }


def recent_orders(limit: int = 100) -> Dict[str, Any]:
    """Задание 5: ORDER BY created_at DESC LIMIT N поверх всех шардов.

    С одного шарда взять top-N нельзя: глобальный топ мог целиком лежать
    на соседнем. Поэтому берём top-N с каждого шарда (это гарантирует, что
    глобальный top-N весь попал в выборку) и отрезаем первые N после слияния.

    Цена: с сети приходит N * (число шардов) строк ради N нужных.
    """

    def one(conn: Connection, shard_id: int) -> List[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {ORDER_COLUMNS}
                FROM orders o
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        for row in rows:
            row["shard"] = shard_id
        return rows

    outcome = scatter(one)
    fetched: List[Dict[str, Any]] = []
    for result in outcome["results"]:
        fetched.extend(result["data"])

    merged = sorted(fetched, key=lambda row: (row["created_at"], row["id"]), reverse=True)[:limit]
    return {
        "orders": merged,
        "rows_fetched": len(fetched),
        "rows_returned": len(merged),
        "overhead_rows": len(fetched) - len(merged),
        "shards_queried": outcome["shards_queried"],
        "partial": outcome["partial"],
        "failed": outcome["failed"],
        "total_ms": outcome["total_ms"],
    }


def recent_orders_with_users(limit: int = 20) -> Dict[str, Any]:
    """Задание 4: JOIN между шардированной и нешардированной таблицей.

    `orders` распределены по шардам, `users` остались в основной базе.
    Одним SQL это не выразить: у PostgreSQL, где лежит заказ, таблицы
    `users` просто нет. Поэтому JOIN выполняется в два шага в приложении:

    1. scatter-gather достаёт заказы и собирает множество user_id;
    2. один запрос в основную базу подтягивает пользователей;
    3. приложение склеивает по ключу (hash join вручную).
    """
    orders_page = recent_orders(limit)
    rows = orders_page["orders"]
    user_ids = sorted({row["user_id"] for row in rows})

    users: Dict[int, Dict[str, Any]] = {}
    if user_ids:
        with main_connection(readonly=True) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, city FROM users WHERE id = ANY(%s)",
                (user_ids,),
            )
            users = {row["id"]: row for row in cur.fetchall()}

    for row in rows:
        user = users.get(row["user_id"])
        row["user_email"] = user["email"] if user else None
        row["user_full_name"] = user["full_name"] if user else None

    return {
        "orders": rows,
        "join_performed_in": "application",
        "shard_roundtrips": orders_page["shards_queried"],
        "extra_roundtrips": 1 if user_ids else 0,
        "user_ids_transferred": len(user_ids),
        "partial": orders_page["partial"],
        "failed": orders_page["failed"],
    }


def find_order_by_id(order_id: int) -> Dict[str, Any]:
    """Поиск заказа по id — а id не является shard key.

    Router бессилен: чтобы узнать, где лежит заказ, нужно спросить все
    шарды. Тот самый случай, когда неудачно выбранный доступ к данным
    превращает простейший запрос в распределённый.
    """

    def one(conn: Connection, shard_id: int) -> Optional[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {ORDER_COLUMNS} FROM orders o WHERE o.id = %s", (order_id,))
            row = cur.fetchone()
        if row is not None:
            row["shard"] = shard_id
        return row

    outcome = scatter(one)
    found = [r["data"] for r in outcome["results"] if r["data"] is not None]
    return {
        "order": found[0] if found else None,
        "shards_queried": outcome["shards_queried"],
        "partial": outcome["partial"],
        "failed": outcome["failed"],
        "total_ms": outcome["total_ms"],
    }


def routing_preview(key: object) -> Dict[str, Any]:
    """Куда router отправит этот ключ — и по какой стратегии."""
    from app.config import settings
    from app.sharding.router import ConsistentHashRouter, ModuloRouter, hash_key

    ids = shard_ids()
    modulo = ModuloRouter(ids)
    ring = ConsistentHashRouter(ids, settings.shard_virtual_nodes)
    return {
        "shard_key": key,
        "hash": hash_key(key),
        "shard_count": shard_count(),
        "active_strategy": settings.shard_strategy,
        "shard": route(key),
        "by_strategy": {"modulo": modulo.route(key), "consistent": ring.route(key)},
        "available_shards": available_shards(),
    }
