"""CLI для работы с шардами (лабораторные №5 и №6).

    docker compose exec backend python -m scripts.shard_admin <команда>

Команды:

    init                 применить migrations_shard/*.sql на каждом шарде
    load  [--limit N]    разложить заказы из основной базы по шардам
    stats                сколько записей осело на каждом шарде
    rebalance            3 shards -> 4 shards: сколько данных переедет
    route  <user_id>     куда router отправит конкретный ключ
    demo                 запросы из лабораторной №6 с замерами
    truncate             очистить шарды (перед повторной загрузкой)

Шарды берутся из SHARD_URLS. Чтобы в команде участвовал и четвёртый шард,
достаточно передать список явно:

    --shards postgresql://...shard0...,...,postgresql://...shard3...
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.sharding.router import ConsistentHashRouter, ModuloRouter

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations_shard"


# ------------------------------------------------------------------ helpers
def resolve_shard_urls(explicit: str | None) -> List[str]:
    raw = explicit or settings.shard_urls
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    if not urls:
        sys.exit("SHARD_URLS пуст: нечего шардировать")
    return urls


def main_dsn() -> str:
    return settings.database_url


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def routers_for(n: int) -> Dict[str, object]:
    ids = list(range(n))
    return {
        "modulo": ModuloRouter(ids),
        "consistent": ConsistentHashRouter(ids, settings.shard_virtual_nodes),
    }


# --------------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> None:
    urls = resolve_shard_urls(args.shards)
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        sys.exit(f"нет файлов в {MIGRATIONS_DIR}")

    for shard_id, url in enumerate(urls):
        with connect(url) as conn:
            for path in files:
                conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                """
                INSERT INTO shard_info (shard_id, strategy, shard_count)
                VALUES (%s, %s, %s)
                ON CONFLICT (shard_id) DO UPDATE
                    SET strategy = EXCLUDED.strategy,
                        shard_count = EXCLUDED.shard_count,
                        loaded_at = now()
                """,
                (shard_id, settings.shard_strategy, len(urls)),
            )
        print(f"shard {shard_id}: схема применена ({', '.join(f.name for f in files)})")


def cmd_truncate(args: argparse.Namespace) -> None:
    urls = resolve_shard_urls(args.shards)
    for shard_id, url in enumerate(urls):
        with connect(url) as conn:
            conn.execute("TRUNCATE order_items, orders")
        print(f"shard {shard_id}: очищен")


# --------------------------------------------------------------------- load
ORDER_COLS = "id, user_id, status, total_amount, created_at, updated_at"
ITEM_COLS = "id, order_id, user_id, product_id, quantity, price_at_purchase"


def cmd_load(args: argparse.Namespace) -> None:
    """Разложить заказы из основной базы по шардам.

    Каждая строка адресуется router'ом по user_id. Позиции заказа едут на
    тот же шард: им проставляется тот же shard key.
    """
    urls = resolve_shard_urls(args.shards)
    router = routers_for(len(urls))[args.strategy]
    print(f"стратегия: {args.strategy}, шардов: {len(urls)}, лимит: {args.limit}")

    shard_conns = [connect(url) for url in urls]
    copiers_sql_orders = f"COPY orders ({ORDER_COLS}) FROM STDIN"
    copiers_sql_items = f"COPY order_items ({ITEM_COLS}) FROM STDIN"

    src = connect(main_dsn())
    started = time.perf_counter()
    loaded_orders = [0] * len(urls)
    loaded_items = [0] * len(urls)
    batch_size = args.batch
    last_id = 0
    remaining = args.limit

    try:
        while remaining > 0:
            take = min(batch_size, remaining)
            with src.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {ORDER_COLS}
                    FROM orders
                    WHERE id > %s
                    ORDER BY id
                    LIMIT %s
                    """,
                    (last_id, take),
                )
                orders = cur.fetchall()
            if not orders:
                break

            last_id = orders[-1]["id"]
            remaining -= len(orders)

            # Раскладываем пачку по шардам и заливаем COPY — по одному
            # потоку на шард вместо построчных INSERT.
            buckets: Dict[int, List[dict]] = {}
            owner: Dict[int, int] = {}
            for row in orders:
                shard_id = router.route(row["user_id"])
                buckets.setdefault(shard_id, []).append(row)
                owner[row["id"]] = shard_id

            for shard_id, rows in buckets.items():
                with shard_conns[shard_id].cursor() as cur, cur.copy(copiers_sql_orders) as cp:
                    for row in rows:
                        cp.write_row(tuple(row[c] for c in ORDER_COLS.split(", ")))
                loaded_orders[shard_id] += len(rows)

            order_ids = list(owner)
            with src.cursor() as cur:
                cur.execute(
                    """
                    SELECT oi.id, oi.order_id, o.user_id, oi.product_id,
                           oi.quantity, oi.price_at_purchase
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE oi.order_id = ANY(%s)
                    """,
                    (order_ids,),
                )
                items = cur.fetchall()

            item_buckets: Dict[int, List[dict]] = {}
            for row in items:
                item_buckets.setdefault(owner[row["order_id"]], []).append(row)

            for shard_id, rows in item_buckets.items():
                with shard_conns[shard_id].cursor() as cur, cur.copy(copiers_sql_items) as cp:
                    for row in rows:
                        cp.write_row(tuple(row[c] for c in ITEM_COLS.split(", ")))
                loaded_items[shard_id] += len(rows)

            done = args.limit - remaining
            print(f"  загружено заказов: {done}", end="\r", flush=True)
    finally:
        src.close()
        for conn in shard_conns:
            conn.close()

    elapsed = time.perf_counter() - started
    print()
    total = sum(loaded_orders)
    for shard_id in range(len(urls)):
        share = loaded_orders[shard_id] * 100 / total if total else 0
        print(
            f"Shard {shard_id} -> {loaded_orders[shard_id]:>7} заказов "
            f"({share:5.2f} %), позиций: {loaded_items[shard_id]}"
        )
    print(f"Итого: {total} заказов, {sum(loaded_items)} позиций за {elapsed:.1f} с")


