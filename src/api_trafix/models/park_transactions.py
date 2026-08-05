import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Enum, DateTime, ForeignKey, String, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base


class ParkingStatus(enum.Enum):
    PARKED = "Parked"
    COMPLETED = "Completed"
    VOID = "Void"


class DetectionMethod(enum.Enum):
    AUTO_LPR = "Auto_LPR"
    SCANNER = "Scanner"
    RFID = "RFID"
    MANUAL = "Manual"


class ParkTransaction(Base):
    __tablename__ = "park_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_number: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True
    )
    police_number: Mapped[str] = mapped_column(String, nullable=False)

    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_types.id"), nullable=False
    )
    member_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_vehicles.id"), nullable=True
    )

    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    exit_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    entry_gate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gates.id"), nullable=False
    )
    exit_gate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gates.id"), nullable=True
    )

    entry_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    exit_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True
    )

    entry_operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    exit_operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    parking_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parking_rates.id"), nullable=True
    )

    status_parking: Mapped[ParkingStatus] = mapped_column(
        Enum(
            ParkingStatus,
            values_callable=lambda e: [v.value for v in e],
            name="parking_status",
        ),
        nullable=False,
        default=ParkingStatus.PARKED,
    )
    is_member: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_fee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detection_method: Mapped[DetectionMethod] = mapped_column(
        Enum(
            DetectionMethod,
            values_callable=lambda e: [v.value for v in e],
            name="detection_method",
        ),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship internal (tabel 14-16)
    payments: Mapped[list["Payment"]] = relationship()