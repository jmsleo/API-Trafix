import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.crud import member as crud
from api_trafix.schemas.member import MemberCreate, MemberRead, MemberUpdate

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=list[MemberRead])
async def list_members(db: AsyncSession = Depends(get_db)):
    return await crud.get_all(db)


@router.get("/{member_id}", response_model=MemberRead)
async def get_member(member_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return db_obj


@router.post("/", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud.get_by_member_code(db, payload.member_code)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Member code already exists")
    return await crud.create(db, payload)


@router.put("/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: uuid.UUID,
    payload: MemberUpdate,
    db: AsyncSession = Depends(get_db),
):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if payload.member_code and payload.member_code != db_obj.member_code:
        existing = await crud.get_by_member_code(db, payload.member_code)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Member code already exists")

    return await crud.update(db, db_obj, payload)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(member_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await crud.delete(db, db_obj)
    return None