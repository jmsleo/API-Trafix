import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.core.security import hash_password
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _count_active_admins(db: AsyncSession, exclude_id: uuid.UUID | None = None) -> int:
    query = select(func.count()).select_from(User).where(
        User.role == UserRole.ADMIN,
        User.status == UserStatus.ACTIVE,
    )
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return await db.scalar(query)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = User(
        name=data.name,
        username=data.username,
        password=hash_password(data.password),
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
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    return await get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    user = await get_user_or_404(db, user_id)

    if user.id == current_admin.id:
        if "status" in data.model_fields_set and data.status is not None and data.status.value != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins cannot deactivate their own account",
            )
        if "role" in data.model_fields_set and data.role is not None and data.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins cannot change their own role",
            )

    if user.role == UserRole.ADMIN and user.status.value == "active":
        active_admins = await _count_active_admins(db, exclude_id=user.id)
        if active_admins == 0 and (
            ("role" in data.model_fields_set and data.role is not None and data.role != UserRole.ADMIN)
            or ("status" in data.model_fields_set and data.status is not None and data.status.value != "active")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote or deactivate the last active admin",
            )

    updates = data.model_dump(exclude_unset=True)
    if "password" in updates and updates["password"]:
        updates["password"] = hash_password(updates["password"])
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
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot delete their own account",
        )

    user = await get_user_or_404(db, user_id)

    if user.role == UserRole.ADMIN and user.status.value == "active":
        active_admins = await _count_active_admins(db, exclude_id=user.id)
        if active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last active admin",
            )

    await db.delete(user)
    await db.commit()
