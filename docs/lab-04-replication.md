# Лабораторная работа №4. Масштабирование чтения: Primary + Replica

Streaming replication для сервиса магазина: запись идёт на primary, чтение —
на реплику. Плюс разбор того, почему реплика может отставать.

**Среда**

| Роль | Контейнер | Образ | Порт на хосте |
|---|---|---|---|
| Primary | `shop_postgres` | postgres:16-alpine | 5432 (по умолчанию) |
| Replica | `shop_postgres_replica` | postgres:16-alpine | 5433 (по умолчанию) |
| Backend | `shop_backend` | FastAPI + psycopg3 | 8000 |

Данные на момент работы: `orders` — 5 000 300 строк в 32 партициях,
`order_items` — 12,5 млн.

---

# Часть 1. Primary и Replica

## Фрагмент `docker-compose.yml`

```yaml
  postgres:                        # ← PRIMARY
    image: postgres:16-alpine
    container_name: shop_postgres
    environment:
      POSTGRES_USER: shop
      POSTGRES_PASSWORD: shop
      POSTGRES_DB: shop
      REPLICATION_USER: "${REPLICATION_USER:-replicator}"
      REPLICATION_PASSWORD: "${REPLICATION_PASSWORD:-replpass}"
    ports:
      - "${POSTGRES_HOST_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d:ro

  postgres_replica:                # ← REPLICA
    image: postgres:16-alpine
    container_name: shop_postgres_replica
    environment:
      PGDATA: /var/lib/postgresql/data
      PGPASSWORD: "${REPLICATION_PASSWORD:-replpass}"
    ports:
      - "${POSTGRES_REPLICA_HOST_PORT:-5433}:5432"
    volumes:
      - pgdata_replica:/var/lib/postgresql/data
    depends_on:
      postgres:
        condition: service_healthy
    command: >
      sh -c '
      if [ ! -s "$$PGDATA/PG_VERSION" ]; then
        rm -rf "$$PGDATA"/*;
        su-exec postgres pg_basebackup -h postgres -p 5432 -U "$$REPLICATION_USER" -D "$$PGDATA" -Fp -Xs -P -R;
        echo "primary_conninfo = ..." >> "$$PGDATA/postgresql.auto.conf";
        echo "hot_standby = on" >> "$$PGDATA/postgresql.auto.conf";
      fi;
      chown -R postgres:postgres "$$PGDATA";
      chmod 0700 "$$PGDATA";
      exec su-exec postgres postgres'
```

Ключевой момент: штатный `docker-entrypoint.sh` умеет только `initdb`, то есть
создавать **пустую** базу. Реплика же должна стартовать с копии primary, поэтому
для неё задана своя команда. Так как первый аргумент не `postgres`, entrypoint
просто выполняет скрипт, не пытаясь ничего инициализировать. Условие
`if [ ! -s "$PGDATA/PG_VERSION" ]` делает запуск идемпотентным: базовая копия
снимается только один раз, при пустом томе.

## Кто есть кто

| | Primary | Replica |
|---|---|---|
| Имя сервиса | `postgres` | `postgres_replica` |
| Принимает запись | да | **нет** |
| `pg_is_in_recovery()` | `false` | `true` |
| Роль в приложении | `DATABASE_URL` | `DATABASE_REPLICA_URL` |

## Как подключиться

```bash
docker compose exec postgres psql -U shop -d shop           # primary
docker compose exec postgres_replica psql -U shop -d shop   # replica
```

Снаружи (psql, pgAdmin, DBeaver):

```
primary:  localhost:5432, база shop, пользователь shop / shop
replica:  localhost:5433, те же учётные данные
```

Порты параметризованы (`POSTGRES_HOST_PORT`, `POSTGRES_REPLICA_HOST_PORT`) —
на машине, где 5432 занят локально установленным PostgreSQL, они переопределяются
в `.env` без правки compose.

---

# Часть 2. Streaming replication

## Что потребовалось на Primary

Приятная неожиданность: PostgreSQL 16 из коробки готов быть primary —
проверка показала

```
 wal_level       | replica
 max_wal_senders | 10
 hot_standby     | on
```

Менять параметры не пришлось. Не хватало только двух вещей.

**1. Роль с правом репликации:**

```sql
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replpass';
```

**2. Разрешение в `pg_hba.conf`.** По умолчанию образ разрешает репликацию
только с localhost:

```
local   replication     all                                     trust
host    replication     all             127.0.0.1/32            trust
host    replication     all             ::1/128                 trust
```

