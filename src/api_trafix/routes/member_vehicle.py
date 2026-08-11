import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.services.audit import log_action
from api_trafix.crud import member as member_crud
from api_trafix.crud import member_vehicle as crud
from api_trafix.crud import vehicle_type as vehicle_type_crud
from api_trafix.models import User, MemberStatus, VehicleStatus
from api_trafix.schemas.member_vehicle import (
    MemberVehicleCreate,
    MemberVehiclePage,
    MemberVehicleRead,
    MemberVehicleUpdate,
)

router = APIRouter(prefix="/member-vehicles", tags=["Member Vehicles"])


@router.get("/", response_model=MemberVehiclePage)
async def list_member_vehicles(
    search: str | None = Query(default=None, max_length=100),
    member_id: uuid.UUID | None = Query(default=None),
    vehicle_type_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db,
        search=search,
        member_id=member_id,
        vehicle_type_id=vehicle_type_id,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return MemberVehiclePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{vehicle_id}", response_model=MemberVehicleRead)
async def get_member_vehicle(vehicle_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, vehicle_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member vehicle not found"
        )
    return db_obj


@router.post("/", response_model=MemberVehicleRead, status_code=status.HTTP_201_CREATED)
async def create_member_vehicle(
    payload: MemberVehicleCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    member = await member_crud.get_by_id(db, payload.member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.status != MemberStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Member is not active"
        )

    vehicle_type = await vehicle_type_crud.get_by_id(db, payload.vehicle_type_id)
    if vehicle_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found"
        )
    if vehicle_type.status != VehicleStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle type is not active"
        )

    existing = await crud.get_by_police_number(db, payload.police_number)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Police number already registered"
        )

    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        "member_vehicle",
        "create",
        user_id=admin.id,
        role=admin.role.value,
        description=f"Register vehicle {db_obj.police_number} for member {payload.member_id}",
    )
    return db_obj


@router.put("/{vehicle_id}", response_model=MemberVehicleRead)
async def update_member_vehicle(
    vehicle_id: uuid.UUID,
    payload: MemberVehicleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, vehicle_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member vehicle not found"
        )

    if payload.police_number and payload.police_number != db_obj.police_number:
        existing = await crud.get_by_police_number(db, payload.police_number)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Police number already registered",
            )

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        "member_vehicle",
        "update",
        user_id=admin.id,
        role=admin.role.value,
        description=f"Update vehicle {db_obj.police_number}",
    )
    return db_obj


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, vehicle_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member vehicle not found"
        )
    if await crud.is_in_use(db, vehicle_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle is used by park transactions",
        )
    plate = db_obj.police_number
    await crud.delete(db, db_obj)
    await log_action(
        db,
        "member_vehicle",
        "delete",
        user_id=admin.id,
        role=admin.role.value,
        description=f"Delete vehicle {plate}",
    )
    return None
