import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID

from api_trafix.config.database import Base


class GateType(str, enum.Enum):
    GATE_IN = "gate_in"
    GATE_OUT = "gate_out"


class GateStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class Gate(Base):
    __tablename__ = "gates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    # The wire id the LPR/gate hardware uses ("1", "2"), decoupled from the
    # UUID primary key. The gate cycle maps a device's gate number to this row.
    gate_code = Column(String(16), nullable=True, unique=True)
    type = Column(
        Enum(GateType, values_callable=lambda e: [v.value for v in e], name="gate_type"),
        nullable=False,
    )
    status = Column(
        Enum(GateStatus, values_callable=lambda e: [v.value for v in e], name="gate_status"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
