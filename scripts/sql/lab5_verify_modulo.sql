-- Задание 5: сколько данных переедет при hash(key) % 3 -> hash(key) % 4
-- Выполнять на shop-primary (порт 5434), база shop.
WITH sample AS (
    -- тот же срез, который загружался в шарды
    SELECT user_id FROM orders ORDER BY id LIMIT 100000
),
keys AS (
    SELECT user_id,
           count(*)                  AS orders,
           hashtext(user_id::text)   AS h
    FROM sample
    GROUP BY user_id
),
routed AS (
    SELECT orders,
           -- hashtext возвращает ЗНАКОВЫЙ int4, поэтому просто % 3 даёт
           -- отрицательные номера шардов. Отсюда двойной остаток.
           ((h % 3) + 3) % 3 AS shard_was,
           ((h % 4) + 4) % 4 AS shard_now
    FROM keys
)
SELECT sum(orders)                                             AS всего_заказов,
       count(*)                                                AS всего_ключей,
       sum(orders) FILTER (WHERE shard_was <> shard_now)        AS переехало,
       sum(orders) FILTER (WHERE shard_was =  shard_now)        AS осталось,
       round(100.0 * sum(orders) FILTER (WHERE shard_was <> shard_now)
             / sum(orders), 2)                                  AS процент_переезда
FROM routed;
