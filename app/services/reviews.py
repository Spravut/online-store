"""Бизнес-логика по отзывам."""

from typing import Any, Dict, Optional

from app.db import connection
from app.errors import ConflictError, NotFoundError
from app.repositories import products as products_repo
from app.repositories import reviews as reviews_repo
from app.repositories import users as users_repo


def get_review(review_id: int) -> Dict[str, Any]:
    with connection(readonly=True) as conn:
        review = reviews_repo.get_by_id(conn, review_id)

    if review is None:
        raise NotFoundError(f"Отзыв {review_id} не найден")
    return review


def create_review(
    product_id: int, user_id: int, rating: int, comment: Optional[str]
) -> Dict[str, Any]:
    with connection() as conn:
        if products_repo.get_by_id(conn, product_id) is None:
            raise NotFoundError(f"Товар {product_id} не найден")
        if users_repo.get_by_id(conn, user_id) is None:
            raise NotFoundError(f"Пользователь {user_id} не найден")
        if reviews_repo.exists(conn, product_id, user_id):
            raise ConflictError("Пользователь уже оставил отзыв на этот товар")

        return reviews_repo.create(conn, product_id, user_id, rating, comment)


def delete_review(review_id: int) -> None:
    with connection() as conn:
        deleted = reviews_repo.delete(conn, review_id)

    if not deleted:
        raise NotFoundError(f"Отзыв {review_id} не найден")
