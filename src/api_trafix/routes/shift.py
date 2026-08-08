import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.crud import shift as crud
from api_trafix.schemas.shift import ShiftCreate, ShiftRead, ShiftUpdate

router = APIRouter(prefix="/shifts", tags=["Shifts"])


@router.get("/", response_model=list[ShiftRead])
async def list_shifts(db: AsyncSession = Depends(get_db)):
    return await crud.get_all(db)


@router.get("/{shift_id}", response_model=ShiftRead)
async def get_shift(shift_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return db_obj


@router.post("/", response_model=ShiftRead, status_code=status.HTTP_201_CREATED)
async def create_shift(payload: ShiftCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud.get_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists")
    return await crud.create(db, payload)


@router.put("/{shift_id}", response_model=ShiftRead)
async def update_shift(
    shift_id: uuid.UUID,
    payload: ShiftUpdate,
    db: AsyncSession = Depends(get_db),
):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    if payload.name and payload.name != db_obj.name:
        existing = await crud.get_by_name(db, payload.name)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists")

    return await crud.update(db, db_obj, payload)


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(shift_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    await crud.delete(db, db_obj)
    return None