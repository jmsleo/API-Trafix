import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import (
    get_current_admin,
    get_current_operator,
    get_current_user,
)
from api_trafix.crud import park_transaction as crud
from api_trafix.models import ParkingStatus, User, UserRole
from api_trafix.schemas.park_transaction import (
    ParkTransactionCheckOut,
    ParkTransactionCreate,
    ParkTransactionPage,
    ParkTransactionRead,
)
from api_trafix.services import parking as parking_service
from api_trafix.services.errors import ServiceError

router = APIRouter(prefix="/park-transactions", tags=["Park Transactions"])


def _handle_service_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post(
    "/", response_model=ParkTransactionRead, status_code=status.HTTP_201_CREATED
)
async def check_in(
    payload: ParkTransactionCreate,
    db: AsyncSession = Depends(get_db),
    operator: User = Depends(get_current_operator),
):
    try:
        return await parking_service.check_in(db, operator, payload)
    except ServiceError as exc:
        raise _handle_service_error(exc)


@router.post("/{transaction_id}/checkout", response_model=ParkTransactionRead)
async def check_out(
    transaction_id: uuid.UUID,
    payload: ParkTransactionCheckOut,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in (UserRole.OPERATOR, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    try:
        return await parking_service.check_out(db, current_user, transaction_id, payload)
    except ServiceError as exc:
        raise _handle_service_error(exc)


@router.post("/{transaction_id}/void", response_model=ParkTransactionRead)
async def void_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    try:
        return await parking_service.void(db, admin, transaction_id)
    except ServiceError as exc:
        raise _handle_service_error(exc)


@router.get("/", response_model=ParkTransactionPage)
async def list_park_transactions(
    search: str | None = Query(default=None, max_length=100),
    status_filter: ParkingStatus | None = Query(default=None, alias="status"),
    vehicle_type_id: uuid.UUID | None = Query(default=None),
    member_id: uuid.UUID | None = Query(default=None),
    entry_from: datetime | None = Query(default=None),
    entry_to: datetime | None = Query(default=None),
    exit_from: datetime | None = Query(default=None),
    exit_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db,
        search=search,
        status=status_filter,
        vehicle_type_id=vehicle_type_id,
        member_id=member_id,
        entry_from=entry_from,
        entry_to=entry_to,
        exit_from=exit_from,
        exit_to=exit_to,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return ParkTransactionPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{transaction_id}", response_model=ParkTransactionRead)
async def get_park_transaction(
    transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    db_obj = await crud.get_by_id(db, transaction_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Park transaction not found",
        )
    return db_obj
