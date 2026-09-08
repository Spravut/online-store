# Shop API — учебный backend интернет-магазина

Проект подготовлен к модулю по масштабированию баз данных: обычный CRUD-сервис
поверх PostgreSQL, на котором дальше будем измерять производительность, строить
индексы, партиционировать и шардировать данные.

## О проекте

Предметная область — **интернет-магазин**: пользователи оформляют заказы,
заказ состоит из позиций (товаров с зафиксированной ценой покупки), товары
принадлежат категориям, на товары пишут отзывы.

Стек:

- Python 3.12 + FastAPI
- PostgreSQL 16
- psycopg3 (**сырой SQL**, без ORM) + пул соединений
- миграции — обычные `.sql` файлы, применяются автоматически при старте
- Docker + Docker Compose

ORM сознательно не используется: на модуле нужно видеть и менять ровно те
запросы, которые уходят в базу.

## Запуск

```bash
docker compose up
```

Поднимается PostgreSQL и backend. При старте приложение само применяет миграции
(схема + небольшой демонстрационный набор данных), поэтому API сразу отвечает
осмысленными данными.

| Что | Где |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Health check | http://localhost:8000/health |
| PostgreSQL | `localhost:5432`, база `shop`, пользователь/пароль `shop` / `shop` |

Полная пересборка с чистой базой:

```bash
docker compose down -v && docker compose up --build
```

## Архитектура

```
Client
  ↓
API / router          app/api/*.py          — HTTP, валидация, коды ответов
  ↓
Service               app/services/*.py     — бизнес-логика, транзакции
  ↓
Repository            app/repositories/*.py — SQL и только SQL
  ↓
PostgreSQL            app/db.py             — пул соединений
```

Хендлеры не работают с базой напрямую: они вызывают сервисы, сервисы —
репозитории, и только репозитории выполняют SQL.

Подключение к PostgreSQL живёт в одном месте — [`app/db.py`](app/db.py).
Там же контекстный менеджер `connection(readonly=...)`: сейчас оба режима ходят
в primary, а когда появится реплика, менять придётся только этот файл.

Ключевые файлы:

| Файл | Назначение |
|---|---|
| `app/main.py` | сборка приложения, обработчики ошибок, старт пула и миграций |
| `app/db.py` | пул соединений, единственная точка подключения к БД |
| `app/migrate.py` | раннер миграций (таблица `schema_migrations`) |
| `app/repositories/orders.py` | SQL по основной растущей сущности |
| `app/repositories/analytics.py` | JOIN-ы через несколько таблиц и агрегации |
| `migrations/*.sql` | схема и демо-данные |
| `scripts/generate_data.py` | массовая генерация данных |

## Схема БД

```
users ──1:N──▶ orders ──1:N──▶ order_items ◀──N:1── products ──N:1──▶ categories
  │                                                     ▲
  └──1:N──▶ reviews ──────────────────────────N:1───────┘
```

- `users` — покупатели (`id`, `email` UNIQUE, `full_name`, `city`, `created_at`)
- `categories` — категории товаров (`id`, `name`, `slug`)
- `products` — товары (`id`, `category_id` → categories, `name`, `price`, `stock`, `created_at`)
- `orders` — **заказы**, основная растущая сущность (`id`, `user_id` → users, `status`, `total_amount`, `created_at`, `updated_at`)
- `order_items` — позиции заказа, таблица-связка **many-to-many** между `orders` и `products`
  (`order_id`, `product_id`, `quantity`, `price_at_purchase`, UNIQUE `(order_id, product_id)`)
- `reviews` — отзывы, вторая связка `users` × `products` (UNIQUE `(product_id, user_id)`)

Связи: one-to-many — `users → orders`, `categories → products`, `orders → order_items`;
many-to-many — `orders ↔ products` через `order_items` и `users ↔ products` через `reviews`.

Дополнительных индексов в схеме намеренно нет — только PRIMARY KEY и UNIQUE.
Исходное состояние нужно, чтобы на модуле самим увидеть, что деградирует.

## Основные endpoint'ы

### Служебные

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | приложение живо и видит PostgreSQL |
| GET | `/docs` | Swagger UI |

### Users

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/users` | список, пагинация, фильтр `city`, поиск `search`, `sort` |
| GET | `/api/users/{id}` | пользователь |
| POST | `/api/users` | создать |
| PUT | `/api/users/{id}` | обновить |
| DELETE | `/api/users/{id}` | удалить |
| GET | `/api/users/{id}/orders` | заказы пользователя (связанная сущность) |

### Products

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/products` | пагинация, `search` (ILIKE), `category_id`, `min_price`, `max_price`, `sort` |
| GET | `/api/products/{id}` | товар |
| POST / PUT / DELETE | `/api/products[/{id}]` | CRUD |
| GET | `/api/products/{id}/reviews` | отзывы на товар (связанная сущность) |

