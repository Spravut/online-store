-- Партиционирование основной растущей таблицы orders по месяцам (лабораторная №3).
--
-- Ключ: created_at. Стратегия: RANGE. Гранулярность: месяц.
-- Обоснование и замеры: docs/lab-03-partitioning.md
--
-- Миграция переносит данные в новую партиционированную таблицу, поэтому на
-- большом объёме выполняется несколько минут. Для учебного проекта это
-- приемлемо; в production такую операцию делают с CONCURRENTLY-приёмами
-- или через логическую репликацию.

-- ---------------------------------------------------------------- 1. Ограничения
-- Первичный ключ партиционированной таблицы обязан содержать ключ
-- партиционирования, то есть становится (id, created_at). Внешний ключ
-- order_items.order_id ссылался на orders(id) — такой цели больше не
-- существует, поэтому ограничение снимается.
-- Целостность на уровне приложения обеспечивается тем, что позиции всегда
-- создаются вместе с заказом в одной транзакции (app/services/orders.py).
ALTER TABLE order_items DROP CONSTRAINT order_items_order_id_fkey;

-- ---------------------------------------------------------------- 2. Старая таблица
ALTER TABLE orders RENAME TO orders_unpartitioned;

-- Освобождаем имена индексов для новой таблицы.
DROP INDEX IF EXISTS idx_orders_user_id_created_at;
DROP INDEX IF EXISTS idx_orders_status_created_at;
DROP INDEX IF EXISTS idx_orders_created_at;
ALTER INDEX orders_pkey RENAME TO orders_unpartitioned_pkey;

-- Последовательность переживает пересоздание таблицы, поэтому нумерация
-- заказов продолжится с того же места.
ALTER SEQUENCE orders_id_seq OWNED BY NONE;

-- ---------------------------------------------------------------- 3. Новая таблица
CREATE TABLE orders (
    id           BIGINT         NOT NULL DEFAULT nextval('orders_id_seq'),
    user_id      BIGINT         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    status       TEXT           NOT NULL DEFAULT 'NEW'
                     CHECK (status IN ('NEW', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
    total_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- ---------------------------------------------------------------- 4. Партиции
-- Помесячно: весь диапазон существующих данных плюс полгода вперёд.
-- Дальше партиции создаёт ночной job (scripts/partition_job.py create).
DO $$
DECLARE
    start_month DATE;
    end_month   DATE;
    m           DATE;
BEGIN
    SELECT date_trunc('month', COALESCE(MIN(created_at), now()))::date,
           date_trunc('month', COALESCE(MAX(created_at), now()))::date + INTERVAL '6 months'
    INTO start_month, end_month
    FROM orders_unpartitioned;

    FOR m IN SELECT generate_series(start_month, end_month, '1 month')::date LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF orders FOR VALUES FROM (%L) TO (%L)',
            'orders_' || to_char(m, 'YYYY_MM'),
            m,
            (m + INTERVAL '1 month')::date
        );
    END LOOP;
END $$;

-- Страховка: если job не сработает и запись выйдет за горизонт, INSERT не упадёт,
-- а попадёт сюда. Наличие строк в orders_default — сигнал проблемы, его
-- контролирует PartitionHealthCheck.
CREATE TABLE orders_default PARTITION OF orders DEFAULT;

-- ---------------------------------------------------------------- 5. Перенос данных
INSERT INTO orders (id, user_id, status, total_amount, created_at, updated_at)
SELECT id, user_id, status, total_amount, created_at, updated_at
FROM orders_unpartitioned;

-- ---------------------------------------------------------------- 6. Индексы
-- Индексы объявляются на родительской таблице: PostgreSQL создаёт их в каждой
-- существующей партиции и автоматически повторит в каждой будущей.
CREATE INDEX idx_orders_user_id_created_at ON orders (user_id, created_at DESC);
CREATE INDEX idx_orders_status_created_at  ON orders (status, created_at DESC);
CREATE INDEX idx_orders_created_at         ON orders (created_at DESC);

-- ---------------------------------------------------------------- 7. Уборка
DROP TABLE orders_unpartitioned;
ALTER SEQUENCE orders_id_seq OWNED BY orders.id;

ANALYZE orders;
