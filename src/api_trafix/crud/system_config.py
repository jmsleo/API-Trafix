from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.system_config import SystemConfig


async def get(db: AsyncSession, section: str, key: str) -> SystemConfig | None:
    result = await db.execute(
        select(SystemConfig).where(
            SystemConfig.section == section, SystemConfig.key == key
        )
    )
    return result.scalar_one_or_none()


async def get_section(db: AsyncSession, section: str) -> dict[str, dict]:
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.section == section)
    )
    return {row.key: row.value for row in result.scalars().all()}


async def upsert(db: AsyncSession, section: str, key: str, value: dict) -> SystemConfig:
    row = await get(db, section, key)
    if row is None:
        row = SystemConfig(section=section, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    await db.commit()
    await db.refresh(row)
    return row