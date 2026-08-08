import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.core.security import hash_password
from api_trafix.models.users import User
from api_trafix.schemas.user import UserCreate, UserUpdate


async def get_all(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.name))
    return list(result.scalars().all())


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