import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin, get_current_user
from api_trafix.crud import payment as crud
from api_trafix.models import PaymentMethod, PaymentStatus, User
from api_trafix.schemas.payment import PaymentPage, PaymentRead
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/", response_model=PaymentPage)
async def list_payments(
    park_transaction_id: uuid.UUID | None = Query(default=None),
    method: PaymentMethod | None = Query(default=None),
    status_filter: PaymentStatus | None = Query(default=None, alias="status"),
    paid_from: datetime | None = Query(default=None),
    paid_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items, total = await crud.get_all(
        db,
        park_transaction_id=park_transaction_id,
        method=method,
        status=status_filter,
        paid_from=paid_from,
        paid_to=paid_to,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return PaymentPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    db_obj = await crud.get_by_id(db, payment_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return db_obj


@router.post("/{payment_id}/refund", response_model=PaymentRead)
async def refund_payment(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, payment_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    if db_obj.status != PaymentStatus.SUCCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only a successful payment can be refunded",
        )
    await log_action(
        db,
        "payment",
        "refund",
        user_id=admin.id,
        role=admin.role.value,
        description=f"Refund payment {db_obj.reference_number} amount={db_obj.amount}",
    )
    return await crud.refund(db, db_obj)
