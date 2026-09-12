"""CLI для эксплуатации партиций (лабораторная №3).

Команды:

    create           создать недостающие партиции на горизонт вперёд (ночной job)
    check            PartitionHealthCheck + уведомление в Telegram при смене статуса
    status           показать существующие партиции и их размеры
    break            удалить партицию — имитация сбоя ночного job
    test-alert       отправить тестовое сообщение в Telegram

Примеры:

    python -m scripts.partition_job status  --table events
    python -m scripts.partition_job create  --table events --horizon 3
    python -m scripts.partition_job check   --table events
    python -m scripts.partition_job break   --partition events_2026_09_15
    python -m scripts.partition_job test-alert

Внутри docker compose:

    docker compose exec backend python -m scripts.partition_job check
"""

import argparse
import logging
import sys
from datetime import date, datetime
from typing import List, Optional

from app.alerts import TelegramNotifier
from app.config import settings
from app.db import close_pool, connection, open_pool
from app.repositories import partitions as partitions_repo
from app.services import partitions as partitions_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("partition-job")


def cmd_status(args: argparse.Namespace) -> int:
    with connection(readonly=True) as conn:
        if not partitions_repo.is_partitioned(conn, args.table, args.schema):
            print(f"Таблица '{args.schema}.{args.table}' не партиционирована")
            return 1
        rows = partitions_repo.list_partitions(conn, args.table, args.schema)

    print(f"Таблица: {args.schema}.{args.table}, партиций: {len(rows)}")
    for row in rows:
        print(f"  {row['partition_name']:<28} {row['size']:>10}  {row['bounds']}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    report = partitions_service.ensure_partitions(
        table=args.table,
        horizon=args.horizon,
        granularity=args.granularity,
        today=args.today,
        schema=args.schema,
    )
    if report["created"]:
        print("Созданы партиции: " + ", ".join(report["created"]))
    else:
        print("Все нужные партиции уже существуют, создавать нечего")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = partitions_service.run_health_check(
        table=args.table,
        horizon=args.horizon,
        granularity=args.granularity,
        today=args.today,
        schema=args.schema,
        force_notify=args.force_notify,
    )

    print(f"Результат проверки: {report['status']}")
    print(f"Ожидается партиций: {len(report['required'])}")
    for name in report["required"]:
        mark = "OK " if name in report["present"] else "!! "
        print(f"  {mark} {name}")

    if report["missing"]:
        print("Отсутствуют: " + ", ".join(report["missing"]))

    if report["notified"]:
        print("Уведомление отправлено в Telegram")
    elif not report["status_changed"]:
        print("Статус не изменился — уведомление не отправлялось (защита от спама)")

    # Ненулевой код возврата удобен для мониторинга и CI.
    return 0 if report["status"] == partitions_service.STATUS_OK else 2


def cmd_break(args: argparse.Namespace) -> int:
    """Имитация сбоя: удаляем партицию, которую должен был создать job."""
    with connection() as conn:
        partitions_repo.drop_partition(conn, args.partition, args.schema)
    print(f"Партиция {args.partition} удалена — теперь проверка должна вернуть CRITICAL")
    return 0


def cmd_test_alert(args: argparse.Namespace) -> int:
    notifier = TelegramNotifier()
    if not notifier.configured:
        print(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы. "
            "Пропиши их в .env или передай через окружение."
        )
        return 1

    text = (
        "🔔 Test alert\n\n"
        f"Service: {settings.app_title}\n"
        f"Table: {args.table}\n"
        f"Checked at: {datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    ok = notifier.send(text)
    print("Отправлено" if ok else "Не удалось отправить, смотри лог выше")
    return 0 if ok else 1


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Управление партициями и алертинг")
    parser.add_argument("--table", default=settings.partition_table)
    parser.add_argument(
        "--horizon",
        type=int,
        default=settings.partition_horizon_days,
        help="на сколько периодов вперёд должны существовать партиции",
    )
    parser.add_argument(
        "--granularity", choices=["day", "month"], default=settings.partition_granularity
    )
    parser.add_argument("--schema", default="public")
    parser.add_argument(
        "--today",
        type=_parse_date,
        default=None,
        help="подменить «сегодня» (YYYY-MM-DD) — удобно для проверок",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="показать партиции").set_defaults(func=cmd_status)
    sub.add_parser("create", help="создать недостающие").set_defaults(func=cmd_create)

    check = sub.add_parser("check", help="проверить и при необходимости отправить alert")
    check.add_argument(
        "--force-notify",
        action="store_true",
        help="отправить уведомление даже если статус не менялся",
    )
    check.set_defaults(func=cmd_check)

    broken = sub.add_parser("break", help="удалить партицию (имитация сбоя job)")
    broken.add_argument("--partition", required=True)
    broken.set_defaults(func=cmd_break)

    sub.add_parser("test-alert", help="отправить тестовое сообщение").set_defaults(
        func=cmd_test_alert
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    open_pool()
    try:
        return args.func(args)
    except RuntimeError as exc:
        # Ожидаемые ошибки конфигурации показываем текстом, без стектрейса.
        print(f"Ошибка: {exc}")
        return 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
