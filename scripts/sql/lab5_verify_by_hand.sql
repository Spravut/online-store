-- Та же логика, что в остальных файлах, но на восьми ключах —
-- чтобы каждую строчку можно было проверить глазами.
-- Выполнять на shop-primary (порт 5434), база shop.
WITH keys AS (
    SELECT user_id, hashtext(user_id::text) AS h
    FROM generate_series(1, 8) user_id
),
ring3 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,2) s, generate_series(0,149) v),
ring4 AS (SELECT s AS shard, hashtext('shard-'||s||'#'||v) AS point
          FROM generate_series(0,3) s, generate_series(0,149) v)
SELECT k.user_id,
       k.h                                        AS hashtext,
       ((h % 3) + 3) % 3                          AS mod3,
       ((h % 4) + 4) % 4                          AS mod4,
       CASE WHEN ((h%3)+3)%3 <> ((h%4)+4)%4
            THEN 'переехал' ELSE '-' END          AS mod_переезд,
       COALESCE((SELECT r.shard FROM ring3 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                (SELECT r.shard FROM ring3 r ORDER BY r.point LIMIT 1)) AS ring3,
       COALESCE((SELECT r.shard FROM ring4 r WHERE r.point >= k.h ORDER BY r.point LIMIT 1),
                (SELECT r.shard FROM ring4 r ORDER BY r.point LIMIT 1)) AS ring4
FROM keys k
ORDER BY user_id;
