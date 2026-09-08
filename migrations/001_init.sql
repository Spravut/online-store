-- Базовая схема интернет-магазина.
-- Намеренно без дополнительных индексов: на модуле мы сначала измерим
-- производительность "как есть", а потом будем её улучшать.

CREATE TABLE users (
    id         BIGSERIAL PRIMARY KEY,
    email      TEXT        NOT NULL UNIQUE,
    full_name  TEXT        NOT NULL,
    city       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categories (
    id   BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,
    category_id BIGINT         NOT NULL REFERENCES categories (id) ON DELETE RESTRICT,
    name        TEXT           NOT NULL,
    description TEXT,
    price       NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    stock       INTEGER        NOT NULL DEFAULT 0 CHECK (stock >= 0),
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Основная растущая сущность.
CREATE TABLE orders (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    status       TEXT           NOT NULL DEFAULT 'NEW'
                     CHECK (status IN ('NEW', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
    total_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Таблица-связка many-to-many между orders и products.
CREATE TABLE order_items (
    id                BIGSERIAL PRIMARY KEY,
    order_id          BIGINT         NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    product_id        BIGINT         NOT NULL REFERENCES products (id) ON DELETE RESTRICT,
    quantity          INTEGER        NOT NULL CHECK (quantity > 0),
    price_at_purchase NUMERIC(12, 2) NOT NULL CHECK (price_at_purchase >= 0),
    UNIQUE (order_id, product_id)
);

CREATE TABLE reviews (
    id         BIGSERIAL PRIMARY KEY,
    product_id BIGINT      NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    user_id    BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    rating     SMALLINT    NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, user_id)
);
