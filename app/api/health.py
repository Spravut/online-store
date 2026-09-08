"""Health check: проверяем, что приложение живо и видит PostgreSQL."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import connection

router = APIRouter(tags=["health"])


@router.get("/health", summary="Проверка приложения и подключения к БД")
def health() -> JSONResponse:
    try:
        with connection(readonly=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - хотим вернуть любую причину как есть
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "down", "detail": str(exc)},
        )

    return JSONResponse(content={"status": "ok", "database": "up"})
