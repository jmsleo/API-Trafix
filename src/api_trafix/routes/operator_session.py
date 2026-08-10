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
from api_trafix.crud import gate as gate_crud
from api_trafix.crud import operator_session as crud
from api_trafix.crud import shift as shift_crud
from api_trafix.models import OperatorSessionStatus, User, UserRole
from api_trafix.schemas.operator_session import (
    OperatorSessionPage,
    OperatorSessionRead,
    OperatorSessionStart,
)

router = APIRouter(prefix="/operator-sessions", tags=["Operator Sessions"])


@router.get("/", response_model=OperatorSessionPage)
async def list_operator_sessions(
    operator_id: uuid.UUID | None = Query(default=None),
    status_filter: OperatorSessionStatus | None = Query(default=None, alias="status"),
    login_from: datetime | None = Query(default=None),
    login_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db,
        operator_id=operator_id,
        status=status_filter,
        login_from=login_from,
        login_to=login_to,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return OperatorSessionPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.post(
    "/start",
    response_model=OperatorSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_operator_session(
    payload: OperatorSessionStart,
    db: AsyncSession = Depends(get_db),
    operator: User = Depends(get_current_operator),
):
    shift = await shift_crud.get_by_id(db, payload.shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    gate = await gate_crud.get_by_id(db, payload.gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    active = await crud.get_active_for_operator(db, operator.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator already has an active session",
        )

    return await crud.start(db, payload, operator)


@router.post("/{session_id}/end", response_model=OperatorSessionRead)
async def end_operator_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_obj = await crud.get_by_id(db, session_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operator session not found"
        )
    if db_obj.status == OperatorSessionStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Session already closed"
        )
    if current_user.role != UserRole.ADMIN and db_obj.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to close this session",
        )
    return await crud.end(db, db_obj)


@router.get("/{session_id}", response_model=OperatorSessionRead)
async def get_operator_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, session_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operator session not found"
        )
    return db_obj
