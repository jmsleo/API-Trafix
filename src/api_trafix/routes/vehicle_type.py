import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.crud import vehicle_type as crud
from api_trafix.schemas.vehicle_type import (
    VehicleTypeCreate,
    VehicleTypeRead,
    VehicleTypeUpdate,
)

router = APIRouter(prefix="/vehicle-types", tags=["Vehicle Types"])


@router.get("/", response_model=list[VehicleTypeRead])
async def list_vehicle_types(db: AsyncSession = Depends(get_db)):
    return await crud.get_all(db)


@router.get("/{vehicle_type_id}", response_model=VehicleTypeRead)
async def get_vehicle_type(vehicle_type_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")
    return db_obj


@router.post("/", response_model=VehicleTypeRead, status_code=status.HTTP_201_CREATED)
async def create_vehicle_type(payload: VehicleTypeCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud.get_by_code(db, payload.code)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already exists")
    return await crud.create(db, payload)


@router.put("/{vehicle_type_id}", response_model=VehicleTypeRead)
async def update_vehicle_type(
    vehicle_type_id: uuid.UUID,
    payload: VehicleTypeUpdate,
    db: AsyncSession = Depends(get_db),
):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")

    if payload.code and payload.code != db_obj.code:
        existing = await crud.get_by_code(db, payload.code)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already exists")

    return await crud.update(db, db_obj, payload)


@router.delete("/{vehicle_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle_type(vehicle_type_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")
    await crud.delete(db, db_obj)
    return None