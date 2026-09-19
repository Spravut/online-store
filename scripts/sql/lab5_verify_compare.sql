-- Сравнение двух стратегий шардирования при расширении 3 -> 4 шарда.
-- Считается прямо здесь, по реальным данным сервиса.
-- Выполнять на shop-primary (порт 5434), база shop.
WITH sample AS (
    -- тот же срез заказов, который загружался в шарды
    SELECT user_id FROM orders ORDER BY id LIMIT 100000
),
keys AS (
    SELECT user_id, count(*) AS orders, hashtext(user_id::text) AS h
    FROM sample GROUP BY user_id
),
-- ---------- стратегия 1: hash(key) % N ----------
modulo AS (
    SELECT orders,
           -- hashtext даёт ЗНАКОВЫЙ int4, поэтому двойной остаток:
           -- иначе получались бы отрицательные номера шардов
           ((h % 3) + 3) % 3 AS shard_was,
           ((h % 4) + 4) % 4 AS shard_now
    FROM keys
),
-- ---------- стратегия 2: Consistent Hashing ----------
-- Кольцо: каждый шард ставит 150 точек (shard-0#0, shard-0#1, ...)
ring3 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,2) s, generate_series(0,149) v),
ring4 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,3) s, generate_series(0,149) v),
consistent AS (
    SELECT k.orders,
           -- ближайшая точка по часовой стрелке,
           -- а если таких нет — кольцо замыкается на первую
           COALESCE((SELECT r.shard FROM ring3 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                    (SELECT r.shard FROM ring3 r ORDER BY r.point LIMIT 1)) AS shard_was,
           COALESCE((SELECT r.shard FROM ring4 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                    (SELECT r.shard FROM ring4 r ORDER BY r.point LIMIT 1)) AS shard_now
    FROM keys k
),
all_routes AS (
    SELECT 'hash(key) % N'      AS стратегия, 1 AS ord, * FROM modulo
    UNION ALL
    SELECT 'Consistent Hashing' AS стратегия, 2 AS ord, * FROM consistent
)
SELECT стратегия,
       sum(orders)                                AS всего,
       sum(orders) FILTER (WHERE shard_was <> shard_now)      AS переехало,
       sum(orders) FILTER (WHERE shard_was =  shard_now)      AS осталось,
       round(100.0 * sum(orders) FILTER (WHERE shard_was <> shard_now) / sum(orders), 2)
                                                  AS "переехало_%"
FROM all_routes
GROUP BY стратегия, ord
ORDER BY ord;
