import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from werkzeug.security import generate_password_hash

from api_trafix.config.database import get_db
from api_trafix.models import User
from api_trafix.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    user = User(
        name=data.name,
        username=data.username,
        password=generate_password_hash(data.password),
        role=data.role,
        status=data.status,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    await db.refresh(user)
    return user


@router.get("", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: uuid.UUID, data: UserUpdate, db: AsyncSession = Depends(get_db)):
    user = await get_user_or_404(db, user_id)
    updates = data.model_dump(exclude_unset=True)
    if "password" in updates and updates["password"]:
        updates["password"] = generate_password_hash(updates["password"])
    for field, value in updates.items():
        setattr(user, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    user = await get_user_or_404(db, user_id)
    await db.delete(user)
    await db.commit()
