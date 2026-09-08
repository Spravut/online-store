"""Массовая генерация тестовых данных.

Данные генерируются на стороне PostgreSQL (generate_series + random),
поэтому миллион заказов создаётся за десятки секунд, а не за часы.

Примеры:
    python -m scripts.generate_data --users 1000 --products 500 --orders 20000
    python -m scripts.generate_data --users 100000 --products 5000 --orders 1000000 --reviews 200000

Внутри docker compose:
    docker compose exec backend python -m scripts.generate_data --orders 1000000
"""

import argparse
import logging
import time
from typing import List, Optional

import psycopg
from psycopg.rows import dict_row

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("generator")

CITIES = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Сочи", "Пермь"]
STATUSES = ["NEW", "PAID", "SHIPPED", "DELIVERED", "CANCELLED"]
DEFAULT_CATEGORIES = [
    ("Смартфоны", "smartphones"),
    ("Ноутбуки", "laptops"),
    ("Наушники", "headphones"),
    ("Клавиатуры", "keyboards"),
    ("Мониторы", "monitors"),
    ("Планшеты", "tablets"),
    ("Телевизоры", "tv"),
]


def scalar(conn: psycopg.Connection, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return list(row.values())[0] if row else None


def truncate_all(conn: psycopg.Connection) -> None:
    logger.info("очищаю таблицы данных")
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE order_items, orders, reviews, products, users, categories "
            "RESTART IDENTITY CASCADE"
        )


def ensure_categories(conn: psycopg.Connection) -> int:
    total = scalar(conn, "SELECT COUNT(*) AS c FROM categories")
    if total:
        return total

    logger.info("создаю базовые категории")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO categories (name, slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            DEFAULT_CATEGORIES,
        )
    return scalar(conn, "SELECT COUNT(*) AS c FROM categories")


def generate_users(conn: psycopg.Connection, count: int, batch: int) -> None:
    if count <= 0:
        return

    logger.info("генерирую %s пользователей", count)
    created = 0
    while created < count:
        chunk = min(batch, count - created)
        base = scalar(conn, "SELECT COALESCE(MAX(id), 0) AS m FROM users")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, full_name, city, created_at)
                SELECT 'user' || (%s + g) || '@example.com',
                       'Пользователь ' || (%s + g),
                       (%s::text[])[1 + floor(random() * %s)::int],
                       now() - (floor(random() * 730))::int * interval '1 day'
                FROM generate_series(1, %s) AS g
                """,
                (base, base, CITIES, len(CITIES), chunk),
            )
        created += chunk
        logger.info("  пользователей: %s / %s", created, count)


def generate_products(conn: psycopg.Connection, count: int, batch: int) -> None:
    if count <= 0:
        return

    ensure_categories(conn)
    logger.info("генерирую %s товаров", count)
    created = 0
    while created < count:
        chunk = min(batch, count - created)
        base = scalar(conn, "SELECT COALESCE(MAX(id), 0) AS m FROM products")
        categories_count = scalar(conn, "SELECT COUNT(*) AS c FROM categories")
        with conn.cursor() as cur:
            # random() в списке SELECT вычисляется для каждой строки generate_series,
            # поэтому категория и цена у товаров получаются разными.
            cur.execute(
                """
                INSERT INTO products (category_id, name, description, price, stock, created_at)
                SELECT c.id, d.name, d.description, d.price, d.stock, d.created_at
                FROM (
                    SELECT 'Товар ' || (%s + g)                                        AS name,
                           'Автоматически сгенерированный товар №' || (%s + g)         AS description,
                           round((random() * 99000 + 500)::numeric, 2)                 AS price,
                           floor(random() * 500)::int                                  AS stock,
                           now() - (floor(random() * 730))::int * interval '1 day'     AS created_at,
                           1 + floor(random() * %s)::bigint                            AS category_rn
                    FROM generate_series(1, %s) AS g
                ) AS d
                JOIN (
                    SELECT row_number() OVER (ORDER BY id) AS rn, id FROM categories
                ) AS c ON c.rn = d.category_rn
                """,
                (base, base, categories_count, chunk),
            )
        created += chunk
        logger.info("  товаров: %s / %s", created, count)


def _refresh_lookup(conn: psycopg.Connection, table: str, extra_columns: str = "") -> int:
    """Временная таблица «номер по порядку -> id», чтобы быстро брать случайную строку."""
    tmp = "tmp_" + table
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS " + tmp)
        cur.execute(
            """
            CREATE TEMP TABLE {tmp} AS
            SELECT row_number() OVER (ORDER BY id) AS rn, id{extra}
            FROM {table}
            """.format(tmp=tmp, extra=extra_columns, table=table)
        )
        cur.execute("CREATE UNIQUE INDEX ON {tmp} (rn)".format(tmp=tmp))
        cur.execute("ANALYZE " + tmp)
    return scalar(conn, "SELECT COUNT(*) AS c FROM " + tmp)


def generate_orders(
    conn: psycopg.Connection, count: int, max_items: int, batch: int, days: int
) -> None:
    if count <= 0:
        return

    users_count = _refresh_lookup(conn, "users")
    products_count = _refresh_lookup(conn, "products", extra_columns=", price")

    if not users_count or not products_count:
        raise SystemExit("Сначала нужно сгенерировать пользователей и товары")

    logger.info("генерирую %s заказов (до %s позиций в каждом)", count, max_items)
    created = 0
    while created < count:
        chunk = min(batch, count - created)
        started = time.perf_counter()
        last_order_id = scalar(conn, "SELECT COALESCE(MAX(id), 0) AS m FROM orders")

        with conn.cursor() as cur:
            # Все random() стоят в списке SELECT над generate_series -> считаются
            # для каждой строки. Случайный пользователь берётся джойном по rn.
            cur.execute(
                """
                INSERT INTO orders (user_id, status, total_amount, created_at, updated_at)
                SELECT u.id, d.status, 0, d.ts, d.ts
                FROM (
                    SELECT (%s::text[])[1 + floor(random() * %s)::int]                  AS status,
                           now() - (floor(random() * %s))::int * interval '1 day'
                                 - (floor(random() * 86400))::int * interval '1 second' AS ts,
                           1 + floor(random() * %s)::bigint                             AS user_rn
                    FROM generate_series(1, %s) AS g
                ) AS d
                JOIN tmp_users u ON u.rn = d.user_rn
                """,
                (STATUSES, len(STATUSES), days, users_count, chunk),
            )

            # Количество позиций зависит от o.id, поэтому у заказов оно разное.
            cur.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
                SELECT d.order_id, p.id, d.quantity, p.price
                FROM (
                    SELECT o.id                             AS order_id,
                           1 + floor(random() * 3)::int     AS quantity,
                           1 + floor(random() * %s)::bigint AS product_rn
                    FROM orders o
                    CROSS JOIN LATERAL generate_series(1, 1 + (o.id %% %s)::int) AS i
                    WHERE o.id > %s
                ) AS d
                JOIN tmp_products p ON p.rn = d.product_rn
                ON CONFLICT (order_id, product_id) DO NOTHING
                """,
                (products_count, max_items, last_order_id),
            )

            cur.execute(
                """
                UPDATE orders o
                SET total_amount = t.total
                FROM (
                    SELECT oi.order_id, SUM(oi.quantity * oi.price_at_purchase) AS total
                    FROM order_items oi
                    WHERE oi.order_id > %s
                    GROUP BY oi.order_id
                ) AS t
                WHERE o.id = t.order_id
                """,
                (last_order_id,),
            )

        created += chunk
        logger.info(
            "  заказов: %s / %s (%.1f сек на порцию)",
            created,
            count,
            time.perf_counter() - started,
        )