Реплика живёт в соседнем контейнере, поэтому добавлена строка:

```
host replication replicator all scram-sha-256
```

Обе операции оформлены скриптом
[`postgres/init/10-replication.sh`](../postgres/init/10-replication.sh), который
образ выполняет при первом запуске с пустым томом. На уже развёрнутой базе
(наш случай — 5 млн заказов терять не хотелось) те же действия сделаны вручную
с последующим `SELECT pg_reload_conf()`.

## Как реплика получила данные

```bash
pg_basebackup -h postgres -p 5432 -U replicator -D "$PGDATA" -Fp -Xs -P -R
```

| Флаг | Что делает |
|---|---|
| `-Fp` | plain format — готовый каталог данных, а не tar |
| `-Xs` | stream: WAL забирается параллельно с копированием, поэтому копия сразу консистентна |
| `-R` | записывает `standby.signal` и `primary_conninfo` — после этого каталог является репликой |
| `-P` | прогресс в лог |

`primary_conninfo` дописывается явно, чтобы в строке подключения был пароль:
`-R` берёт параметры соединения, но `PGPASSWORD` в конфиг не переносит, и без
этого реплика не смогла бы переподключиться после рестарта.

## Цепочка «как изменение попадает на реплику»

```
1. Primary выполняет INSERT/UPDATE/DELETE
        ↓
2. Изменение записывается в WAL (журнал предзаписи) и фиксируется на диске
        ↓
3. Процесс walsender на primary отдаёт поток WAL
        ↓
4. Процесс walreceiver на реплике принимает его и пишет к себе
        ↓
5. Процесс startup (recovery) применяет записи к файлам данных
        ↓
6. Изменение становится видно запросам на реплике
```

Лог реплики показывает ровно эти шаги:

```
LOG:  entering standby mode
LOG:  starting backup recovery with redo LSN 6/1F000028, checkpoint LSN 6/1F000060
LOG:  consistent recovery state reached at 6/1F000138
LOG:  database system is ready to accept read-only connections
LOG:  started streaming WAL from primary at 6/20000000 on timeline 1
```

## Проверка состояния на Primary

```sql
SELECT * FROM pg_stat_replication;
```

```
-[ RECORD 1 ]----+-------------
application_name | shop_replica
client_addr      | 172.18.0.3
state            | streaming
sync_state       | async
sent_lsn         | 6/20000060
replay_lsn       | 6/20000060
```

Расшифровка:

- `state = streaming` — базовая копия уже передана, идёт непрерывный поток WAL;
- `sync_state = async` — **асинхронная** репликация: primary подтверждает
  коммит клиенту, не дожидаясь реплики. Отсюда и берётся возможность отставания;
- `sent_lsn = replay_lsn` — всё отправленное уже применено, отставания в этот
  момент нет.

---

# Часть 3. Доказательство, что репликация работает

**Запись на Primary:**

```sql
INSERT INTO users (email, full_name, city)
VALUES ('replica-test@example.com', 'Проверка репликации', 'Москва')
RETURNING id, email, full_name, created_at;
```

```
  id   |          email           |      full_name      |          created_at
-------+--------------------------+---------------------+-------------------------------
 20051 | replica-test@example.com | Проверка репликации | 2026-09-17 14:40:24.648829+00
INSERT 0 1
```

**Чтение на Replica** (отдельный контейнер, отдельное подключение):

```sql
SELECT id, email, full_name, created_at FROM users
WHERE email = 'replica-test@example.com';
```

```
  id   |          email           |      full_name      |          created_at
-------+--------------------------+---------------------+-------------------------------
 20051 | replica-test@example.com | Проверка репликации | 2026-09-17 14:40:24.648829+00
```

Совпадают `id`, значения и `created_at` вплоть до микросекунд — это не
повторная вставка, а та же самая строка, приехавшая через WAL.

**Подтверждение подключённой реплики** — вывод `pg_stat_replication` выше
(`state = streaming`) и раздел `replication` в `/health` приложения:

```json
"replication": {
  "replica_enabled": true,
  "reads_go_to": "replica",
  "replicas_connected": [
    {"application_name": "shop_replica", "client_addr": "172.18.0.3/32",
     "state": "streaming", "sync_state": "async",
     "sent_lsn": "6/20000060", "replay_lsn": "6/20000060", "replay_lag_ms": 0}
  ],
  "replica": {"in_recovery": true, "replay_lsn": "6/20000060", "lag_seconds": 0.0}
}
```

