"""HTTP-слой для категорий."""

from typing import List

from fastapi import APIRouter, status

from app.schemas import CategoryCreate, CategoryOut
from app.services import categories as categories_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=List[CategoryOut], summary="Список категорий")
def list_categories():
    return categories_service.list_categories()


@router.get("/{category_id}", response_model=CategoryOut, summary="Категория по id")
def get_category(category_id: int):
    return categories_service.get_category(category_id)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED, summary="Создать категорию")
def create_category(payload: CategoryCreate):
    return categories_service.create_category(payload.name, payload.slug)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить категорию")
def delete_category(category_id: int) -> None:
    categories_service.delete_category(category_id)
