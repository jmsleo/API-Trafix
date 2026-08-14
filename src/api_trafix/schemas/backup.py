from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models import BackupStatus


class BackupRestoreRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    confirm: bool = True


class BackupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    format: str
    size_bytes: int
    progress: int = 0
    status: BackupStatus
    error_message: str | None
    created_by: UUID | None
    last_restored_at: datetime | None
    last_restored_by: UUID | None
    created_at: datetime
    updated_at: datetime


class BackupPage(BaseModel):
    items: list[BackupRead]
    total: int
    page: int
    page_size: int
    total_pages: int
