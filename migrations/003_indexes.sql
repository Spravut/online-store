-- Индексы, добавленные по результатам лабораторной работы №1.
-- Каждый индекс подтверждён измерением EXPLAIN ANALYZE до и после,
-- подробности и планы выполнения: docs/lab-01-indexes.md
--
-- Namely:
--   GET /api/users/{id}/orders        Seq Scan 50.6 мс -> Index Scan 0.28 мс
--   GET /api/orders?status=&from=&to= Seq Scan 52.8 мс -> Index Scan 0.32 мс
--   GET /api/orders (сортировка по умолчанию created_at DESC)
--   аналитика по order_items

-- Заказы пользователя, отсортированные по дате: WHERE user_id = ? ORDER BY created_at DESC.
-- Порядок колонок важен: сначала колонка равенства, затем колонка сортировки.
CREATE INDEX idx_orders_user_id_created_at ON orders (user_id, created_at DESC);

-- Лента заказов с фильтром по статусу и диапазоном дат:
-- WHERE status = ? AND created_at >= ? AND created_at < ? ORDER BY created_at DESC.
CREATE INDEX idx_orders_status_created_at ON orders (status, created_at DESC);

-- Лента заказов без фильтра по статусу: ORDER BY created_at DESC LIMIT ...
-- и диапазонные запросы по дате.
CREATE INDEX idx_orders_created_at ON orders (created_at DESC);

-- Внешний ключ order_items.product_id не имел индекса: он нужен аналитике
-- (JOIN order_items -> products) и ускоряет проверку ссылок при удалении товара.
-- Обратное направление (order_id) уже покрыто UNIQUE (order_id, product_id).
CREATE INDEX idx_order_items_product_id ON order_items (product_id);
