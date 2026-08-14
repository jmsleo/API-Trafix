import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api_trafix.config.database import Base


class GateEvent(Base):
    """Audit trail of gate hardware decisions.

    Ported from the mock's ``gate_events`` table. The production system kept no
    record of what the gate hardware did, which is why the wire protocol had to
    be reconstructed from a packet capture. Every gate-in / gate-out decision
    is recorded here so the next person does not need Wireshark.

    ``gate_code`` is the wire gate id ("1", "2"), not the gates UUID — the
    hardware never learns the UUID.
    """

    __tablename__ = "gate_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
