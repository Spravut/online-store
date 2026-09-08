"""HTTP-слой для товаров: поиск, фильтры, сортировка, пагинация."""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Query, status

from app.schemas import (
    Page,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    ProductWithCategory,
    ReviewWithAuthor,
)
from app.services import products as products_service

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=Page[ProductWithCategory], summary="Список товаров")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="Поиск по названию (ILIKE)"),
    category_id: Optional[int] = Query(None),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    sort: Optional[str] = Query(None, description="price | -price | name | created_at | -created_at"),
):
    return products_service.list_products(
        page, page_size, search, category_id, min_price, max_price, sort
    )


@router.get("/{product_id}", response_model=ProductOut, summary="Товар по id")
def get_product(product_id: int):
    return products_service.get_product(product_id)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED, summary="Создать товар")
def create_product(payload: ProductCreate):
    return products_service.create_product(
        payload.category_id, payload.name, payload.description, payload.price, payload.stock
    )


@router.put("/{product_id}", response_model=ProductOut, summary="Обновить товар")
def update_product(product_id: int, payload: ProductUpdate):
    return products_service.update_product(
        product_id,
        payload.category_id,
        payload.name,
        payload.description,
        payload.price,
        payload.stock,
    )


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить товар")
def delete_product(product_id: int) -> None:
    products_service.delete_product(product_id)


@router.get("/{product_id}/reviews", response_model=Page[ReviewWithAuthor], summary="Отзывы на товар")
def list_product_reviews(
    product_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    return products_service.list_product_reviews(product_id, page, page_size)
