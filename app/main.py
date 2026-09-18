"""Точка входа приложения.

Слои: API (этот файл + app/api) -> Service (app/services) -> Repository
(app/repositories) -> PostgreSQL (app/db.py).
"""

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import scheduler
from app.api import analytics, categories, health, orders, products, reviews, shards, users
from app.config import settings
from app.db import close_pool, open_pool
from app.errors import ConflictError, NotFoundError, ValidationError
from app.migrate import run_migrations
from app.sharding.pools import ShardUnavailable, close_shard_pools, open_shard_pools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    open_shard_pools()
    if settings.run_migrations:
        run_migrations()
    scheduler.start()
    yield
    scheduler.shutdown()
    close_shard_pools()
    close_pool()


DESCRIPTION = """
Учебный backend интернет-магазина для модуля по масштабированию баз данных.

**Основная растущая сущность — `orders`.**

Стек: FastAPI + psycopg3 (сырой SQL) + PostgreSQL, миграции — `.sql` файлы.
"""

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description=DESCRIPTION,
    lifespan=lifespan,
)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ShardUnavailable)
async def shard_unavailable_handler(request: Request, exc: ShardUnavailable) -> JSONResponse:
    """Отказ шарда (лабораторная №6, задание 6).

    503, а не 500: запрос не сломан, просто нужный кусок данных сейчас
    недоступен. Остальные шарды при этом продолжают обслуживаться.
    """
    logger.warning("shard unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc), "partial": True})


@app.exception_handler(psycopg.IntegrityError)
async def integrity_handler(request: Request, exc: psycopg.IntegrityError) -> JSONResponse:
    logger.warning("integrity error: %s", exc)
    return JSONResponse(status_code=409, content={"detail": "Нарушение целостности данных"})


app.include_router(health.router)
app.include_router(users.router)
app.include_router(categories.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(reviews.router)
app.include_router(analytics.router)
app.include_router(shards.router)


@app.get("/", include_in_schema=False)
def root():
    return {"service": settings.app_title, "docs": "/docs", "health": "/health"}
