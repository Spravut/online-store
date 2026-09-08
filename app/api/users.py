"""HTTP-слой для пользователей. Ходит только в сервисы, не в БД."""

from typing import Optional

from fastapi import APIRouter, Query, status

from app.schemas import OrderOut, Page, UserCreate, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=Page[UserOut], summary="Список пользователей")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    city: Optional[str] = Query(None, description="Фильтр по городу"),
    search: Optional[str] = Query(None, description="Поиск по имени (ILIKE)"),
    sort: Optional[str] = Query(None, description="created_at | -created_at | full_name | id"),
):
    return users_service.list_users(page, page_size, city, search, sort)


@router.get("/{user_id}", response_model=UserOut, summary="Пользователь по id")
def get_user(user_id: int):
    return users_service.get_user(user_id)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Создать пользователя")
def create_user(payload: UserCreate):
    return users_service.create_user(payload.email, payload.full_name, payload.city)


@router.put("/{user_id}", response_model=UserOut, summary="Обновить пользователя")
def update_user(user_id: int, payload: UserUpdate):
    return users_service.update_user(user_id, payload.email, payload.full_name, payload.city)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить пользователя")
def delete_user(user_id: int) -> None:
    users_service.delete_user(user_id)


@router.get("/{user_id}/orders", response_model=Page[OrderOut], summary="Заказы пользователя")
def list_user_orders(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    return users_service.list_user_orders(user_id, page, page_size, status_filter)
