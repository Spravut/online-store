-- Песочница для лабораторной работы №3 (части 1-11).
--
-- Учебные таблицы создаются в ОТДЕЛЬНОЙ схеме lab3, чтобы не конфликтовать
-- с доменными таблицами магазина (у него есть своя products) и не попадать
-- в рабочее развёртывание сервиса — поэтому это скрипт, а не миграция.
--
-- Запуск:
--   docker compose exec -T postgres psql -U shop -d shop -f - < scripts/lab3_sandbox.sql

DROP SCHEMA IF EXISTS lab3 CASCADE;
CREATE SCHEMA lab3;
SET search_path TO lab3;

-- ============================================================ Часть 1. RANGE по дате
CREATE TABLE events (
    id         BIGSERIAL   NOT NULL,
    user_id    BIGINT      NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload    TEXT,
    created_at TIMESTAMP   NOT NULL
) PARTITION BY RANGE (created_at);

CREATE TABLE events_2026_09_09 PARTITION OF events
    FOR VALUES FROM ('2026-09-09') TO ('2026-09-10');
CREATE TABLE events_2026_09_10 PARTITION OF events
    FOR VALUES FROM ('2026-09-10') TO ('2026-09-11');
CREATE TABLE events_2026_09_11 PARTITION OF events
    FOR VALUES FROM ('2026-09-11') TO ('2026-09-12');

INSERT INTO events (user_id, event_type, payload, created_at)
SELECT (random() * 100000)::bigint,
       (ARRAY['click', 'view', 'purchase', 'login'])[1 + floor(random() * 4)::int],
       '{}',
       '2026-09-09'::timestamp + (random() * 3) * INTERVAL '1 day'
FROM generate_series(1, 900000);

ANALYZE events;

-- ============================================================ Часть 3. RANGE по числу
CREATE TABLE products (
    id    BIGINT  NOT NULL,
    name  TEXT    NOT NULL,
    price NUMERIC NOT NULL
) PARTITION BY RANGE (price);

CREATE TABLE products_cheap     PARTITION OF products FOR VALUES FROM (0) TO (100);
CREATE TABLE products_medium    PARTITION OF products FOR VALUES FROM (100) TO (1000);
CREATE TABLE products_expensive PARTITION OF products FOR VALUES FROM (1000) TO (MAXVALUE);

INSERT INTO products (id, name, price)
SELECT g, 'Товар ' || g, round((random() * 5000)::numeric, 2)
FROM generate_series(1, 100000) g;

ANALYZE products;

-- ============================================================ Часть 4-5. LIST
CREATE TABLE customers (
    id            BIGINT      NOT NULL,
    name          TEXT        NOT NULL,
    customer_type VARCHAR(30) NOT NULL
) PARTITION BY LIST (customer_type);

CREATE TABLE customers_b2c        PARTITION OF customers FOR VALUES IN ('B2C');
CREATE TABLE customers_b2b        PARTITION OF customers FOR VALUES IN ('B2B');
CREATE TABLE customers_enterprise PARTITION OF customers FOR VALUES IN ('Enterprise');

INSERT INTO customers (id, name, customer_type)
SELECT g, 'Клиент ' || g,
       (ARRAY['B2C', 'B2C', 'B2C', 'B2B', 'Enterprise'])[1 + floor(random() * 5)::int]
FROM generate_series(1, 50000) g;

ANALYZE customers;

-- ============================================================ Часть 6. HASH
CREATE TABLE user_events (
    id         BIGINT      NOT NULL,
    user_id    BIGINT      NOT NULL,
    event_type VARCHAR(50),
    created_at TIMESTAMP   NOT NULL
) PARTITION BY HASH (user_id);

CREATE TABLE user_events_0 PARTITION OF user_events FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE user_events_1 PARTITION OF user_events FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE user_events_2 PARTITION OF user_events FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE user_events_3 PARTITION OF user_events FOR VALUES WITH (MODULUS 4, REMAINDER 3);

INSERT INTO user_events (id, user_id, event_type, created_at)
SELECT g, (random() * 100000)::bigint,
       (ARRAY['click', 'view', 'purchase', 'login'])[1 + floor(random() * 4)::int],
       NOW() - (random() * INTERVAL '365 days')
FROM generate_series(1, 1000000) g;

ANALYZE user_events;

SELECT 'sandbox ready' AS status;