---

# Часть 4. Read-only поведение реплики

```sql
-- на реплике
INSERT INTO users (email, full_name) VALUES ('should-fail@example.com', 'Нельзя');
UPDATE users SET city = 'Казань' WHERE id = 1;
```

```
ERROR:  cannot execute INSERT in a read-only transaction
ERROR:  cannot execute UPDATE in a read-only transaction
```

**Почему так.** Реплика постоянно находится в режиме восстановления
(`pg_is_in_recovery() = true`): её единственный источник изменений — поток WAL
с primary. Она не ведёт собственный WAL и не может присвоить транзакции
собственный идентификатор, поэтому любая запись отвергается самой СУБД,
без всяких настроек.

**Почему приложению нельзя считать реплику отдельной базой для записи.**
Даже если бы запись была технически возможна, данные немедленно разошлись бы:
на primary одна история изменений, на реплике другая. Следующая же запись WAL
с primary попыталась бы применить изменение к строке, которой на реплике уже
нет или которая выглядит иначе — репликация сломалась бы. Реплика по определению
является **побайтовой копией** primary, а не второй независимой базой.
Архитектурно это означает: **один источник правды для записи**.

---

# Часть 5. Чтение сервиса через реплику

## Где это в коде

Вся маршрутизация — в [`app/db.py`](../app/db.py), в одном месте:

```python
_primary_pool = _build_pool(settings.database_url)
_replica_pool = (
    _build_pool(settings.database_replica_url) if settings.database_replica_url else None
)


@contextmanager
def connection(readonly: bool = False) -> Iterator[Connection]:
    target = _replica_pool if (readonly and _replica_pool is not None) else _primary_pool
    with target.connection() as conn:
        yield conn
```

Это сработало без единой правки в SQL, потому что контекстный менеджер
`connection(readonly=...)` существовал в проекте с самого начала — читающие
сервисы уже вызывали его с флагом, писавшие без. Раньше оба режима вели
в primary, теперь флаг определяет пул.

Пример читающего сценария — `GET /api/users/{id}/orders`,
[`app/services/users.py`](../app/services/users.py):

```python
def list_user_orders(user_id, page, page_size, status):
    with connection(readonly=True) as conn:          # ← уходит на реплику
        total = orders_repo.count(conn, user_id=user_id, status=status)
        items = orders_repo.list_orders(conn, ...)
```

А запись — `POST /api/orders`, [`app/services/orders.py`](../app/services/orders.py):

```python
with connection() as conn:                            # ← primary
    order = orders_repo.create(conn, user_id, merged)
```

Через реплику сейчас идут: списки заказов, товаров и пользователей, карточка
заказа, позиции заказа, отзывы и вся аналитика. Через primary — все `INSERT`,
`UPDATE`, `DELETE`, а также миграции и job создания партиций.

## Read-after-write: единственное место, где пришлось думать

`create_order` после вставки перечитывал заказ, чтобы вернуть его клиенту
вместе с позициями. Если бы этот `SELECT` ушёл на реплику, клиент мог бы
получить **404 на только что созданный ресурс** — изменение ещё не доехало.

```python
def get_order(order_id: int, use_replica: bool = True) -> Dict[str, Any]:
    """`use_replica=False` нужен сразу после записи: реплика могла ещё
    не получить изменение (replication lag)."""
    with connection(readonly=use_replica) as conn:
        ...


def create_order(user_id, items):
    with connection() as conn:
        order = orders_repo.create(conn, user_id, merged)

    # Read-after-write: читаем с primary, иначе на реплике заказа может
    # ещё не быть и клиент получил бы 404 на только что созданный ресурс.
    return get_order(order["id"], use_replica=False)
```

Это общее правило read scaling: **чтение сразу после собственной записи должно
идти на primary**, всё остальное можно отдавать реплике.

## Доказательство, что чтение действительно идёт на реплику

Соединения приложения видны на реплике (`172.18.0.4` — контейнер backend):

```
 datname | usename | application_name |  client_addr  | connections | states
---------+---------+------------------+---------------+-------------+--------
 shop    | shop    |                  | 172.18.0.4/32 |           2 | idle
```

Более наглядное доказательство — в части 6: при остановленном проигрывании WAL
API возвращает устаревшие данные, хотя на primary они уже есть. Если бы запросы
шли в primary, этого бы не произошло.

