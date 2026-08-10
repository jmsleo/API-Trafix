import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.gates import Gate


async def get_by_id(db: AsyncSession, gate_id: uuid.UUID) -> Gate | None:
    result = await db.execute(select(Gate).where(Gate.id == gate_id))
    return result.scalar_one_or_none()
