"""Бизнес-логика по категориям."""

from typing import Any, Dict, List

from app.db import connection
from app.errors import ConflictError, NotFoundError
from app.repositories import categories as categories_repo


def list_categories() -> List[Dict[str, Any]]:
    with connection(readonly=True) as conn:
        return categories_repo.list_all(conn)


def get_category(category_id: int) -> Dict[str, Any]:
    with connection(readonly=True) as conn:
        category = categories_repo.get_by_id(conn, category_id)

    if category is None:
        raise NotFoundError(f"Категория {category_id} не найдена")
    return category


def create_category(name: str, slug: str) -> Dict[str, Any]:
    with connection() as conn:
        existing = [c for c in categories_repo.list_all(conn) if c["slug"] == slug]
        if existing:
            raise ConflictError(f"Категория со slug '{slug}' уже существует")
        return categories_repo.create(conn, name, slug)


def delete_category(category_id: int) -> None:
    with connection() as conn:
        deleted = categories_repo.delete(conn, category_id)

    if not deleted:
        raise NotFoundError(f"Категория {category_id} не найдена")
