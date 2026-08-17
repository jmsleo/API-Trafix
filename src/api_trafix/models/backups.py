import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from api_trafix.config.database import Base


class BackupStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Backup(Base):
    __tablename__ = "backups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False, unique=True)
    format = Column(String(10), nullable=False, default="custom")
    size_bytes = Column(BigInteger, nullable=False, default=0)
    progress = Column(Integer, nullable=False, default=0)
    status = Column(
        Enum(BackupStatus, values_callable=lambda e: [v.value for v in e], name="backup_status"),
        nullable=False,
        default=BackupStatus.COMPLETED,
    )
    error_message = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_restored_at = Column(DateTime(timezone=True), nullable=True)
    last_restored_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
