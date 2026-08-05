import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class MemberStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class Member(Base):
    __tablename__ = "members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_code = Column(String(50), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=True)
    phone_number = Column(String(20), nullable=True)
    status = Column(
        Enum(MemberStatus, values_callable=lambda e: [v.value for v in e], name="member_status"),
        nullable=False,
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    created_by_user = relationship("User", back_populates="members", foreign_keys=[created_by])
