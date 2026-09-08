"""HTTP-слой для аналитики: JOIN-ы и агрегации."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query

from app.schemas import CategorySalesOut, TopProductOut, UserStatsOut
from app.services import analytics as analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get(
    "/sales-by-category",
    response_model=List[CategorySalesOut],
    summary="Продажи по категориям (агрегация)",
)
def sales_by_category(
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
):
    return analytics_service.sales_by_category(date_from, date_to)


@router.get(
    "/top-products",
    response_model=List[TopProductOut],
    summary="Топ товаров по выручке (JOIN + агрегация)",
)
def top_products(
    limit: int = Query(10, ge=1, le=100),
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
):
    return analytics_service.top_products(limit, date_from, date_to)


@router.get(
    "/users/{user_id}/stats",
    response_model=UserStatsOut,
    summary="Статистика по пользователю (агрегация)",
)
def user_stats(user_id: int):
    return analytics_service.user_stats(user_id)
