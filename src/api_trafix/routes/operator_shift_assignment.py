import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import operator_shift_assignment as crud
from api_trafix.crud import shift as shift_crud
from api_trafix.crud import users as user_crud
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.schemas.operator_shift_assignment import (
    OperatorShiftAssignmentCreate,
    OperatorShiftAssignmentPage,
    OperatorShiftAssignmentRead,
)

router = APIRouter(prefix="/operator-shifts", tags=["Operator Shift Assignments"])


@router.get("/", response_model=OperatorShiftAssignmentPage)
async def list_operator_shift_assignments(
    operator_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db, operator_id=operator_id, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return OperatorShiftAssignmentPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{assignment_id}", response_model=OperatorShiftAssignmentRead)
async def get_operator_shift_assignment(
    assignment_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    db_obj = await crud.get_by_id(db, assignment_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator shift assignment not found",
        )
    return db_obj


@router.post(
    "/",
    response_model=OperatorShiftAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_shift_to_operator(
    payload: OperatorShiftAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    operator = await user_crud.get_by_id(db, payload.operator_id)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found"
        )
    if operator.role != UserRole.OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not an operator",
        )
    if operator.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator is not active",
        )

    shift = await shift_crud.get_by_id(db, payload.shift_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found"
        )

    existing = await crud.get_by_operator_and_shift(
        db, payload.operator_id, payload.shift_id
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator is already assigned to this shift",
        )

    return await crud.create(db, payload)


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator_shift_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, assignment_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator shift assignment not found",
        )
    await crud.delete(db, db_obj)
    return None
