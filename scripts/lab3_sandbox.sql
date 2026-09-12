-- Песочница для лабораторной работы №3: партиционированная таблица events.
--
-- Это учебная таблица, а не часть доменной схемы магазина, поэтому она
-- создаётся отдельным скриптом, а не миграцией — в рабочем развёртывании
-- сервиса её нет.
--
-- Запуск:
--   docker compose exec -T postgres psql -U shop -d shop -f - < scripts/lab3_sandbox.sql

DROP TABLE IF EXISTS events CASCADE;

CREATE TABLE events (
    id         BIGSERIAL   NOT NULL,
    user_id    BIGINT      NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload    TEXT,
    created_at TIMESTAMP   NOT NULL
) PARTITION BY RANGE (created_at);

-- Индексы объявляются на родительской таблице: PostgreSQL автоматически
-- создаёт соответствующий индекс в каждой партиции, включая будущие.
CREATE INDEX idx_events_user_id ON events (user_id);
CREATE INDEX idx_events_event_type ON events (event_type);

-- Стартовые партиции: позавчера, вчера, сегодня.
-- Дальше их создаёт job: python -m scripts.partition_job create
DO $$
DECLARE
    d DATE;
BEGIN
    FOR d IN SELECT generate_series(CURRENT_DATE - 2, CURRENT_DATE, '1 day')::date LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF events FOR VALUES FROM (%L) TO (%L)',
            'events_' || to_char(d, 'YYYY_MM_DD'), d, d + 1
        );
    END LOOP;
END $$;

-- Тестовые данные, равномерно размазанные по существующим партициям.
INSERT INTO events (user_id, event_type, payload, created_at)
SELECT (random() * 100000)::bigint,
       (ARRAY['click', 'view', 'purchase', 'login'])[1 + floor(random() * 4)::int],
       '{}',
       CURRENT_DATE - 2 + (random() * 3) * INTERVAL '1 day'
FROM generate_series(1, 300000);

ANALYZE events;

SELECT tableoid::regclass AS partition_name, COUNT(*)
FROM events
GROUP BY tableoid
ORDER BY partition_name;
