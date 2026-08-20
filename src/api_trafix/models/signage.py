import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class SignageStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SignageContentType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


class Signage(Base):
    __tablename__ = "signages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    location = Column(String(200), nullable=True)
    status = Column(
        Enum(SignageStatus, values_callable=lambda e: [v.value for v in e], name="signage_status"),
        nullable=False,
        default=SignageStatus.ACTIVE,
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    assignments = relationship("SignageAssignment", back_populates="signage", cascade="all, delete-orphan")
    schedules = relationship("SignageSchedule", back_populates="signage", cascade="all, delete-orphan")


class SignageContent(Base):
    __tablename__ = "signage_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(100), nullable=False)
    content_type = Column(
        Enum(
            SignageContentType,
            values_callable=lambda e: [v.value for v in e],
            name="signage_content_type",
        ),
        nullable=False,
        default=SignageContentType.TEXT,
    )
    body = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    file_path = Column(String(500), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    broadcast_start = Column(DateTime(timezone=True), nullable=True)
    broadcast_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    assignments = relationship("SignageAssignment", back_populates="content", cascade="all, delete-orphan")
    schedules = relationship("SignageSchedule", back_populates="content", cascade="all, delete-orphan")


class SignageAssignment(Base):
    __tablename__ = "signage_assignments"
    __table_args__ = (
        UniqueConstraint("signage_id", "content_id", name="uq_signage_assignment"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signage_id = Column(UUID(as_uuid=True), ForeignKey("signages.id"), nullable=False)
    content_id = Column(UUID(as_uuid=True), ForeignKey("signage_contents.id"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    signage = relationship("Signage", back_populates="assignments")
    content = relationship("SignageContent", back_populates="assignments")


class SignageSchedule(Base):
    __tablename__ = "signage_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signage_id = Column(UUID(as_uuid=True), ForeignKey("signages.id"), nullable=False)
    content_id = Column(UUID(as_uuid=True), ForeignKey("signage_contents.id"), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    signage = relationship("Signage", back_populates="schedules")
    content = relationship("SignageContent", back_populates="schedules")
