-- Схема одного шарда (лабораторная №5).
--
-- Отличия от основной базы (migrations/001_init.sql) — прямое следствие
-- того, что шарды независимы:
--
-- 1. Нет таблиц users, products, categories. Они не шардируются: заказы
--    распределены по user_id, а сам справочник пользователей остаётся в
--    основной базе. Поэтому FK на users здесь физически невозможен —
--    чужая таблица лежит в другом PostgreSQL.
-- 2. id заказа НЕ BIGSERIAL: значения приезжают из основной базы и
--    должны совпадать с ней. Своя последовательность на каждом шарде
--    рано или поздно выдала бы один и тот же id на разных шардах.
-- 3. order_items несёт денормализованный user_id — тот же shard key,
--    что и у заказа. Это гарантирует, что позиции лежат на том же
--    шарде, и JOIN orders + order_items остаётся локальным.

CREATE TABLE IF NOT EXISTS orders (
    id           BIGINT         NOT NULL,
    user_id      BIGINT         NOT NULL,          -- shard key
    status       TEXT           NOT NULL DEFAULT 'NEW'
                     CHECK (status IN ('NEW', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
    total_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

-- Главный индекс шарда: почти каждый single-shard запрос идёт по user_id.
CREATE INDEX IF NOT EXISTS idx_shard_orders_user_created
    ON orders (user_id, created_at DESC);

-- Для распределённого ORDER BY created_at DESC LIMIT N: каждый шард
-- должен уметь отдать свой top-N быстро, иначе scatter-gather упрётся
-- в Seq Scan на каждом узле.
CREATE INDEX IF NOT EXISTS idx_shard_orders_created
    ON orders (created_at DESC);

CREATE TABLE IF NOT EXISTS order_items (
    id                BIGINT         NOT NULL,
    order_id          BIGINT         NOT NULL,
    user_id           BIGINT         NOT NULL,     -- тот же shard key, что у заказа
    product_id        BIGINT         NOT NULL,
    quantity          INTEGER        NOT NULL CHECK (quantity > 0),
    price_at_purchase NUMERIC(12, 2) NOT NULL CHECK (price_at_purchase >= 0),
    PRIMARY KEY (id),
    -- FK работает: обе таблицы колокированы на одном шарде.
    FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_shard_order_items_order
    ON order_items (order_id);

-- Служебная таблица: чем этот шард себя считает. Удобно при отладке,
-- чтобы не перепутать порты и убедиться, что router попал куда надо.
CREATE TABLE IF NOT EXISTS shard_info (
    shard_id    INTEGER     PRIMARY KEY,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy    TEXT,
    shard_count INTEGER
);
