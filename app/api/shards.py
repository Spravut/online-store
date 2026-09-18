"""HTTP-эндпоинты поверх шардированных данных (лабораторные №5 и №6).

Разделены намеренно: по URL сразу видно, какой запрос обслуживается одним
шардом, а какой превращается в scatter-gather.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.sharding import pools, queries

router = APIRouter(prefix="/api/shards", tags=["sharding"])


def _require_sharding() -> None:
    if not pools.sharding_enabled():
        raise HTTPException(status_code=503, detail="Шардирование выключено: SHARD_URLS пуст")


@router.get("/", summary="Конфигурация шардов и router")
def shards_overview():
    _require_sharding()
    return {
        "shard_count": pools.shard_count(),
        "strategy": settings.shard_strategy,
        "virtual_nodes": settings.shard_virtual_nodes,
        # Живая проверка, а не просто "пул открыт": шард могли уронить
        # уже после старта приложения.
        "health": {str(k): v for k, v in pools.probe_shards().items()},
    }


@router.get("/stats", summary="Распределение заказов по шардам")
def stats():
    _require_sharding()
    return queries.shard_stats()


@router.get("/route/{user_id}", summary="Куда router отправит этот shard key")
def route(user_id: int):
    _require_sharding()
    return queries.routing_preview(user_id)


# ----------------------------------------------------------- single-shard
@router.get("/users/{user_id}/orders", summary="Заказы пользователя (single-shard)")
def user_orders(user_id: int, limit: int = Query(50, le=500), offset: int = 0):
    _require_sharding()
    return queries.user_orders(user_id, limit, offset)


@router.get("/users/{user_id}/stats", summary="Агрегация по пользователю (single-shard)")
def user_stats(user_id: int):
    _require_sharding()
    return queries.user_stats(user_id)


@router.get(
    "/users/{user_id}/orders/{order_id}/items",
    summary="Позиции заказа: локальный JOIN внутри шарда",
)
def user_order_items(user_id: int, order_id: int):
    _require_sharding()
    return queries.user_order_with_items(user_id, order_id)


# ------------------------------------------------------------- distributed
@router.get("/orders/count", summary="COUNT(*) по всем шардам (scatter-gather)")
def orders_count(status: Optional[str] = None):
    _require_sharding()
    return queries.all_orders_count(status)


@router.get("/orders/revenue-by-status", summary="GROUP BY поверх всех шардов")
def revenue_by_status():
    _require_sharding()
    return queries.revenue_by_status()


@router.get("/orders/recent", summary="ORDER BY ... LIMIT поверх всех шардов")
def recent(limit: int = Query(100, le=1000)):
    _require_sharding()
    return queries.recent_orders(limit)


@router.get("/orders/recent-with-users", summary="Cross-shard JOIN: orders + users")
def recent_with_users(limit: int = Query(20, le=200)):
    _require_sharding()
    return queries.recent_orders_with_users(limit)


@router.get("/orders/by-id/{order_id}", summary="Поиск по id — не shard key, идём во все шарды")
def order_by_id(order_id: int):
    _require_sharding()
    return queries.find_order_by_id(order_id)