# -------------------------------------------------------------------- stats
def cmd_stats(args: argparse.Namespace) -> None:
    urls = resolve_shard_urls(args.shards)
    rows = []
    for shard_id, url in enumerate(urls):
        try:
            with connect(url) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT (SELECT COUNT(*) FROM orders)                AS orders,
                           (SELECT COUNT(DISTINCT user_id) FROM orders) AS users,
                           (SELECT COUNT(*) FROM order_items)           AS items,
                           (SELECT COALESCE(SUM(total_amount), 0) FROM orders) AS revenue
                    """
                )
                rows.append((shard_id, cur.fetchone()))
        except Exception as exc:  # noqa: BLE001
            print(f"Shard {shard_id}: НЕДОСТУПЕН ({exc})")

    total = sum(r["orders"] for _, r in rows)
    print(f"{'shard':>5} {'orders':>10} {'share':>8} {'users':>8} {'items':>10} {'revenue':>16}")
    for shard_id, r in rows:
        share = r["orders"] * 100 / total if total else 0
        print(
            f"{shard_id:>5} {r['orders']:>10} {share:>7.2f}% {r['users']:>8} "
            f"{r['items']:>10} {float(r['revenue']):>16.2f}"
        )
    print(f"{'ИТОГО':>5} {total:>10}")

    if total and len(rows) > 1:
        counts = [r["orders"] for _, r in rows]
        spread = (max(counts) - min(counts)) * 100 / (total / len(counts))
        print(f"Перекос между самым большим и самым маленьким шардом: {spread:.2f} % от среднего")


# ---------------------------------------------------------------- rebalance
def _key_weights(limit: int) -> List[Tuple[int, int]]:
    """(user_id, сколько у него заказов) по тому же срезу, что и загружали."""
    with connect(main_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, COUNT(*) AS n
            FROM (SELECT user_id FROM orders ORDER BY id LIMIT %s) AS sample
            GROUP BY user_id
            """,
            (limit,),
        )
        return [(row["user_id"], row["n"]) for row in cur.fetchall()]


def _distribution(router, weights: Sequence[Tuple[int, int]], n: int) -> List[int]:
    buckets = [0] * n
    for key, count in weights:
        buckets[router.route(key)] += count
    return buckets


def cmd_rebalance(args: argparse.Namespace) -> None:
    """Задания 5 и 7: сколько записей меняет шард при N -> N+1."""
    weights = _key_weights(args.limit)
    total_rows = sum(n for _, n in weights)
    print(f"ключей (user_id): {len(weights)}, строк (orders): {total_rows}")
    print(f"переход: {args.frm} shards -> {args.to} shards\n")

    summary = []
    for name in ("modulo", "consistent"):
        before = routers_for(args.frm)[name]
        after = routers_for(args.to)[name]

        moved_rows = 0
        moved_keys = 0
        for key, count in weights:
            if before.route(key) != after.route(key):
                moved_rows += count
                moved_keys += 1

        dist_before = _distribution(before, weights, args.frm)
        dist_after = _distribution(after, weights, args.to)

        label = "hash(key) % N" if name == "modulo" else "Consistent Hashing"
        print(f"--- {label} ---")
        print(f"  было:  {['%d (%.2f%%)' % (v, v * 100 / total_rows) for v in dist_before]}")
        print(f"  стало: {['%d (%.2f%%)' % (v, v * 100 / total_rows) for v in dist_after]}")
        print(f"  переехало ключей: {moved_keys} из {len(weights)} "
              f"({moved_keys * 100 / len(weights):.2f} %)")
        print(f"  переехало строк:  {moved_rows} из {total_rows} "
              f"({moved_rows * 100 / total_rows:.2f} %)")
        print(f"  осталось на месте: {total_rows - moved_rows} "
              f"({(total_rows - moved_rows) * 100 / total_rows:.2f} %)\n")
        summary.append((label, moved_rows * 100 / total_rows))

    print(f"{'':<22}{'Перемещено'}")
    for label, pct in summary:
        print(f"{label:<22}{pct:.2f} %")
    print(f"\nТеоретический минимум при {args.frm} -> {args.to}: "
          f"{100 / args.to:.2f} % (доля нового шарда)")


