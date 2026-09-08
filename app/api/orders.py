"""HTTP-слой для заказов."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Query, status

from app.schemas import (
    OrderCreate,
    OrderDetailOut,
    OrderItemOut,
    OrderOut,
    OrderUpdate,
    Page,
)
from app.services import orders as orders_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=Page[OrderOut], summary="Список заказов с фильтрами")
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: Optional[str] = Query(
        None, alias="status", description="NEW | PAID | SHIPPED | DELIVERED | CANCELLED"
    ),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None, alias="from", description="created_at >= from"),
    date_to: Optional[datetime] = Query(None, alias="to", description="created_at < to"),
    min_amount: Optional[Decimal] = Query(None, ge=0),
    sort: Optional[str] = Query(None, description="created_at | -created_at | total_amount | status"),
):
    return orders_service.list_orders(
        page, page_size, status_filter, user_id, date_from, date_to, min_amount, sort
    )


@router.get("/{order_id}", response_model=OrderDetailOut, summary="Заказ с позициями и покупателем")
def get_order(order_id: int):
    return orders_service.get_order(order_id)


@router.get("/{order_id}/items", response_model=List[OrderItemOut], summary="Позиции заказа")
def list_order_items(order_id: int):
    return orders_service.list_order_items(order_id)


@router.post("", response_model=OrderDetailOut, status_code=status.HTTP_201_CREATED, summary="Создать заказ")
def create_order(payload: OrderCreate):
    return orders_service.create_order(payload.user_id, payload.items)


@router.put("/{order_id}", response_model=OrderOut, summary="Изменить статус заказа")
def update_order(order_id: int, payload: OrderUpdate):
    return orders_service.update_order_status(order_id, payload.status)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить заказ")
def delete_order(order_id: int) -> None:
    orders_service.delete_order(order_id)
