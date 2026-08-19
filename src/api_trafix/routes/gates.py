import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.crud import gate as crud
from api_trafix.models import GateType, User
from api_trafix.schemas.gate import GateCreate, GatePage, GateRead, GateUpdate
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/gates", tags=["Gates"])


async def _reload_registry(request: Request) -> None:
    """Pick up gate changes in the running orchestrator without a restart."""
    registry = getattr(request.app.state, "device_registry", None)
    if registry is not None:
        await registry.reload()


@router.get("/", response_model=GatePage)
async def list_gates(
    search: str | None = Query(default=None, max_length=100),
    gate_type: GateType | None = Query(default=None, alias="type"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    items, total = await crud.get_all(
        db, search=search, gate_type=gate_type, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return GatePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{gate_id}", response_model=GateRead)
async def get_gate(
    gate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, gate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    return db_obj


@router.post("/", response_model=GateRead, status_code=status.HTTP_201_CREATED)
async def create_gate(
    payload: GateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    if payload.gate_code and await crud.get_by_gate_code(db, payload.gate_code) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gate_code is already in use by another gate",
        )
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="gate",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created gate '{db_obj.name}' ({db_obj.gate_code or '-'})",
    )
    await _reload_registry(request)
    return db_obj


@router.put("/{gate_id}", response_model=GateRead)
async def update_gate(
    gate_id: uuid.UUID,
    payload: GateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, gate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    if payload.gate_code and payload.gate_code != db_obj.gate_code:
        existing = await crud.get_by_gate_code(db, payload.gate_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gate_code is already in use by another gate",
            )

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="gate",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated gate '{db_obj.name}' ({db_obj.gate_code or '-'})",
    )
    await _reload_registry(request)
    return db_obj


@router.delete("/{gate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate(
    gate_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, gate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    if await crud.is_in_use(db, gate_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gate is referenced by park transactions",
        )
    await log_action(
        db,
        module="gate",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted gate '{db_obj.name}' ({db_obj.gate_code or '-'})",
    )
    await crud.delete(db, db_obj)
    await _reload_registry(request)
    return None