## Поведение без реплики

Если `DATABASE_REPLICA_URL` пуст или реплика недоступна, `open_pool()` ловит
ошибку и переключает чтение обратно на primary:

```python
except Exception as exc:
    logger.error("реплика недоступна (%s), чтение идёт в primary", exc)
    _disable_replica()
```

Сервис поднимается и работает — просто без масштабирования чтения.

---

# Часть 6. Replication lag

## Естественное отставание

200 вставок на primary, сразу замер:

```
lag_bytes  | 0
replay_lag | 00:00:00.002745
write_lag  | 00:00:00.000563
flush_lag  | 00:00:00.002528
```

**2,7 миллисекунды.** На локальной машине, где контейнеры соединены виртуальной
сетью, поймать устаревшее чтение «на глаз» практически невозможно — реплика
догоняет быстрее, чем успевает выполниться следующий запрос.

Три величины показывают три стадии: `write_lag` — реплика записала WAL,
`flush_lag` — сбросила на диск, `replay_lag` — применила к данным. Видно, что
основное время уходит между записью и применением.

## Отставание, сделанное видимым

Чтобы зафиксировать момент расхождения, проигрывание WAL на реплике
останавливается штатной функцией:

```sql
-- на реплике
SELECT pg_wal_replay_pause();
```

Реплика продолжает **получать** WAL, но перестаёт его **применять**.

**Пишем на primary:**

```sql
INSERT INTO users (email, full_name, city)
SELECT 'lag-test-' || g || '@example.com', 'Лаг ' || g, 'Сочи'
FROM generate_series(1,3) g;

SELECT count(*) FROM users WHERE email LIKE 'lag-test-%';   →  3
```

**Читаем с реплики:**

```sql
SELECT count(*) FROM users WHERE email LIKE 'lag-test-%';   →  0
```

**Читаем через API сервиса:**

```bash
curl "http://localhost:8000/api/users?search=Лаг&page_size=5"
→ найдено пользователей: 0
```

Вот он, зафиксированный момент: **на primary 3 строки, на реплике и в ответе
API — ноль**. Заодно это прямое доказательство части 5 — запрос сервиса
обслуживается репликой.

Отставание в цифрах в тот же момент:

```
primary_lsn | 6/200096A0
replay_lsn  | 6/200033D0
lag_bytes   | 25296
replay_lag  | 00:00:00.133294
```

**После `SELECT pg_wal_replay_resume()`:**

```
реплика:  3
API:      3
```

Реплика догнала за доли секунды, данные сошлись.

> **Главный вывод.** Репликация не означает мгновенную синхронизацию. Между
> коммитом на primary и применением изменения на реплике всегда есть промежуток.
> В нормальном режиме он измеряется единицами миллисекунд, но при нагрузке,
> сетевых проблемах или долгих транзакциях на реплике может вырасти до секунд
> и минут. Приложение обязано это учитывать — иначе пользователь увидит, что
> «созданный заказ пропал».

---

# Контрольные вопросы

**1. Чем Primary отличается от Replica?**
Primary — единственный экземпляр, принимающий изменения; он ведёт WAL и является
источником правды. Replica находится в режиме постоянного восстановления
(`pg_is_in_recovery() = true`), не ведёт собственный WAL и применяет поток
изменений от primary. Проверяется одним запросом, а на практике — тем, что
`INSERT` на реплике падает с `cannot execute INSERT in a read-only transaction`.

**2. Почему запись выполняем на Primary?**
Потому что должен быть один источник правды. Если писать в оба экземпляра
независимо, их истории разойдутся и репликация сломается: реплика не сможет
применить WAL к данным, которые у неё уже другие. Технически СУБД этого и не
разрешает — реплика физически не умеет принимать запись.

**3. Как изменение из Primary попадает на Replica?**
`INSERT` → запись в WAL на primary → процесс `walsender` отдаёт поток по сети →
`walreceiver` на реплике принимает и сохраняет → процесс `startup` применяет
записи к файлам данных → изменение видно запросам. Состояние цепочки видно
в `pg_stat_replication` (`state = streaming`).

**4. Что такое WAL в контексте репликации?**
Write-Ahead Log — журнал предзаписи. Любое изменение сначала попадает в него
и только потом в файлы данных; изначально он нужен для восстановления после
сбоя. Streaming replication использует тот же журнал как транспорт: реплика
получает те же записи и «проигрывает» их у себя. То есть репликация — это
непрерывное восстановление по чужому журналу.