# -------------------------------------------------------------------- route
def cmd_route(args: argparse.Namespace) -> None:
    urls = resolve_shard_urls(args.shards)
    n = len(urls)
    routers = routers_for(n)
    from app.sharding.router import hash_key

    print(f"shard key: {args.key}")
    print(f"hash:      {hash_key(args.key)}")
    print(f"шардов:    {n}")
    for name, router in routers.items():
        print(f"  {name:<12} -> shard {router.route(args.key)}")


# --------------------------------------------------------------------- demo
def cmd_demo(args: argparse.Namespace) -> None:
    """Запросы из лабораторной №6 с замером времени и числа опрошенных шардов."""
    from app.db import close_pool, open_pool
    from app.sharding import pools, queries

    if not pools.sharding_enabled():
        sys.exit("SHARD_URLS пуст")
    pools.open_shard_pools()
    # Основная база нужна для cross-shard JOIN: users не шардированы.
    open_pool()

    with connect(main_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id FROM orders ORDER BY id LIMIT 1")
        user_id = cur.fetchone()["user_id"]

    def show(title: str, payload: dict, keys: Sequence[str]) -> None:
        print(f"\n### {title}")
        for key in keys:
            if key in payload:
                print(f"  {key}: {payload[key]}")

    print(f"пример пользователя: user_id = {user_id}")

    show(
        "2. Single-shard query: заказы пользователя",
        queries.user_orders(user_id, limit=5),
        ("shard", "shards_queried", "total_ms"),
    )
    show(
        "3. Агрегация COUNT(*) по всем шардам",
        queries.all_orders_count(),
        ("per_shard", "total", "shards_queried", "total_ms", "slowest_shard_ms"),
    )
    show(
        "3. GROUP BY status по всем шардам",
        queries.revenue_by_status(),
        ("rows", "shards_queried", "total_ms"),
    )
    local_join = queries.user_order_with_items(
        user_id, queries.user_orders(user_id, limit=1)["orders"][0]["id"]
    )
    local_join["items_count"] = len(local_join["items"])
    show(
        "4. Локальный JOIN orders + order_items внутри шарда",
        local_join,
        ("shard", "items_count"),
    )
    show(
        "4. Cross-shard JOIN orders + users (склейка в приложении)",
        queries.recent_orders_with_users(limit=5),
        ("join_performed_in", "shard_roundtrips", "extra_roundtrips", "user_ids_transferred"),
    )
    show(
        "5. ORDER BY created_at DESC LIMIT 100 поверх шардов",
        queries.recent_orders(limit=100),
        ("rows_fetched", "rows_returned", "overhead_rows", "shards_queried", "total_ms"),
    )
    show(
        "Поиск по id (не shard key) — распределённый запрос",
        queries.find_order_by_id(1),
        ("order", "shards_queried", "total_ms"),
    )
    pools.close_shard_pools()
    close_pool()


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shards", help="список URL шардов через запятую (по умолчанию SHARD_URLS)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="применить схему на всех шардах").set_defaults(func=cmd_init)
    sub.add_parser("truncate", help="очистить шарды").set_defaults(func=cmd_truncate)
    sub.add_parser("stats", help="распределение данных по шардам").set_defaults(func=cmd_stats)

    load = sub.add_parser("load", help="разложить заказы по шардам")
    load.add_argument("--limit", type=int, default=100_000)
    load.add_argument("--batch", type=int, default=5_000)
    load.add_argument("--strategy", choices=("modulo", "consistent"), default=settings.shard_strategy)
    load.set_defaults(func=cmd_load)

    reb = sub.add_parser("rebalance", help="сколько данных переедет при N -> N+1")
    reb.add_argument("--limit", type=int, default=100_000)
    reb.add_argument("--frm", type=int, default=3, help="сколько шардов было")
    reb.add_argument("--to", type=int, default=4, help="сколько стало")
    reb.set_defaults(func=cmd_rebalance)

    rt = sub.add_parser("route", help="куда уедет конкретный ключ")
    rt.add_argument("key")
    rt.set_defaults(func=cmd_route)

    sub.add_parser("demo", help="запросы лабораторной №6").set_defaults(func=cmd_demo)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