def generate_reviews(conn: psycopg.Connection, count: int, batch: int) -> None:
    if count <= 0:
        return

    users_count = _refresh_lookup(conn, "users")
    products_count = _refresh_lookup(conn, "products", extra_columns=", price")

    logger.info("генерирую %s отзывов", count)
    created = 0
    while created < count:
        chunk = min(batch, count - created)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reviews (product_id, user_id, rating, comment, created_at)
                SELECT p.id, u.id, d.rating, 'Сгенерированный отзыв', d.created_at
                FROM (
                    SELECT 1 + floor(random() * 5)::int                            AS rating,
                           now() - (floor(random() * 365))::int * interval '1 day' AS created_at,
                           1 + floor(random() * %s)::bigint                        AS product_rn,
                           1 + floor(random() * %s)::bigint                        AS user_rn
                    FROM generate_series(1, %s) AS g
                ) AS d
                JOIN tmp_products p ON p.rn = d.product_rn
                JOIN tmp_users    u ON u.rn = d.user_rn
                ON CONFLICT (product_id, user_id) DO NOTHING
                """,
                (products_count, users_count, chunk),
            )
        created += chunk
        logger.info("  отзывов: %s / %s", created, count)


def print_summary(conn: psycopg.Connection) -> None:
    logger.info("итого в базе:")
    for table in ("users", "categories", "products", "orders", "order_items", "reviews"):
        logger.info("  %-12s %s", table, scalar(conn, "SELECT COUNT(*) AS c FROM " + table))


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Генератор тестовых данных для shop API")
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--products", type=int, default=500)
    parser.add_argument("--orders", type=int, default=20000)
    parser.add_argument("--reviews", type=int, default=2000)
    parser.add_argument("--max-items", type=int, default=4, help="максимум позиций в заказе")
    parser.add_argument("--days", type=int, default=730, help="разброс created_at заказов в днях")
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--truncate", action="store_true", help="очистить таблицы перед генерацией")
    parser.add_argument("--dsn", default=settings.database_url)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    with psycopg.connect(args.dsn, row_factory=dict_row, autocommit=True) as conn:
        if args.truncate:
            truncate_all(conn)

        ensure_categories(conn)
        generate_users(conn, args.users, args.batch_size)
        generate_products(conn, args.products, args.batch_size)
        generate_orders(conn, args.orders, args.max_items, args.batch_size, args.days)
        generate_reviews(conn, args.reviews, args.batch_size)

        with conn.cursor() as cur:
            cur.execute("ANALYZE")

        print_summary(conn)

    logger.info("готово за %.1f сек", time.perf_counter() - started)


if __name__ == "__main__":
    main()
