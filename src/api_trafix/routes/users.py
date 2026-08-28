import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import users as crud
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.schemas.user import PasswordReset, UserCreate, UserPage, UserRead, UserUpdate
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=UserPage)
async def list_users(
    search: str | None = Query(default=None, max_length=100),
    role_filter: UserRole | None = Query(default=None, alias="role"),
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, search=search, role=role_filter, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return UserPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, user_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pengguna tidak ditemukan")
    return db_obj


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    existing = await crud.get_by_username(db, payload.username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username sudah digunakan")
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="user",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created user '{db_obj.username}' with role {db_obj.role.value}",
    )
    return db_obj


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, user_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pengguna tidak ditemukan")

    if payload.username and payload.username != db_obj.username:
        existing = await crud.get_by_username(db, payload.username)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username sudah digunakan")

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="user",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated user '{db_obj.username}'",
    )
    return db_obj


@router.post("/{user_id}/reset-password", response_model=UserRead)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, user_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pengguna tidak ditemukan")
    if payload.password.lower() == db_obj.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password tidak boleh sama dengan username",
        )
    db_obj = await crud.reset_password(db, db_obj, payload.password)
    await log_action(
        db,
        module="user",
        action="reset-password",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Reset password for user '{db_obj.username}'",
    )
    return db_obj


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, user_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pengguna tidak ditemukan")
    await log_action(
        db,
        module="user",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted user '{db_obj.username}'",
    )
    await crud.delete(db, db_obj)
    return None