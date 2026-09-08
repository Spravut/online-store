"""Мелкие помощники для сборки SQL: сортировка и WHERE-условия."""

from typing import Dict, List, Optional, Tuple

from app.errors import ValidationError


def build_order_by(sort: Optional[str], allowed: Dict[str, str], default: str) -> str:
    """Превращает ?sort=created_at / ?sort=-created_at в кусок ORDER BY.

    `allowed` — белый список: имя из query -> выражение в SQL. Всё, чего нет
    в списке, отклоняется, поэтому подстановка в текст запроса безопасна.
    """
    if not sort:
        return default

    direction = "DESC" if sort.startswith("-") else "ASC"
    field = sort.lstrip("-+")

    if field not in allowed:
        raise ValidationError(
            f"Сортировка по '{field}' не поддерживается. Доступны: {', '.join(sorted(allowed))}"
        )

    return f"{allowed[field]} {direction}"


def build_where(conditions: List[Tuple[str, object]]) -> Tuple[str, List[object]]:
    """Собирает WHERE из пар (условие, значение), пропуская значения None."""
    clauses: List[str] = []
    params: List[object] = []

    for clause, value in conditions:
        if value is None:
            continue
        clauses.append(clause)
        params.append(value)

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params
