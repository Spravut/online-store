-- Задание 7: то же расширение 3 -> 4 шарда, но через Consistent Hashing.
-- Выполнять на shop-primary (порт 5434), база shop.
WITH sample AS (
    SELECT user_id FROM orders ORDER BY id LIMIT 100000
),
keys AS (
    SELECT user_id, count(*) AS orders, hashtext(user_id::text) AS h
    FROM sample GROUP BY user_id
),
-- Кольцо: каждый шард ставит 150 точек с именами shard-0#0, shard-0#1, ...
ring3 AS (
    SELECT s AS shard, hashtext('shard-' || s || '#' || v) AS point
    FROM generate_series(0, 2) s, generate_series(0, 149) v
),
ring4 AS (
    SELECT s AS shard, hashtext('shard-' || s || '#' || v) AS point
    FROM generate_series(0, 3) s, generate_series(0, 149) v
),
routed AS (
    SELECT k.orders,
           -- ближайшая точка по часовой стрелке; если таких нет —
           -- кольцо замыкается на самую первую точку
           COALESCE(
               (SELECT r.shard FROM ring3 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
               (SELECT r.shard FROM ring3 r ORDER BY r.point LIMIT 1)
           ) AS shard_was,
           COALESCE(
               (SELECT r.shard FROM ring4 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
               (SELECT r.shard FROM ring4 r ORDER BY r.point LIMIT 1)
           ) AS shard_now
    FROM keys k
)
SELECT sum(orders)                                       AS всего_заказов,
       count(*)                                          AS всего_ключей,
       sum(orders) FILTER (WHERE shard_was <> shard_now)  AS переехало,
       sum(orders) FILTER (WHERE shard_was =  shard_now)  AS осталось,
       round(100.0 * sum(orders) FILTER (WHERE shard_was <> shard_now)
             / sum(orders), 2)                            AS процент_переезда
FROM routed;