### Orders

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/orders` | пагинация, фильтры `status`, `user_id`, `from`, `to`, `min_amount`, `sort` |
| GET | `/api/orders/{id}` | заказ с покупателем и позициями (JOIN) |
| GET | `/api/orders/{id}/items` | позиции заказа (связанная сущность) |
| POST | `/api/orders` | создать заказ вместе с позициями (в одной транзакции) |
| PUT | `/api/orders/{id}` | сменить статус |
| DELETE | `/api/orders/{id}` | удалить |

### Categories / Reviews / Analytics

| Метод | Путь | Описание |
|---|---|---|
| GET / POST / DELETE | `/api/categories[/{id}]` | категории |
| GET / POST / DELETE | `/api/reviews[/{id}]` | отзывы |
| GET | `/api/analytics/sales-by-category` | продажи по категориям (агрегация) |
| GET | `/api/analytics/top-products` | топ товаров по выручке (JOIN + агрегация) |
| GET | `/api/analytics/users/{id}/stats` | статистика по пользователю (агрегация) |

Примеры:

```bash
curl "http://localhost:8000/health"
curl "http://localhost:8000/api/orders?status=PAID&page=1&page_size=20&sort=-created_at"
curl "http://localhost:8000/api/orders?from=2026-01-01&to=2026-02-01"
curl "http://localhost:8000/api/products?search=ноут&min_price=1000&sort=price"
curl "http://localhost:8000/api/analytics/sales-by-category"
```

## Пагинация, фильтрация, сортировка

- **Пагинация**: `?page=1&page_size=20` на `/api/orders`, `/api/products`, `/api/users`,
  `/api/users/{id}/orders`, `/api/products/{id}/reviews`.
  Ответ: `{"items": [...], "total": N, "page": 1, "page_size": 20}`.
- **Фильтры**: `?status=PAID`, `?user_id=5`, `?from=...&to=...`, `?min_amount=...`,
  `?search=phone` (ILIKE), `?category_id=2`, `?min_price&max_price`, `?city=Москва`.
- **Сортировка**: `?sort=created_at` и `?sort=-created_at` (минус — DESC).
  Поле проверяется по белому списку в [`app/repositories/_sql.py`](app/repositories/_sql.py),
  поэтому подстановка в текст запроса безопасна.

## Основная сущность для масштабирования

**`orders`**

Почему она подходит:

- количество заказов растёт линейно со временем и никогда не уменьшается —
  это единственная таблица, которая будет расти неограниченно;
- у неё есть `created_at`, по которому естественно делать **партиционирование по диапазону дат**
  (свежие заказы читают часто, прошлогодние — почти никогда);
- у неё есть `user_id` — естественный **ключ шардирования**: заказы одного покупателя
  живут на одном шарде, и запросы «мои заказы» не становятся распределёнными;
- она участвует во всех тяжёлых запросах: фильтрация по статусу и диапазону дат,
  сортировка по `created_at`, JOIN с `users`, `order_items`, `products`, `categories`
  и агрегации выручки;
- вместе с ней растёт `order_items` (в среднем 2–3 строки на заказ), то есть
  миллион заказов — это ещё и ~2.5 млн позиций.

## Сложные запросы

### JOIN №1 — позиции заказа с товаром и категорией

4 таблицы. Используется в `GET /api/orders/{id}` и `GET /api/orders/{id}/items`.
Код: [`app/repositories/orders.py`](app/repositories/orders.py) → `list_items`.

```sql
SELECT oi.id,
       oi.order_id,
       oi.product_id,
       p.name AS product_name,
       c.name AS category_name,
       oi.quantity,
       oi.price_at_purchase,
       (oi.quantity * oi.price_at_purchase) AS line_total
FROM order_items oi
JOIN orders     o ON o.id = oi.order_id
JOIN products   p ON p.id = oi.product_id
JOIN categories c ON c.id = p.category_id
WHERE o.id = %s
ORDER BY oi.id;
```

### JOIN №2 — топ товаров по выручке с рейтингом

4 таблицы + подзапрос с агрегацией по отзывам (отдельно, чтобы отзывы не размножали
строки). Используется в `GET /api/analytics/top-products`.
Код: [`app/repositories/analytics.py`](app/repositories/analytics.py) → `top_products`.

```sql
SELECT p.id                                    AS product_id,
       p.name                                  AS product_name,
       c.name                                  AS category_name,
       SUM(oi.quantity)                        AS units_sold,
       SUM(oi.quantity * oi.price_at_purchase) AS revenue,
       ROUND(r.avg_rating, 2)                  AS avg_rating,
       COALESCE(r.reviews_count, 0)            AS reviews_count
