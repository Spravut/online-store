"""Жизненный цикл партиций: создание вперёд, контроль и алертинг.

Три операции:

* `ensure_partitions()`  — создать недостающие партиции на горизонт вперёд
                           (ночной job, безопасен при повторном запуске);
* `check_partitions()`   — определить, все ли нужные партиции существуют;
* `run_health_check()`   — то же самое плюс уведомление в Telegram, с защитой
                           от повторной отправки одного и того же алерта
                           и с отдельным recovery-сообщением.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.alerts import TelegramNotifier
from app.config import settings
from app.db import connection
from app.repositories import partitions as partitions_repo

logger = logging.getLogger(__name__)

DAY = "day"
MONTH = "month"

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"


# --------------------------------------------------------------- вычисления
def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    year, month = value.year + (value.month // 12), value.month % 12 + 1
    return date(year, month, 1)


def partition_bounds(table: str, moment: date, granularity: str) -> Tuple[str, date, date]:
    """Имя партиции и её границы [from, to) для указанного момента."""
    if granularity == DAY:
        return f"{table}_{moment:%Y_%m_%d}", moment, moment + timedelta(days=1)

    if granularity == MONTH:
        start = _month_start(moment)
        return f"{table}_{start:%Y_%m}", start, _next_month(start)

    raise ValueError(f"неизвестная гранулярность: {granularity}")


def required_partitions(
    table: str, today: date, horizon: int, granularity: str
) -> List[Tuple[str, date, date]]:
    """Партиции, которые обязаны существовать: текущая плюс `horizon` вперёд.

    При horizon=3 и гранулярности по дням это 4 партиции: сегодня и три
    следующих дня — ровно как в задании.
    """
    result: List[Tuple[str, date, date]] = []
    cursor = today

    for _ in range(horizon + 1):
        result.append(partition_bounds(table, cursor, granularity))
        if granularity == DAY:
            cursor = cursor + timedelta(days=1)
        else:
            cursor = _next_month(cursor)

    return result


# ------------------------------------------------------------- create job
def ensure_partitions(
    table: Optional[str] = None,
    horizon: Optional[int] = None,
    granularity: str = DAY,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """CreatePartitionsJob: создаёт недостающие партиции.

    Идемпотентна: уже существующие партиции не трогаются, повторный запуск
    ничего не ломает.
    """
    table = table or settings.partition_table
    horizon = horizon if horizon is not None else settings.partition_horizon_days
    today = today or date.today()

    logger.info("Partition job started. Table: %s, horizon: %s %s(s)", table, horizon, granularity)

    required = required_partitions(table, today, horizon, granularity)
    created: List[str] = []

    with connection() as conn:
        if not partitions_repo.is_partitioned(conn, table):
            raise RuntimeError(
                f"Таблица '{table}' не партиционирована — создавать партиции не для чего"
            )

        existing = set(partitions_repo.partition_names(conn, table))
        missing = [item for item in required if item[0] not in existing]

        logger.info("Existing partitions: %s", len(existing))
        logger.info("Required partitions: %s", len(required))
        logger.info("Missing partitions: %s", len(missing))

        for name, date_from, date_to in missing:
            logger.info("Creating: %s [%s .. %s)", name, date_from, date_to)
            partitions_repo.create_range_partition(conn, table, name, date_from, date_to)
            created.append(name)
            logger.info("Partition created successfully.")

    logger.info("Partition job finished. Created: %s", len(created))

    return {
        "table": table,
        "horizon": horizon,
        "granularity": granularity,
        "required": [item[0] for item in required],
        "existing_count": len(existing),
        "created": created,
    }


# ------------------------------------------------------------- health check
def check_partitions(
    table: Optional[str] = None,
    horizon: Optional[int] = None,
    granularity: str = DAY,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """PartitionHealthCheck: существуют ли все нужные партиции."""
    table = table or settings.partition_table
    horizon = horizon if horizon is not None else settings.partition_horizon_days
    today = today or date.today()

    required = required_partitions(table, today, horizon, granularity)

    with connection(readonly=True) as conn:
        if not partitions_repo.is_partitioned(conn, table):
            raise RuntimeError(f"Таблица '{table}' не партиционирована")
        existing = set(partitions_repo.partition_names(conn, table))

    missing = [name for name, _, _ in required if name not in existing]

    return {
        "table": table,
        "horizon": horizon,
        "granularity": granularity,
        "status": STATUS_CRITICAL if missing else STATUS_OK,
        "required": [name for name, _, _ in required],
        "present": [name for name, _, _ in required if name in existing],
        "missing": missing,
        "checked_at": datetime.now().replace(microsecond=0),
    }


# ----------------------------------------------------------------- алертинг
def format_alert(report: Dict[str, Any]) -> str:
    unit = "day" if report["granularity"] == DAY else "month"
    return (
        "🚨 Partition alert\n\n"
        f"Table: {report['table']}\n"
        f"Missing partitions: {', '.join(report['missing'])}\n"
        f"Expected horizon: {report['horizon']} {unit}s\n"
        f"Checked at: {report['checked_at']:%Y-%m-%d %H:%M:%S}"
    )


def format_recovery(report: Dict[str, Any]) -> str:
    return (
        "🟢 Partition check OK\n\n"
        f"Table: {report['table']}\n"
        "All required partitions exist.\n"
        f"Checked at: {report['checked_at']:%Y-%m-%d %H:%M:%S}"
    )


def run_health_check(
    table: Optional[str] = None,
    horizon: Optional[int] = None,
    granularity: str = DAY,
    today: Optional[date] = None,
    notifier: Optional[TelegramNotifier] = None,
    force_notify: bool = False,
) -> Dict[str, Any]:
    """Проверка + уведомление.

    Уведомление отправляется только при **смене** статуса:

        CRITICAL (было OK)       -> alert
        CRITICAL (было CRITICAL) -> молчим, чтобы не спамить
        OK       (было CRITICAL) -> recovery
        OK       (было OK)       -> молчим

    `force_notify=True` отправляет сообщение независимо от прошлого статуса —
    удобно для демонстрации.
    """
    report = check_partitions(table, horizon, granularity, today)
    notifier = notifier or TelegramNotifier()

    details = ", ".join(report["missing"]) if report["missing"] else ""

    with connection() as conn:
        partitions_repo.ensure_state_table(conn)
        previous = partitions_repo.get_alert_state(conn, report["table"])
        previous_status = previous["status"] if previous else None
        partitions_repo.save_alert_state(conn, report["table"], report["status"], details)

    status_changed = previous_status != report["status"]
    should_notify = force_notify or status_changed

    report["previous_status"] = previous_status
    report["status_changed"] = status_changed
    report["notified"] = False

    if report["status"] == STATUS_CRITICAL:
        logger.error(
            "PartitionHealthCheck: CRITICAL, отсутствуют партиции: %s", details
        )
        message = format_alert(report)
    else:
        logger.info("PartitionHealthCheck: OK, все %s партиций на месте", len(report["required"]))
        message = format_recovery(report)

    if should_notify:
        report["notified"] = notifier.send(message)
    else:
        logger.info(
            "статус не изменился (%s) — уведомление не отправляется", report["status"]
        )

    report["message"] = message
    return report
