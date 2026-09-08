"""HTTP-слой для отзывов."""

from fastapi import APIRouter, status

from app.schemas import ReviewCreate, ReviewOut
from app.services import reviews as reviews_service

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/{review_id}", response_model=ReviewOut, summary="Отзыв по id")
def get_review(review_id: int):
    return reviews_service.get_review(review_id)


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED, summary="Создать отзыв")
def create_review(payload: ReviewCreate):
    return reviews_service.create_review(
        payload.product_id, payload.user_id, payload.rating, payload.comment
    )


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить отзыв")
def delete_review(review_id: int) -> None:
    reviews_service.delete_review(review_id)
