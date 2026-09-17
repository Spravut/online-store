"""Планировщик фоновых задач по работе с партициями (лабораторная №3).

Заменяет собой cron: поднимается вместе с приложением, поэтому ничего
настраивать вне `docker compose up` не нужно.

Две задачи:

* `ensure_partitions` — ночью создаёт партиции на горизонт вперёд;
* `run_health_check`  — регулярно проверяет, что они на месте, и шлёт alert.

Используется `BackgroundScheduler`, а не асинхронный: обе задачи работают с
синхронным пулом psycopg и выполняются в отдельных потоках, не блокируя
event loop FastAPI. Это та же модель, по которой FastAPI выполняет обычные
`def`-эндпоинты.
"""

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services import partitions as partitions_service

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _create_partitions_job() -> None:
    """Ночное создание партиций. Исключения гасим: планировщик должен выжить."""
    try:
        partitions_service.ensure_partitions()
    except Exception as exc:  # noqa: BLE001
        logger.error("CreatePartitionsJob упал: %s", exc)


def _health_check_job() -> None:
    """Регулярная проверка + alert при смене статуса."""
    try:
        partitions_service.run_health_check()
    except Exception as exc:  # noqa: BLE001
        logger.error("PartitionHealthCheck упал: %s", exc)


def start() -> None:
    """Поднимает планировщик, если он включён в настройках."""
    global _scheduler

    if not settings.scheduler_enabled:
        logger.info("планировщик выключен (SCHEDULER_ENABLED=false)")
        return

    _scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)

    # Общие параметры задач:
    #   coalesce           — после простоя выполнить один раз, а не N пропущенных;
    #   max_instances=1    — не запускать вторую копию, пока работает первая;
    #   misfire_grace_time — насколько опоздание ещё считается допустимым.
    _scheduler.add_job(
        _create_partitions_job,
        trigger=CronTrigger(
            hour=settings.partition_create_hour,
            minute=settings.partition_create_minute,
        ),
        id="create_partitions",
        name="CreatePartitionsJob",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        _health_check_job,
        trigger=IntervalTrigger(minutes=settings.partition_check_interval_minutes),
        id="partition_health_check",
        name="PartitionHealthCheck",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    _scheduler.start()

    for job in _scheduler.get_jobs():
        logger.info("задача %s: следующий запуск %s", job.name, job.next_run_time)


def shutdown() -> None:
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("планировщик остановлен")


def jobs_status() -> list:
    """Список задач и времён следующего запуска — для эндпоинта /health."""
    if _scheduler is None:
        return []
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]
