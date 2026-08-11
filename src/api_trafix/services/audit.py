import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.audit_logs import AuditLog


async def log_action(
    db: AsyncSession,
    module: str,
    action: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    description: str | None = None,
    *,
    commit: bool = True,
) -> AuditLog:
    db_obj = AuditLog(
        user_id=user_id,
        role=role,
        module=module,
        action=action,
        description=description,
    )
    db.add(db_obj)
    if commit:
        await db.commit()
    return db_obj
