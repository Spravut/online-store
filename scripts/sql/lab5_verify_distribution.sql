-- Задание 4: как данные распределились по шардам (и что стало после
-- расширения до 4). Выполнять на shop-primary (порт 5434), база shop.
WITH sample AS (
    SELECT user_id FROM orders ORDER BY id LIMIT 100000
),
keys AS (
    SELECT user_id, count(*) AS orders, hashtext(user_id::text) AS h
    FROM sample GROUP BY user_id
),
ring3 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,2) s, generate_series(0,149) v),
ring4 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,3) s, generate_series(0,149) v),
routed AS (
    SELECT k.orders,
           ((h % 3) + 3) % 3 AS mod3,
           ((h % 4) + 4) % 4 AS mod4,
           COALESCE((SELECT r.shard FROM ring3 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                    (SELECT r.shard FROM ring3 r ORDER BY r.point LIMIT 1)) AS ring3,
           COALESCE((SELECT r.shard FROM ring4 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                    (SELECT r.shard FROM ring4 r ORDER BY r.point LIMIT 1)) AS ring4
    FROM keys k
),
unpivoted AS (
    SELECT 'hash % 3'           AS вариант, 1 AS ord, mod3  AS shard, orders FROM routed
    UNION ALL SELECT 'hash % 4', 2, mod4,  orders FROM routed
    UNION ALL SELECT 'ring, 3 шарда', 3, ring3, orders FROM routed
    UNION ALL SELECT 'ring, 4 шарда', 4, ring4, orders FROM routed
)
SELECT вариант,
       shard,
       sum(orders)                                              AS заказов,
       round(100.0 * sum(orders) / sum(sum(orders)) OVER (PARTITION BY вариант), 2) AS "доля_%"
FROM unpivoted
GROUP BY вариант, ord, shard
ORDER BY ord, shard;
