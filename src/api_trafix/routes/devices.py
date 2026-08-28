import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.crud import device as crud
from api_trafix.crud import gate as gate_crud
from api_trafix.models import User
from api_trafix.schemas.device import DeviceCreate, DevicePage, DeviceRead, DeviceUpdate
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/devices", tags=["Devices"])


async def _reload_registry(request: Request) -> None:
    """Pick up device changes in the running orchestrator without a restart."""
    registry = getattr(request.app.state, "device_registry", None)
    if registry is not None:
        await registry.reload()


async def _ensure_gate_exists(db: AsyncSession, gate_id: uuid.UUID) -> None:
    if await gate_crud.get_by_id(db, gate_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gerbang yang dirujuk tidak ada",
        )


@router.get("/", response_model=DevicePage)
async def list_devices(
    search: str | None = Query(default=None, max_length=100),
    device_type: str | None = Query(default=None, max_length=50, alias="type"),
    gate_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    items, total = await crud.get_all(
        db, search=search, device_type=device_type, gate_id=gate_id, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return DevicePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, device_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perangkat tidak ditemukan")
    return db_obj


@router.post("/", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    await _ensure_gate_exists(db, payload.gate_id)
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="device",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created device '{db_obj.name}' ({db_obj.type})",
    )
    await _reload_registry(request)
    return db_obj


@router.put("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, device_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perangkat tidak ditemukan")

    if payload.gate_id is not None and payload.gate_id != db_obj.gate_id:
        await _ensure_gate_exists(db, payload.gate_id)

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="device",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated device '{db_obj.name}' ({db_obj.type})",
    )
    await _reload_registry(request)
    return db_obj


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_by_id(db, device_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perangkat tidak ditemukan")
    await log_action(
        db,
        module="device",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted device '{db_obj.name}' ({db_obj.type})",
    )
    await crud.delete(db, db_obj)
    await _reload_registry(request)
    return None
