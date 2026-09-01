import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import (
    get_current_admin,
    get_current_operator,
    get_current_user,
)
from api_trafix.crud import gate as gate_crud
from api_trafix.crud import operator_shift_assignment as assignment_crud
from api_trafix.crud import operator_session as crud
from api_trafix.crud import shift as shift_crud
from api_trafix.models import Gate, GateType, OperatorSessionStatus, User, UserRole
from api_trafix.services.audit import log_action
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


async def _resolve_exit_gate(db: AsyncSession, gate_id: uuid.UUID | None) -> Gate:
    """Resolve the gate a cashier session is bound to.

    Operators serve the exit gate only (gate-in is fully automatic), so an
    omitted ``gate_id`` resolves THE configured exit gate. Exactly one
    gate_out must exist — ambiguity would risk opening the wrong barrier.
    An explicit ``gate_id`` stays supported (deploy rollout, tests) but must
    also be a gate_out.
    """
    if gate_id is not None:
        gate = await gate_crud.get_by_id(db, gate_id)
        if gate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gerbang tidak ditemukan")
        if gate.type != GateType.GATE_OUT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sesi operator hanya dapat dibuka di gerbang keluar",
            )
        return gate

    exits = (
        (await db.execute(select(Gate).where(Gate.type == GateType.GATE_OUT).order_by(Gate.gate_code)))
        .scalars()
        .all()
    )
    if len(exits) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Belum ada gate keluar yang dikonfigurasi",
        )
    if len(exits) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Harus ada tepat satu gate keluar; hapus atau ubah gate keluar lainnya",
        )
    return exits[0]


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan")

    if not await assignment_crud.has_active_assignment(db, operator.id, payload.shift_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak dijadwalkan pada shift ini",
        )

    gate = await _resolve_exit_gate(db, payload.gate_id)

    active = await crud.get_active_for_operator(db, operator.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator sudah memiliki sesi aktif",
        )

    db_obj = await crud.start(db, payload, operator, gate)
    await log_action(
        db,
        module="operator-session",
        action="start",
        user_id=operator.id,
        role=operator.role.value,
        description=f"Operator '{operator.username}' started session at gate '{gate.name}'",
    )
    return db_obj


@router.post("/{session_id}/end", response_model=OperatorSessionRead)
async def end_operator_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_obj = await crud.get_by_id(db, session_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sesi operator tidak ditemukan"
        )
    if db_obj.status == OperatorSessionStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Sesi sudah ditutup"
        )
    if current_user.role != UserRole.ADMIN and db_obj.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tidak diizinkan menutup sesi ini",
        )
    db_obj = await crud.end(db, db_obj)
    await log_action(
        db,
        module="operator-session",
        action="end",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Ended operator session {session_id}",
    )
    return db_obj


@router.get("/{session_id}", response_model=OperatorSessionRead)
async def get_operator_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, session_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sesi operator tidak ditemukan"
        )
    return db_obj