**5. Что такое replication lag?**
Задержка между моментом, когда изменение зафиксировано на primary, и моментом,
когда оно применено на реплике. Измеряется в байтах WAL
(`pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)`) и во времени
(`replay_lag`). В наших замерах — 2,7 мс в обычном режиме и 25 296 байт при
искусственно остановленном проигрывании.

**6. Почему SELECT после INSERT может увидеть старые данные, если отправить его на реплику?**
Потому что репликация асинхронная: primary подтверждает коммит клиенту, **не
дожидаясь** реплики (`sync_state = async`). Между подтверждением и применением
на реплике проходит время, и запрос, попавший в этот промежуток, увидит
состояние «до». Именно это воспроизведено в части 6: на primary три строки,
на реплике ноль. Поэтому в сервисе чтение сразу после записи явно отправлено
на primary (`get_order(..., use_replica=False)`).

**7. Что масштабируется при Read Scaling: скорость одного запроса или способность обслуживать больше чтений?**
Второе. Один и тот же `SELECT` на реплике выполняется примерно столько же,
сколько на primary — железо и планы те же. Выигрыш в том, что читающая нагрузка
распределяется между экземплярами: primary разгружается и может больше времени
тратить на запись, а суммарная пропускная способность по чтению растёт
пропорционально числу реплик. Латентность отдельного запроса не улучшается,
улучшается **пропускная способность системы**.

**8. Почему наличие реплики не отменяет индексы и оптимизацию SQL?**
Потому что реплика — точная копия primary, включая схему, индексы и объём
данных. Запрос, который делает `Seq Scan` по 5 млн строк, будет делать ровно то
же самое и на реплике. Реплика умножает количество экземпляров, но не уменьшает
стоимость одного запроса. Более того, тяжёлый неоптимизированный запрос на
реплике может увеличить replication lag: долгая транзакция мешает применять WAL.
Сначала оптимизация, потом масштабирование — иначе тиражируется неэффективность.

**9. CAP-теорема**
Утверждает, что распределённая система при **разделении сети** (Partition
tolerance) вынуждена выбирать между согласованностью (Consistency) и
доступностью (Availability): одновременно все три свойства обеспечить нельзя.
Сеть ненадёжна всегда, поэтому P — не опция, а данность, и реальный выбор
всегда между C и A.

Наша конфигурация — наглядный пример **AP**: асинхронная репликация. Если связь
между primary и репликой пропадёт, реплика продолжит отвечать на запросы
(доступность сохранена), но данные будут устаревшими (строгая согласованность
нарушена). Ровно это и показано в части 6.

Выбрать CP можно было бы, включив синхронную репликацию
(`synchronous_commit = on` + `synchronous_standby_names`): тогда primary ждёт
подтверждения от реплики перед ответом клиенту, отставания нет, но при потере
реплики **запись на primary остановится** — доступность принесена в жертву
согласованности. Для интернет-магазина, где показать список заказов на 50 мс
устаревшим не страшно, а отказ в оформлении заказа стоит денег, выбран AP.

Стоит добавить, что CAP описывает поведение только в момент разделения сети;
в обычном режиме система и доступна, и согласована. Более точную картину даёт
расширение **PACELC**: при разделении (P) выбираем между A и C, а в нормальном
режиме (Else) — между latency (L) и consistency (C). Наша система: PA/EL —
и при сбое, и в норме мы предпочитаем скорость строгой согласованности.

---

## Что изменилось в репозитории

| Файл | Изменение |
|---|---|
| [`docker-compose.yml`](../docker-compose.yml) | сервис `postgres_replica`, том `pgdata_replica`, проброс `DATABASE_REPLICA_URL` |
| [`postgres/init/10-replication.sh`](../postgres/init/10-replication.sh) | подготовка primary: роль `replicator` и правило в `pg_hba.conf` |
| [`app/db.py`](../app/db.py) | два пула, маршрутизация по `readonly`, диагностика репликации |
| [`app/config.py`](../app/config.py) | настройка `database_replica_url` |
| [`app/services/orders.py`](../app/services/orders.py) | read-after-write: `get_order(..., use_replica=False)` |
| [`app/api/health.py`](../app/api/health.py) | раздел `replication` в ответе |
| [`.env.example`](../.env.example) | переменные реплики и учётки репликации |

Ни один SQL-запрос и ни один репозиторий не изменились — маршрутизация чтения
целиком уместилась в `app/db.py`.
