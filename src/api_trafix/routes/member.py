import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.crud import member as crud
from api_trafix.models import MemberStatus
from api_trafix.schemas.member import MemberCreate, MemberPage, MemberRead, MemberUpdate

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=MemberPage)
async def list_members(
    search: str | None = Query(default=None, max_length=100),
    status_filter: MemberStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return MemberPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{member_id}", response_model=MemberRead)
async def get_member(member_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return db_obj


@router.post("/", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(payload: MemberCreate, db: AsyncSession = Depends(get_db)):
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
    return await crud.update(db, db_obj, payload)


@router.patch("/{member_id}/block", response_model=MemberRead)
async def block_member(member_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return await crud.block(db, db_obj)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(member_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await crud.delete(db, db_obj)
    return None