FROM products p
JOIN categories  c  ON c.id = p.category_id
JOIN order_items oi ON oi.product_id = p.id
JOIN orders      o  ON o.id = oi.order_id
LEFT JOIN (
    SELECT product_id,
           AVG(rating)::numeric AS avg_rating,
           COUNT(*)             AS reviews_count
    FROM reviews
    GROUP BY product_id
) AS r ON r.product_id = p.id
WHERE o.status <> 'CANCELLED'
  AND (%s::timestamptz IS NULL OR o.created_at >= %s)
  AND (%s::timestamptz IS NULL OR o.created_at <  %s)
GROUP BY p.id, p.name, c.name, r.avg_rating, r.reviews_count
ORDER BY revenue DESC
LIMIT %s;
```

### Агрегация — продажи по категориям

`COUNT(DISTINCT)`, `SUM`, `AVG`, `GROUP BY`, `HAVING`.
Используется в `GET /api/analytics/sales-by-category`.
Код: [`app/repositories/analytics.py`](app/repositories/analytics.py) → `sales_by_category`.

```sql
SELECT c.id                                                 AS category_id,
       c.name                                               AS category_name,
       COUNT(DISTINCT o.id)                                 AS orders_count,
       COALESCE(SUM(oi.quantity), 0)                        AS items_sold,
       COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) AS revenue,
       COALESCE(ROUND(AVG(oi.quantity * oi.price_at_purchase), 2), 0) AS avg_order_item
FROM categories c
JOIN products    p  ON p.category_id = c.id
JOIN order_items oi ON oi.product_id = p.id
JOIN orders      o  ON o.id = oi.order_id
WHERE o.status <> 'CANCELLED'
  AND (%s::timestamptz IS NULL OR o.created_at >= %s)
  AND (%s::timestamptz IS NULL OR o.created_at <  %s)
GROUP BY c.id, c.name
HAVING SUM(oi.quantity) > 0
ORDER BY revenue DESC;
```

Ещё одна агрегация — статистика пользователя (`COUNT`, `SUM`, `AVG`, `MAX`,
`LEFT JOIN`) в `GET /api/analytics/users/{id}/stats`.

### Запросы, которые станут интересными при росте объёма

| Тип | Где |
|---|---|
| поиск `WHERE name ILIKE ...` | `/api/products?search=` |
| фильтр `WHERE status = ...` | `/api/orders?status=` |
| диапазон `WHERE created_at >= ... AND < ...` | `/api/orders?from=&to=` |
| сортировка `ORDER BY created_at DESC` + `LIMIT/OFFSET` | пагинация везде |
| `COUNT(*)` для `total` в пагинации | каждый список |
| JOIN на 4 таблицы | `/api/orders/{id}` |
| агрегация по всей истории | `/api/analytics/*` |

Посмотреть план любого из них:

```bash
docker compose exec postgres psql -U shop -d shop -c "EXPLAIN ANALYZE SELECT * FROM orders WHERE status = 'PAID' ORDER BY created_at DESC LIMIT 20;"
```

## Генерация данных

Демо-данные (5 категорий, 40 товаров, 50 пользователей, 300 заказов, 600 позиций,
~200 отзывов) приезжают автоматически с миграцией `002_seed_demo.sql`.

Для больших объёмов есть генератор. Данные создаются на стороне PostgreSQL
(`generate_series` + `random()`), поэтому это быстро.

```bash
# внутри docker compose
docker compose exec backend python -m scripts.generate_data \
    --users 100000 --products 5000 --orders 1000000 --reviews 200000

# локально (нужен доступ к порту 5432)
python -m scripts.generate_data --orders 20000
```

Параметры:

| Флаг | По умолчанию | Что делает |
|---|---|---|
| `--users` | 1000 | сколько пользователей добавить |
| `--products` | 500 | сколько товаров добавить |
| `--orders` | 20000 | сколько заказов добавить (позиции создаются автоматически) |
| `--reviews` | 2000 | сколько отзывов добавить |
| `--max-items` | 4 | максимум позиций в заказе |
| `--days` | 730 | на какой период «размазать» `created_at` заказов |
| `--batch-size` | 100000 | размер порции вставки |
| `--truncate` | — | очистить таблицы перед генерацией |

Замер на локальной машине: 100 000 заказов и 250 000 позиций — около 27 секунд.

Проверить, что получилось:

```bash
docker compose exec postgres psql -U shop -d shop -c "SELECT count(*) FROM orders;"
```

## Миграции

Все изменения схемы — только через `.sql` файлы в `migrations/`, вручную через GUI
схема не правится. Раннер ([`app/migrate.py`](app/migrate.py)) применяет файлы по
порядку имён и запоминает применённые в таблице `schema_migrations`.

Добавить миграцию: положить `003_что_то.sql` в `migrations/` и перезапустить backend.

Отключить автоприменение можно переменной окружения `RUN_MIGRATIONS=false`.

## Что будет дальше (на модуле)

Специально **не сделано** заранее: индексы (кроме PK/UNIQUE), партиционирование,
репликация, шардирование, оптимизация запросов. Это предмет занятий.
