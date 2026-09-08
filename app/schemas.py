"""Pydantic-схемы запросов и ответов (они же — описание API в Swagger)."""

from datetime import datetime
from decimal import Decimal
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- users
class UserCreate(BaseModel):
    email: str = Field(examples=["ivan@example.com"])
    full_name: str = Field(min_length=1, examples=["Иван Иванов"])
    city: Optional[str] = Field(default=None, examples=["Москва"])


class UserUpdate(BaseModel):
    email: str
    full_name: str = Field(min_length=1)
    city: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    city: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------- categories
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, examples=["Смартфоны"])
    slug: str = Field(min_length=1, examples=["smartphones"])


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str


# ------------------------------------------------------------------------ products
class ProductCreate(BaseModel):
    category_id: int
    name: str = Field(min_length=1, examples=["Смартфон X100"])
    description: Optional[str] = None
    price: Decimal = Field(ge=0, examples=["49990.00"])
    stock: int = Field(ge=0, default=0)


class ProductUpdate(ProductCreate):
    pass


class ProductOut(BaseModel):
    id: int
    category_id: int
    name: str
    description: Optional[str]
    price: Decimal
    stock: int
    created_at: datetime


class ProductWithCategory(ProductOut):
    category_name: str


# -------------------------------------------------------------------------- orders
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, examples=[2])


class OrderCreate(BaseModel):
    user_id: int
    items: List[OrderItemCreate] = Field(min_length=1)


class OrderUpdate(BaseModel):
    status: str = Field(examples=["PAID"])


class OrderOut(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime


class OrderItemOut(BaseModel):
    id: int
    order_id: int
    product_id: int
    product_name: str
    category_name: str
    quantity: int
    price_at_purchase: Decimal
    line_total: Decimal


class OrderDetailOut(OrderOut):
    user_email: str
    user_full_name: str
    items: List[OrderItemOut]


# ------------------------------------------------------------------------- reviews
class ReviewCreate(BaseModel):
    product_id: int
    user_id: int
    rating: int = Field(ge=1, le=5, examples=[5])
    comment: Optional[str] = None


class ReviewOut(BaseModel):
    id: int
    product_id: int
    user_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime


class ReviewWithAuthor(ReviewOut):
    user_full_name: str


# ----------------------------------------------------------------------- analytics
class CategorySalesOut(BaseModel):
    category_id: int
    category_name: str
    orders_count: int
    items_sold: int
    revenue: Decimal
    avg_order_item: Decimal


class TopProductOut(BaseModel):
    product_id: int
    product_name: str
    category_name: str
    units_sold: int
    revenue: Decimal
    avg_rating: Optional[float]
    reviews_count: int


class UserStatsOut(BaseModel):
    user_id: int
    full_name: str
    orders_count: int
    total_spent: Decimal
    avg_order_amount: Decimal
    last_order_at: Optional[datetime]
