"""Бизнес-логика по товарам: поиск, фильтры, сортировка, пагинация."""

from decimal import Decimal
from typing import Any, Dict, Optional

from app.db import connection
from app.errors import NotFoundError, ValidationError
from app.repositories import categories as categories_repo
from app.repositories import products as products_repo
from app.repositories import reviews as reviews_repo
from app.repositories._sql import build_order_by


def list_products(
    page: int,
    page_size: int,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    sort: Optional[str] = None,
) -> Dict[str, Any]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValidationError("min_price не может быть больше max_price")

    order_by = build_order_by(sort, products_repo.SORTABLE, default="p.created_at DESC")
    offset = (page - 1) * page_size

    with connection(readonly=True) as conn:
        total = products_repo.count(
            conn, search=search, category_id=category_id, min_price=min_price, max_price=max_price
        )
        items = products_repo.list_products(
            conn,
            limit=page_size,
            offset=offset,
            search=search,
            category_id=category_id,
            min_price=min_price,
            max_price=max_price,
            order_by=order_by,
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_product(product_id: int) -> Dict[str, Any]:
    with connection(readonly=True) as conn:
        product = products_repo.get_by_id(conn, product_id)

    if product is None:
        raise NotFoundError(f"Товар {product_id} не найден")
    return product


def create_product(
    category_id: int, name: str, description: Optional[str], price: Decimal, stock: int
) -> Dict[str, Any]:
    with connection() as conn:
        if categories_repo.get_by_id(conn, category_id) is None:
            raise NotFoundError(f"Категория {category_id} не найдена")
        return products_repo.create(conn, category_id, name, description, price, stock)


def update_product(
    product_id: int,
    category_id: int,
    name: str,
    description: Optional[str],
    price: Decimal,
    stock: int,
) -> Dict[str, Any]:
    with connection() as conn:
        if categories_repo.get_by_id(conn, category_id) is None:
            raise NotFoundError(f"Категория {category_id} не найдена")

        product = products_repo.update(
            conn, product_id, category_id, name, description, price, stock
        )

    if product is None:
        raise NotFoundError(f"Товар {product_id} не найден")
    return product


def delete_product(product_id: int) -> None:
    with connection() as conn:
        deleted = products_repo.delete(conn, product_id)

    if not deleted:
        raise NotFoundError(f"Товар {product_id} не найден")


def list_product_reviews(product_id: int, page: int, page_size: int) -> Dict[str, Any]:
    """Отзывы на товар: GET /api/products/{id}/reviews."""
    offset = (page - 1) * page_size

    with connection(readonly=True) as conn:
        if products_repo.get_by_id(conn, product_id) is None:
            raise NotFoundError(f"Товар {product_id} не найден")

        total = reviews_repo.count_by_product(conn, product_id)
        items = reviews_repo.list_by_product(conn, product_id, limit=page_size, offset=offset)

    return {"items": items, "total": total, "page": page, "page_size": page_size}
