import uuid
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.core.security import hash_password
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.schemas.user import UserCreate, UserUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    role: UserRole | None = None,
    status: UserStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[User], int]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if search:
        like = f"%{search.strip()}%"
        condition = or_(User.name.ilike(like), User.username.ilike(like))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if role is not None:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if status is not None:
        stmt = stmt.where(User.status == status)
        count_stmt = count_stmt.where(User.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(User.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def reset_password(
    db: AsyncSession, db_obj: User, new_password: str
) -> User:
    db_obj.password = hash_password(new_password)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, payload: UserCreate) -> User:
    data = payload.model_dump()
    plain_password = data.pop("password")
    db_obj = User(**data, password=hash_password(plain_password))
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: User, payload: UserUpdate) -> User:
    update_data = payload.model_dump(exclude_unset=True)
    if "password" in update_data and update_data["password"] is not None:
        update_data["password"] = hash_password(update_data["password"])
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def delete(db: AsyncSession, db_obj: User) -> None:
    await db.delete(db_obj)
    await db.commit()