"""Простейшая система миграций: применяет .sql файлы из каталога migrations/.

Каждый файл выполняется ровно один раз, факт применения фиксируется в таблице
schema_migrations. Файлы применяются в порядке имён, поэтому имена начинаются
с номера: 001_init.sql, 002_seed_demo.sql, ...
"""

import logging
from pathlib import Path

from app.db import connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def run_migrations() -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row["version"] for row in cur.fetchall()}
        conn.commit()

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue

            logger.info("applying migration %s", path.name)
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (path.name,),
                )
            conn.commit()

        logger.info("migrations are up to date")
