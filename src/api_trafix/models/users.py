import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEKNISI = "teknisi"
    OPERATOR = "operator"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, values_callable=lambda e: [v.value for v in e], name="user_role"),
        nullable=False,
    )
    status = Column(
        Enum(UserStatus, values_callable=lambda e: [v.value for v in e], name="user_status"),
        nullable=False,
    )
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    members = relationship("Member", back_populates="created_by_user", foreign_keys="Member.created_by")
    audit_logs = relationship("AuditLog", back_populates="user")
