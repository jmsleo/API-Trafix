import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin, get_current_operator
from api_trafix.crud import operator_shift_assignment as crud
from api_trafix.crud import shift as shift_crud
from api_trafix.crud import users as user_crud
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.services.audit import log_action
from api_trafix.schemas.operator_shift_assignment import (
    OperatorShiftAssignmentCreate,
    OperatorShiftAssignmentPage,
    OperatorShiftAssignmentRead,
    OperatorShiftAssignmentUpdate,
)
from api_trafix.schemas.shift import ShiftRead

router = APIRouter(prefix="/operator-shifts", tags=["Operator Shift Assignments"])


@router.get("/me", response_model=list[ShiftRead])
async def list_my_assigned_shifts(
    operator: User = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """The current operator's ACTIVE assigned shifts (used at login)."""
    assignments = await crud.get_active_by_operator(db, operator.id)
    return [assignment.shift for assignment in assignments]


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
            detail="Penugasan shift operator tidak ditemukan",
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
    current_user: User = Depends(get_current_admin),
):
    operator = await user_crud.get_by_id(db, payload.operator_id)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operator tidak ditemukan"
        )
    if operator.role != UserRole.OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pengguna bukan operator",
        )
    if operator.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator tidak aktif",
        )

    shift = await shift_crud.get_by_id(db, payload.shift_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan"
        )

    existing = await crud.get_by_operator_and_shift(
        db, payload.operator_id, payload.shift_id
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator sudah ditugaskan ke shift ini",
        )

    shift_taken = await crud.get_by_shift_id(db, payload.shift_id)
    if shift_taken is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shift sudah ditugaskan ke operator lain",
        )

    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="operator-shift",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Assigned operator '{operator.username}' to shift '{shift.name}'",
    )
    return db_obj


@router.put(
    "/{assignment_id}",
    response_model=OperatorShiftAssignmentRead,
)
async def update_operator_shift_assignment(
    assignment_id: uuid.UUID,
    payload: OperatorShiftAssignmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, assignment_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Penugasan shift operator tidak ditemukan",
        )

    operator = await user_crud.get_by_id(db, payload.operator_id)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operator tidak ditemukan"
        )
    if operator.role != UserRole.OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pengguna bukan operator",
        )
    if operator.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator tidak aktif",
        )

    shift = await shift_crud.get_by_id(db, payload.shift_id)
    if shift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan"
        )

    existing = await crud.get_by_operator_and_shift(
        db, payload.operator_id, payload.shift_id
    )
    if existing is not None and existing.id != assignment_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator sudah ditugaskan ke shift ini",
        )

    shift_taken = await crud.get_by_shift_id(
        db, payload.shift_id, exclude_id=assignment_id
    )
    if shift_taken is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shift sudah ditugaskan ke operator lain",
        )

    previous_operator = db_obj.operator.username if db_obj.operator else str(db_obj.operator_id)
    previous_shift = db_obj.shift.name if db_obj.shift else str(db_obj.shift_id)
    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="operator-shift",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=(
            f"Updated assignment for operator '{previous_operator}' "
            f"to shift '{previous_shift}' (new operator '{operator.username}', "
            f"shift '{shift.name}')"
        ),
    )
    return db_obj


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator_shift_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, assignment_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Penugasan shift operator tidak ditemukan",
        )
    await log_action(
        db,
        module="operator-shift",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Removed operator shift assignment {assignment_id}",
    )
    await crud.delete(db, db_obj)
    return None
