-- Небольшой демонстрационный набор данных, чтобы API можно было потрогать
-- сразу после `docker compose up`.
-- Массовая генерация (сотни тысяч записей) живёт отдельно: scripts/generate_data.py
--
-- Важно: подзапросы ниже всегда ссылаются на строку внешнего запроса
-- (через g или o.id). Некоррелированный подзапрос PostgreSQL вычислил бы
-- ОДИН раз, и все заказы получились бы одинаковыми.

INSERT INTO categories (name, slug) VALUES
    ('Смартфоны',   'smartphones'),
    ('Ноутбуки',    'laptops'),
    ('Наушники',    'headphones'),
    ('Клавиатуры',  'keyboards'),
    ('Мониторы',    'monitors');

INSERT INTO products (category_id, name, description, price, stock, created_at)
SELECT c.id,
       c.name || ' модель ' || g,
       'Демонстрационный товар в категории «' || c.name || '»',
       round((5000 + ((g * 7919 + c.id * 104729) % 90000))::numeric, 2),
       ((g * 37 + c.id * 11) % 200)::int,
       now() - ((g * 13 + c.id * 29) % 365) * interval '1 day'
FROM categories c
CROSS JOIN generate_series(1, 8) AS g;

INSERT INTO users (email, full_name, city, created_at)
SELECT 'user' || g || '@example.com',
       'Пользователь ' || g,
       (ARRAY['Москва', 'Санкт-Петербург', 'Казань', 'Новосибирск', 'Екатеринбург'])[1 + (g % 5)],
       now() - ((g * 17) % 365) * interval '1 day'
FROM generate_series(1, 50) AS g;

INSERT INTO orders (user_id, status, created_at, updated_at)
SELECT u.id,
       (ARRAY['NEW', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED'])[1 + (g % 5)],
       ts.value,
       ts.value
FROM generate_series(1, 300) AS g
CROSS JOIN LATERAL (
    SELECT now() - ((g * 11) % 180) * interval '1 day'
                 - ((g * 3607) % 86400) * interval '1 second' AS value
) AS ts
CROSS JOIN LATERAL (
    -- псевдослучайный, но воспроизводимый выбор покупателя для заказа g
    SELECT id FROM users ORDER BY md5(id::text || g::text) LIMIT 1
) AS u;

INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
SELECT o.id, p.id, 1 + (o.id % 3), p.price
FROM orders o
CROSS JOIN LATERAL (
    SELECT id, price
    FROM products
    ORDER BY md5(id::text || o.id::text)
    LIMIT 1 + (o.id % 3)
) AS p;

UPDATE orders o
SET total_amount = t.total
FROM (
    SELECT order_id, SUM(quantity * price_at_purchase) AS total
    FROM order_items
    GROUP BY order_id
) AS t
WHERE o.id = t.order_id;

INSERT INTO reviews (product_id, user_id, rating, comment, created_at)
SELECT p.id, u.id,
       1 + (g % 5),
       'Демонстрационный отзыв №' || g,
       now() - ((g * 7) % 120) * interval '1 day'
FROM generate_series(1, 200) AS g
CROSS JOIN LATERAL (
    SELECT id FROM products ORDER BY md5(id::text || g::text)      LIMIT 1
) AS p
CROSS JOIN LATERAL (
    SELECT id FROM users    ORDER BY md5(id::text || (g * 3)::text) LIMIT 1
) AS u
ON CONFLICT (product_id, user_id) DO NOTHING;
