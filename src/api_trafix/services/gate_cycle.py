"""The business logic of the gate-in / gate-out cycle, independent of HTTP.

A faithful async port of ``trafix-api-mock/trafix/service.py`` (itself a port
of ``GateController::gatein`` and the ``GateOut*`` family from the Laravel
app), mapped onto the modern API-Trafix schema:

* ``transactions``        -> :class:`api_trafix.models.ParkTransaction`
* ``parking_fees``        -> :class:`api_trafix.models.ParkingRate`
* ``vehicles``            -> :class:`api_trafix.models.VehicleType` (wire id
  1-4 <-> ``vehicle_types.code``, see :mod:`services.vehicles`)
* ``members``             -> ``members`` + ``member_vehicles`` +
  ``member_subscriptions``, flattened into :class:`MemberContext` so the fee
  rules keep the exact signature they had in the mock
* ``locations``           -> :class:`GateCycleConfig` (store name / address)
* the QRIS pool           -> dropped; this port is cash-only, so the printed
  QR *is* the ticket code

Keeping this out of the FastAPI layer means the whole check-in/check-out cycle
can be tested with a database and nothing else: no HTTP, no broker.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from api_trafix.models import (
    Gate,
    GateEvent,
    Member,
    MemberSubscription,
    MemberVehicle,
    ParkingRate,
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentMethod,
    PaymentStatus,
    RateStatus,
    VehicleStatus,
    VehicleType,
)
from api_trafix.services import escpos, rates
from api_trafix.services import vehicles as vehicles_module
from api_trafix.services.vehicles import vehicle_id_of, vehicle_name, vehicle_type_id

log = logging.getLogger(__name__)

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
WIB = timezone(timedelta(hours=7))

# Result statuses, matching the strings the Laravel API returns so an existing
# frontend keeps working.
STATUS_SUCCESS = "success"
STATUS_SUCCESS_MEMBER = "success_member"
STATUS_SUCCESS_TICKET = "success_ticket"
STATUS_TICKET_USED = "ticket_used"
STATUS_NOT_FOUND = "notfound"
STATUS_ALREADY_PAID = "already_paid"
STATUS_PLATE_MISMATCH = "plate_mismatch"
STATUS_MEMBER_EXPIRED = "member_expired"
STATUS_FAILED_MEMBER = "failed_member"

# The wire id of the class recorded when the entry cannot distinguish classes.
DEFAULT_VEHICLE_ID = 1  # Motor


class GateCycleError(RuntimeError):
    """Raised when the site is not configured for the gate cycle to run."""


def now_string() -> str:
    return format_wib(datetime.now(UTC))


def format_wib(value: datetime | None) -> str | None:
    """Render an aware UTC timestamp the way the wire shows it (WIB, naive)."""
    if value is None:
        return None
    return value.astimezone(WIB).strftime(DATETIME_FORMAT)


def normalize_plate(plate: str | None) -> str | None:
    """Strip spacing and case so two reads can be compared.

    flow.md §7.7: the entry and exit cameras produce different strings for what
    may be the same vehicle. Normalising is necessary but nowhere near
    sufficient — which is why the plate is advisory, not a lookup key.
    """
    if not plate:
        return None
    cleaned = "".join(ch for ch in plate.upper() if ch.isalnum())
    return cleaned or None


def plates_equal(a: str | None, b: str | None) -> bool:
    """Compare two plate strings ignoring spacing and case."""
    na, nb = normalize_plate(a), normalize_plate(b)
    return na is not None and na == nb


class Publisher(Protocol):
    """How the service reaches the gate hardware."""

    async def print_ticket(self, gate: str, blocks: list[dict], message_id: str) -> None: ...

    async def open_barrier(self, gate: str, *, exit_lane: bool = False) -> None: ...


class NullPublisher:
    """Used in tests and when the service runs without a broker."""

    def __init__(self) -> None:
        self.printed: list[tuple[str, list[dict]]] = []
        self.barriers: list[tuple[str, bool]] = []

    async def print_ticket(self, gate: str, blocks: list[dict], message_id: str) -> None:
        self.printed.append((gate, blocks))

    async def open_barrier(self, gate: str, *, exit_lane: bool = False) -> None:
        self.barriers.append((gate, exit_lane))


@dataclass
class GateInResult:
    status: str
    transaction_code: str
    transaction_id: UUID
    plate: str | None
    image_path: str
    type_qr: str


@dataclass
class MemberGateInResult:
    """The outcome of an RFID member auto-entry."""

    status: str
    transaction_code: str | None = None
    member_name: str | None = None
    member_code: str | None = None
    plate: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS


@dataclass
class GateOutResult:
    status: str
    transaction_code: str | None = None
    card_number: str | None = None
    total: float = 0.0
    duration: str = ""
    plate_in: str | None = None
    plate_out: str | None = None
    plate_match: bool | None = None
    is_member: bool = False
    member_name: str | None = None
    time_checkin: str | None = None
    time_checkout: str | None = None
    cam_in: str | None = None
    cam_out: str | None = None
    breakdown: str = ""
    message: str | None = None
    vehicle_id: int | None = None
    admin_id: int | None = None
    shift_id: int | None = None
    payment_status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (
            STATUS_SUCCESS,
            STATUS_SUCCESS_MEMBER,
            STATUS_SUCCESS_TICKET,
        )


@dataclass
class PosActionResult:
    """The outcome of a POS action (void, reprint, receipt)."""

    status: str
    transaction_code: str | None = None
    message: str | None = None
    blocks_printed: int = 0
    refunded: int = 0
    total: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS


@dataclass
class LprGateOutQuote:
    """The transaction facts ``checkLprImageGateOut`` answers with."""

    status: str
    transaction_id: UUID
    transaction_code: str
    police_number: str | None
    card_number: str | None
    vehicle_id: int | None
    vehicle_name: str | None
    time_checkin: str | None
    gate_in: str | None
    gate_status: str | None
    payment_status: str | None
    cam_in: str | None
    camin_lpr: str | None
    gate_out: str | None
    cam_out: str | None
    camout_lpr: str | None


@dataclass(frozen=True)
class GateCycleConfig:
    """Site configuration the gate cycle reads. Stands in for the mock's
    ``locations`` row and the ``policies`` block."""

    site_name: str
    site_address: str
    storage_dir: Path
    require_plate_match: bool = False
    command_exit_barrier: bool = True


@dataclass
class MemberContext:
    """A member flattened for the fee rules.

    ``vehicle_id`` is the wire id and ``time_limit`` the subscription end date,
    matching the two attributes ``rates.is_active_member`` reads.
    """

    id: UUID
    name: str
    member_code: str
    card_number: str | None
    police_number: str | None
    vehicle_id: int | None
    time_limit: date | None


async def find_member_by_plate(
    db: AsyncSession, plate: str | None
) -> MemberContext | None:
    """Resolve a plate to a member, tolerating spacing differences.

    Member plates are stored as typed (``H 1234 CD``) while transactions store
    the normalised form (``H1234CD``) and the cashier may type either. The
    lookup compares normalised values on both sides.
    """
    if not normalize_plate(plate):
        return None
    vehicles = (
        await db.execute(
            select(MemberVehicle).options(
                selectinload(MemberVehicle.vehicle_type)
            )
        )
    ).scalars().all()
    for vehicle in vehicles:
        if not plates_equal(vehicle.police_number, plate):
            continue
        member = await db.get(Member, vehicle.member_id)
        if member is None:
            continue
        return await _member_context(db, member, vehicle)
    return None


async def find_member_by_card(db: AsyncSession, card_no: str) -> MemberContext | None:
    """Resolve an RFID tag to a member."""
    card_no = str(card_no or "").strip()
    if not card_no:
        return None
    member = await db.scalar(
        select(Member).where(Member.card_number == card_no)
    )
    if member is None:
        return None
    vehicle = (
        await db.execute(
            select(MemberVehicle)
            .where(MemberVehicle.member_id == member.id)
            .options(selectinload(MemberVehicle.vehicle_type))
            .order_by(MemberVehicle.created_at)
        )
    ).scalars().first()
    return await _member_context(db, member, vehicle)


async def _member_context(
    db: AsyncSession, member: Member, vehicle: MemberVehicle | None
) -> MemberContext:
    subscription = await db.scalar(
        select(MemberSubscription)
        .where(MemberSubscription.member_id == member.id)
        .order_by(MemberSubscription.end_date.desc())
        .limit(1)
    )
    vehicle_id = None
    if vehicle is not None and vehicle.vehicle_type is not None:
        vehicle_id = vehicles_module.VEHICLE_IDS.get(vehicle.vehicle_type.code)
    time_limit = None
    if subscription is not None and subscription.end_date is not None:
        time_limit = subscription.end_date.date()
    return MemberContext(
        id=member.id,
        name=member.name,
        member_code=member.member_code,
        card_number=member.card_number,
        police_number=vehicle.police_number if vehicle is not None else None,
        vehicle_id=vehicle_id,
        time_limit=time_limit,
    )


async def gate_uuid(db: AsyncSession, gate_code: str) -> UUID | None:
    """The gates UUID for a wire gate id ("1", "2")."""
    gate = await db.scalar(select(Gate).where(Gate.gate_code == gate_code))
    return gate.id if gate is not None else None


class GateCycleService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        publisher: Publisher | None = None,
        storage=None,
        config: GateCycleConfig | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        print_gap_seconds: float = 0.2,
    ) -> None:
        self.session_factory = session_factory
        self.publisher: Publisher = publisher or NullPublisher()
        self.storage = storage
        self.config = config
        self.clock = clock
        # The gap between the two halves of the ticket. The real controller
        # drops the second half if they arrive back to back, which is why the
        # PHP has usleep(200000). Tests set this to zero.
        self.print_gap_seconds = print_gap_seconds
        # Per-gate locks so one ticket's two print halves are published
        # contiguously. The QR is stored in half one but printed in half two,
        # so a second, overlapping gate-in can otherwise overwrite the real
        # printer's QR buffer before the first ticket prints — putting the
        # wrong code on the paper.
        self._print_locks: dict[str, asyncio.Lock] = {}

    def _print_lock(self, gate: str) -> asyncio.Lock:
        lock = self._print_locks.get(gate)
        if lock is None:
            lock = self._print_locks[gate] = asyncio.Lock()
        return lock

    async def _publish_ticket(
        self,
        gate: str,
        transaction_code: str,
        blocks_1: list[dict],
        blocks_2: list[dict],
    ) -> None:
        """Publish the two halves of a ticket, contiguously for this gate.

        The QR is stored in the first half but printed in the second, so a
        concurrent gate-in squeezing between the two messages can overwrite the
        real printer's stored QR before it prints — the paper then carries
        another ticket's code. The per-gate lock keeps one ticket's halves
        together.
        """
        from api_trafix.services.protocol import message_id

        async with self._print_lock(gate):
            await self.publisher.print_ticket(
                gate, blocks_1, message_id(transaction_code, 1)
            )
            if self.print_gap_seconds:
                await asyncio.sleep(self.print_gap_seconds)
            await self.publisher.print_ticket(
                gate, blocks_2, message_id(transaction_code, 2)
            )

    # -- helpers -----------------------------------------------------------

    async def generate_transaction_code(self, db: AsyncSession) -> str:
        """Port of ``generateTrxCode()``: 7 digits of epoch ms + 3 random.

        Collision-checked against the table, as the original is.
        """
        milliseconds = int(time.time() * 1000)
        time_part = str(milliseconds)[-7:]
        for _ in range(1000):
            candidate = f"{time_part}{random.randint(0, 999):03d}"
            exists = await db.scalar(
                select(ParkTransaction.id).where(
                    ParkTransaction.ticket_number == candidate
                )
            )
            if not exists:
                return candidate
        raise GateCycleError("could not allocate a unique transaction code")

    def _log_event(
        self,
        db: AsyncSession,
        *,
        source: str,
        method: str,
        gate: str | None = None,
        transaction_code: str | None = None,
        detail: str | None = None,
    ) -> None:
        db.add(
            GateEvent(
                source=source,
                method=method,
                gate_code=gate,
                ticket_number=transaction_code,
                detail=detail,
            )
        )

    async def _rate_for(self, db: AsyncSession, vehicle_id: int | None) -> ParkingRate | None:
        """The active tariff for a wire vehicle id, else None."""
        resolved = await vehicle_type_id(db, vehicle_id)
        if resolved is None:
            return None
        return await self._rate_for_vehicle_type(db, resolved)

    async def _rate_for_vehicle_type(
        self, db: AsyncSession, vehicle_type_id: UUID | None
    ) -> ParkingRate | None:
        """The active tariff for a vehicle_types UUID, else None."""
        if vehicle_type_id is None:
            return None
        return await db.scalar(
            select(ParkingRate)
            .where(
                ParkingRate.vehicle_type_id == vehicle_type_id,
                ParkingRate.status == RateStatus.ACTIVE,
            )
            .order_by(ParkingRate.created_at.desc())
        )

    def _allocate_qr(self, transaction_code: str) -> tuple[str, str]:
        """Cash-only port: the printed QR *is* the ticket code.

        The mock's QRIS pool is deliberately absent — no Xendit integration in
        this port, so every ticket is a cash ticket.
        """
        return escpos.TYPE_QR_CASH, transaction_code

    async def _build_ticket(
        self,
        db: AsyncSession,
        *,
        gate: str,
        transaction_code: str,
        qr_string: str,
        type_qr: str,
        vehicle_id: int | None,
        plate: str | None,
        checkin_at: str,
    ) -> tuple[list[dict], list[dict]]:
        motor = await self._rate_for(db, DEFAULT_VEHICLE_ID)
        mobil = await self._rate_for(db, 2)
        vehicle = await vehicle_name(db, vehicle_id)

        header = escpos.TicketHeader(
            store_name=self.config.site_name if self.config else "",
            store_address=self.config.site_address if self.config else "",
            qris=qr_string,
            type_qr=type_qr,
        )
        body = escpos.TicketBody(
            gate=gate,
            datetime=checkin_at,
            trx=transaction_code,
            vehicle=vehicle,
            lost_motor=motor.ticket_charge if motor else 0,
            lost_car=mobil.ticket_charge if mobil else 0,
            stay_motor=motor.stay_charge if motor else 0,
            stay_car=mobil.stay_charge if mobil else 0,
            police_number=plate,
            type_qr=type_qr,
        )
        return escpos.build_gate_in_1(header), escpos.build_gate_in_2(body)

    # -- check-in ----------------------------------------------------------

    async def gate_in(
        self,
        *,
        gate: str,
        vehicle_id: int | None,
        plate_num: str | None,
        url_gambar: str | None,
        serial_no: str,
        ipcam: str | None = None,
    ) -> GateInResult:
        """A driver pressed the ticket button. Port of ``gatein()``."""
        async with self.session_factory() as session:
            gate_id = await gate_uuid(session, gate)
            if gate_id is None:
                raise GateCycleError(f"unknown gate {gate!r}")

            transaction_code = await self.generate_transaction_code(session)

            # Fetch the snapshot the LPR advertised. Off the request path: a
            # slow camera must never hold the barrier shut.
            image_path = "-"
            if url_gambar and self.storage is not None:
                if url_gambar.startswith("storage/"):
                    # The push-style camera uploaded the image straight to us;
                    # it is already on disk under the /storage mount.
                    image_path = url_gambar
                else:
                    image_path = self.storage.download_async(
                        url_gambar,
                        "lpr/gatein",
                        self.storage.lpr_filename(url_gambar),
                    )
            elif url_gambar:
                image_path = url_gambar

            type_qr, qr_string = self._allocate_qr(transaction_code)

            plate = normalize_plate(plate_num)
            checkin_at = self.clock()
            wire_checkin = format_wib(checkin_at)

            transaction = ParkTransaction(
                ticket_number=transaction_code,
                entry_time=checkin_at,
                status_parking=ParkingStatus.PARKED,
                entry_gate_id=gate_id,
                vehicle_type_id=await _coerce_vehicle(session, vehicle_id),
                cam_in=image_path,
                camin_lpr=image_path,
                police_number=plate,
                payment_type="cash",
                detection_method=DetectionMethodForWire.SCANNER,
            )
            session.add(transaction)
            await session.flush()

            self._log_event(
                session,
                source="api",
                method="gatein",
                gate=gate,
                transaction_code=transaction_code,
                detail=f"plate={plate or '(none)'} typeqr={type_qr}",
            )

            blocks_1, blocks_2 = await self._build_ticket(
                session,
                gate=gate,
                transaction_code=transaction_code,
                qr_string=qr_string,
                type_qr=type_qr,
                vehicle_id=vehicle_id,
                plate=plate,
                checkin_at=wire_checkin,
            )
            transaction_id = transaction.id
            await session.commit()

        # Two publishes, separated exactly as the PHP's usleep(200000) does,
        # serialised per gate so a concurrent gate-in cannot interleave its
        # QR-store half between them.
        await self._publish_ticket(gate, transaction_code, blocks_1, blocks_2)

        log.info(
            "gate %s: issued ticket %s for plate %s",
            gate,
            transaction_code,
            plate or "(none)",
        )
        return GateInResult(
            status=STATUS_SUCCESS,
            transaction_code=transaction_code,
            transaction_id=transaction_id,
            plate=plate,
            image_path=image_path,
            type_qr=type_qr,
        )

    async def member_gate_in(
        self,
        *,
        gate: str,
        card_no: str,
        serial_no: str,
        vehicle_id: int | None = None,
    ) -> MemberGateInResult:
        """A member tapped an RFID card at the entry. No ticket is printed.

        Mirrors the on-site ``readCard`` event (flow.md §5): the tag is resolved
        against ``members.card_number``; an active member for this vehicle class
        gets a transaction and the barrier opens. Unknown cards and expired
        subscriptions are rejected — the barrier stays shut.
        """
        card_no = str(card_no or "").strip()
        if not card_no:
            return MemberGateInResult(
                status=STATUS_NOT_FOUND, message="Nomor kartu tidak diisi"
            )

        async with self.session_factory() as session:
            member = await find_member_by_card(session, card_no)
            if member is None:
                log.info("gate %s: card %s is not a member", gate, card_no)
                return MemberGateInResult(
                    status=STATUS_NOT_FOUND,
                    message=f"Tidak ada member yang ditemukan untuk kartu {card_no}",
                )

            if not rates.is_active_member(member, vehicle_id):
                log.warning(
                    "gate %s: card %s belongs to %s but the subscription is "
                    "expired or the vehicle class mismatches",
                    gate,
                    card_no,
                    member.name,
                )
                return MemberGateInResult(
                    status=STATUS_MEMBER_EXPIRED,
                    member_name=member.name,
                    member_code=member.member_code,
                    plate=member.police_number,
                    message="Langganan member kedaluwarsa atau kelas kendaraan tidak sesuai",
                )

            gate_id = await gate_uuid(session, gate)
            if gate_id is None:
                raise GateCycleError(f"unknown gate {gate!r}")

            transaction_code = await self.generate_transaction_code(session)
            checkin_at = self.clock()

            transaction = ParkTransaction(
                ticket_number=transaction_code,
                entry_time=checkin_at,
                status_parking=ParkingStatus.PARKED,
                entry_gate_id=gate_id,
                vehicle_type_id=await _coerce_vehicle(
                    session, member.vehicle_id or vehicle_id
                ),
                police_number=member.police_number,
                card_number=card_no,
                is_member=True,
                total_fee=0,
                payment_status="lunas",
                cam_in="-",
                camin_lpr="-",
                payment_type="cash",
                detection_method=DetectionMethodForWire.RFID,
            )
            session.add(transaction)
            await session.flush()

            self._log_event(
                session,
                source="api",
                method="gatein-card",
                gate=gate,
                transaction_code=transaction_code,
                detail=f"card={card_no} member={member.name}",
            )
            await session.commit()

        log.info(
            "gate %s: member %s entered on card %s (ticket %s)",
            gate,
            member.name,
            card_no,
            transaction_code,
        )
        return MemberGateInResult(
            status=STATUS_SUCCESS,
            transaction_code=transaction_code,
            member_name=member.name,
            member_code=member.member_code,
            plate=member.police_number,
        )

    # -- LPR-direct entry (POST /api/lpr/gatein, /api/lpr/gateinimage) -----

    def _store_upload(self, filename: str, content: bytes) -> str:
        """Persist a file an LPR unit uploaded directly.

        Falls back to ``config.storage_dir`` when no ``SnapshotStore`` was
        wired (tests). Returns the ``storage/<filename>`` value the
        ``/storage`` mount serves back, matching ``storeAs('public', …)``.
        """
        if self.storage is not None:
            return self.storage.save_upload(filename, content)
        if self.config is not None:
            target = Path(self.config.storage_dir) / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return f"storage/{filename}"
        raise GateCycleError("no storage configured to accept an upload")

    async def lpr_gate_in(self, *, plate: str, image: bytes) -> GateInResult:
        """Port of ``GateController::GateInLpr`` (:428).

        The entry LPR unit reports a plate and uploads its photo; a transaction
        is opened from that alone. No ticket is printed and no QR allocated —
        the raw PHP creates the row and nothing else.
        """
        normalized = normalize_plate(plate)
        async with self.session_factory() as session:
            gate_id = await gate_uuid(session, "1")
            if gate_id is None:
                raise GateCycleError("gate '1' is not configured")
            transaction_code = await self.generate_transaction_code(session)
            filename = f"CAMIN_LPR_{transaction_code}_{int(time.time())}.jpg"
            image_path = self._store_upload(filename, image)
            checkin_at = self.clock()

            transaction = ParkTransaction(
                ticket_number=transaction_code,
                entry_time=checkin_at,
                status_parking=ParkingStatus.PARKED,
                entry_gate_id=gate_id,
                vehicle_type_id=await _coerce_vehicle(session, None),
                police_number=normalized,
                cam_in=image_path,
                camin_lpr=image_path,
                detection_method=DetectionMethodForWire.AUTO_LPR,
            )
            session.add(transaction)
            await session.flush()
            transaction_id = transaction.id

            self._log_event(
                session,
                source="api",
                method="lpr-gatein",
                gate="1",
                transaction_code=transaction_code,
                detail=f"plate={normalized}",
            )
            await session.commit()

        log.info("LPR gate-in: opened %s for plate %s", transaction_code, normalized)
        return GateInResult(
            status=STATUS_SUCCESS,
            transaction_code=transaction_code,
            transaction_id=transaction_id,
            plate=normalized,
            image_path=image_path,
            type_qr=escpos.TYPE_QR_CASH,
        )

    async def attach_gatein_image(
        self, *, transaction_code: str, plate: str | None, image: bytes
    ) -> dict:
        """Port of ``GateController::GateinImageLpr`` (:387).

        Attaches the LPR photo to an open session looked up by its ticket code
        or member card, and records the plate read.
        """
        async with self.session_factory() as session:
            transaction = await session.scalar(
                select(ParkTransaction)
                .where(
                    (ParkTransaction.ticket_number == transaction_code)
                    | (
                        (ParkTransaction.card_number == transaction_code)
                        & ParkTransaction.exit_time.is_(None)
                    )
                )
                .order_by(ParkTransaction.updated_at.desc())
                .limit(1)
            )
            if transaction is None:
                return {"status": STATUS_NOT_FOUND, "message": "Transaksi tidak ditemukan"}

            filename = f"CAMIN_LPR_{transaction_code}_{int(time.time())}.jpg"
            image_path = self._store_upload(filename, image)
            normalized = normalize_plate(plate)
            if normalized:
                transaction.police_number = normalized
            transaction.camin_lpr = image_path

            self._log_event(
                session,
                source="api",
                method="lpr-gateinimage",
                gate=_gate_code_of(transaction.entry_gate_id, await _gate_codes(session)),
                transaction_code=transaction.ticket_number,
                detail=f"image={image_path}",
            )
            await session.commit()

        code = (
            transaction.ticket_number
            if transaction.ticket_number == transaction_code
            else transaction.card_number
        )
        return {
            "status": STATUS_SUCCESS,
            "camin_lpr": image_path,
            "transaction_code": code,
        }

    async def find_open_plate_code(self, *, plate: str) -> str | None:
        """Ticket code of the open session for a plate, else None.

        Backs ``checkLprImage``; the URL probe itself stays in the HTTP layer.
        """
        async with self.session_factory() as session:
            transaction = await self.find_open_transaction(session, plate=plate)
            return transaction.ticket_number if transaction is not None else None

    # -- lookup ------------------------------------------------------------

    async def find_open_transaction(
        self, db: AsyncSession, *, code: str | None = None, plate: str | None = None
    ) -> ParkTransaction | None:
        """Locate the parking session a vehicle at the exit belongs to.

        **The ticket code is authoritative and the plate is advisory.** flow.md
        §7.7 shows why: the two cameras disagree, and 4 of 6 entry tickets
        recorded no plate at all, so a plate can never be the primary key.

        ``exit_time IS NULL`` decides whether a car is still inside.
        """
        if code:
            transaction = await db.scalar(
                select(ParkTransaction)
                .where(ParkTransaction.ticket_number == code)
                .order_by(ParkTransaction.created_at.desc())
                .limit(1)
            )
            if transaction is not None:
                return transaction

            # A member's RFID tag. The cashier types it in place of a ticket
            # code; the card is reused every visit, so only the open session
            # matches.
            transaction = await db.scalar(
                select(ParkTransaction)
                .where(
                    ParkTransaction.card_number == code,
                    ParkTransaction.exit_time.is_(None),
                )
                .order_by(ParkTransaction.entry_time.desc())
                .limit(1)
            )
            if transaction is not None:
                return transaction

        normalized = normalize_plate(plate)
        if normalized:
            transaction = await db.scalar(
                select(ParkTransaction)
                .where(
                    ParkTransaction.police_number == normalized,
                    ParkTransaction.exit_time.is_(None),
                )
                .order_by(ParkTransaction.entry_time.desc())
                .limit(1)
            )
            if transaction is not None:
                return transaction
            # Member plates are stored as typed (``H 1234 CD``) while the
            # cashier's lookup is normalised. Resolve the plate to a member and
            # find that member's open session so a cashier typing only the
            # plate can settle a member's car.
            member = await find_member_by_plate(db, normalized)
            if member is not None and member.card_number:
                transaction = await db.scalar(
                    select(ParkTransaction)
                    .where(
                        ParkTransaction.card_number == member.card_number,
                        ParkTransaction.exit_time.is_(None),
                    )
                    .order_by(ParkTransaction.entry_time.desc())
                    .limit(1)
                )
                if transaction is not None:
                    return transaction
        return None

    async def quote(
        self,
        *,
        code: str | None = None,
        plate: str | None = None,
        lost: bool = False,
        vehicle_id: int | None = None,
        vehicle_type_id: UUID | None = None,
    ) -> GateOutResult:
        """What would this vehicle pay? Read-only — nothing is written.

        Backs the cashier's ``detailtransaction`` screen.
        """
        async with self.session_factory() as session:
            transaction = await self.find_open_transaction(session, code=code, plate=plate)
            if transaction is None:
                return GateOutResult(
                    status=STATUS_NOT_FOUND,
                    message="Transaksi aktif tidak ditemukan",
                )
            return await self._price(
                session,
                transaction,
                plate_out=plate,
                lost=lost,
                vehicle_id=vehicle_id,
                vehicle_type_id=vehicle_type_id,
            )

    async def quote_gateout_image(self, *, plate: str) -> LprGateOutQuote | None:
        """The transaction facts ``checkLprImageGateOut`` reports, or None.

        Read-only plate lookup; the image availability probe is performed by
        the HTTP layer because it is a side-effecting network call.
        """
        async with self.session_factory() as session:
            transaction = await self.find_open_transaction(session, plate=plate)
            if transaction is None:
                return None
            vehicle_id = await vehicle_id_of(session, transaction.vehicle_type_id)
            vehicle = (
                await vehicle_name(session, vehicle_id) if vehicle_id is not None else None
            )
            return LprGateOutQuote(
                status=STATUS_SUCCESS,
                transaction_id=transaction.id,
                transaction_code=transaction.ticket_number or "",
                police_number=normalize_plate(transaction.police_number),
                card_number=transaction.card_number,
                vehicle_id=vehicle_id,
                vehicle_name=vehicle,
                time_checkin=format_wib(transaction.entry_time),
                gate_in=_gate_code_of(transaction.entry_gate_id, await _gate_codes(session)),
                gate_status="in" if transaction.exit_time is None else "out",
                payment_status=transaction.payment_status,
                cam_in=transaction.cam_in,
                camin_lpr=transaction.camin_lpr,
                gate_out=_gate_code_of(transaction.exit_gate_id, await _gate_codes(session)),
                cam_out=transaction.cam_out,
                camout_lpr=transaction.camout_lpr,
            )

    async def _price(
        self,
        db: AsyncSession,
        transaction: ParkTransaction,
        *,
        plate_out: str | None,
        lost: bool = False,
        vehicle_id: int | None = None,
        vehicle_type_id: UUID | None = None,
    ) -> GateOutResult:
        # The cashier's selection wins when given (explicit vehicle_type_id
        # first, then the legacy wire id); otherwise the class recorded at
        # entry decides.
        entry_vehicle_id = await vehicle_id_of(db, transaction.vehicle_type_id)

        tariff_row = None
        flat_tariff = None
        chosen_wire_id: int | None = None
        if vehicle_type_id is not None:
            chosen = await db.get(VehicleType, vehicle_type_id)
            if chosen is not None:
                chosen_wire_id = await vehicle_id_of(db, chosen.id)
                tariff_row = await self._rate_for_vehicle_type(db, chosen.id)
                if tariff_row is None and chosen.price is not None:
                    flat_tariff = _flat_tariff_from_price(chosen.price)
        if tariff_row is None and flat_tariff is None:
            chosen_wire_id = vehicle_id or entry_vehicle_id
            tariff_row = await self._rate_for(db, chosen_wire_id)

        member = None
        if transaction.police_number:
            member = await find_member_by_plate(db, transaction.police_number)

        check_in = transaction.entry_time
        check_out = self.clock()

        if tariff_row is not None:
            fee = rates.calculate(
                rates.Tariff.from_row(tariff_row),
                check_in,
                check_out,
                vehicle_id=chosen_wire_id,
                member=member,
                type=rates.TYPE_LOST if lost else rates.TYPE_NORMAL,
            )
        elif flat_tariff is not None:
            fee = rates.calculate(
                flat_tariff,
                check_in,
                check_out,
                member=member,
                type=rates.TYPE_LOST if lost else rates.TYPE_NORMAL,
            )
        else:
            log.error("no parking_rates row for vehicle %s", chosen_wire_id)
            fee = rates.Fee(0, "0", "no tariff configured")

        plate_in = normalize_plate(transaction.police_number)
        plate_seen = normalize_plate(plate_out)
        match = None if (plate_in is None or plate_seen is None) else plate_in == plate_seen

        is_member = rates.is_active_member(member, chosen_wire_id)

        return GateOutResult(
            status=STATUS_SUCCESS_MEMBER if is_member else STATUS_SUCCESS,
            transaction_code=transaction.ticket_number,
            card_number=transaction.card_number,
            total=fee.total,
            duration=fee.duration,
            plate_in=plate_in,
            plate_out=plate_seen,
            plate_match=match,
            is_member=is_member,
            member_name=member.name if member else None,
            time_checkin=format_wib(transaction.entry_time),
            time_checkout=format_wib(check_out),
            cam_in=transaction.cam_in,
            cam_out=transaction.cam_out,
            breakdown=fee.breakdown,
            vehicle_id=chosen_wire_id,
            payment_status=transaction.payment_status,
            created_at=format_wib(transaction.created_at),
            updated_at=format_wib(transaction.updated_at),
        )

    # -- check-out ---------------------------------------------------------

    async def gate_out(
        self,
        *,
        gate: str,
        code: str | None = None,
        plate_num: str | None = None,
        url_gambar: str | None = None,
        admin_id: int | None = None,
        shift_id: int | None = None,
        exit_operator_id: UUID | None = None,
        exit_shift_id: UUID | None = None,
        lost: bool = False,
        vehicle_id: int | None = None,
        vehicle_type_id: UUID | None = None,
        open_barrier: bool = True,
    ) -> GateOutResult:
        """Settle a parking session and release the vehicle.

        **This is the method missing from production** (flow.md §7.1): the
        route ``POST /api/lpr/gateout`` points at ``GateoutController::GateOutLpr``,
        which does not exist, so every automated exit 500s. Modelled on
        ``GateOutRfidLpr``.
        """
        async with self.session_factory() as session:
            transaction = await self.find_open_transaction(
                session, code=code, plate=plate_num
            )

            if transaction is None:
                self._log_event(
                    session,
                    source="api",
                    method="gateout_notfound",
                    gate=gate,
                    detail=f"code={code!r} plate={plate_num!r}",
                )
                await session.commit()
                return GateOutResult(
                    status=STATUS_NOT_FOUND,
                    message="Transaksi aktif tidak ditemukan untuk tiket atau plat ini",
                )

            if _is_paid(transaction) and transaction.exit_time is not None:
                return GateOutResult(
                    status=STATUS_TICKET_USED,
                    transaction_code=transaction.ticket_number,
                    message="Tiket ini sudah digunakan",
                )

            quote = await self._price(
                session,
                transaction,
                plate_out=plate_num,
                lost=lost,
                vehicle_id=vehicle_id,
                vehicle_type_id=vehicle_type_id,
            )

            # Optional strictness. Off by default, because on site the plates
            # genuinely disagree and refusing would strand real drivers.
            if (
                self.config is not None
                and self.config.require_plate_match
                and quote.plate_match is False
            ):
                self._log_event(
                    session,
                    source="api",
                    method="gateout_plate_mismatch",
                    gate=gate,
                    transaction_code=transaction.ticket_number,
                    detail=f"in={quote.plate_in} out={quote.plate_out}",
                )
                await session.commit()
                return GateOutResult(
                    status=STATUS_PLATE_MISMATCH,
                    transaction_code=transaction.ticket_number,
                    plate_in=quote.plate_in,
                    plate_out=quote.plate_out,
                    plate_match=False,
                    message="Plat tidak cocok dengan catatan masuk",
                )

            image_path = transaction.cam_out
            if url_gambar and self.storage is not None:
                image_path = self.storage.download_async(
                    url_gambar,
                    "lpr/gateout",
                    self.storage.lpr_filename(url_gambar, prefix="CAMOUT_LPR"),
                )
            elif url_gambar:
                image_path = url_gambar

            exit_gate_id = await gate_uuid(session, gate)
            transaction.exit_time = _parse_wire(quote.time_checkout) if quote.time_checkout else None
            transaction.total_fee = int(quote.total)
            transaction.duration = quote.duration
            transaction.payment_status = "lunas"
            transaction.paid_at = self.clock()
            transaction.exit_gate_id = exit_gate_id
            transaction.status_parking = ParkingStatus.COMPLETED
            if image_path:
                transaction.cam_out = image_path
                transaction.camout_lpr = image_path
            # The exit read is recorded but never overwrites a known entry
            # plate: the entry read is the one the ticket was issued against.
            if quote.plate_out and not transaction.police_number:
                transaction.police_number = quote.plate_out
            if quote.plate_match is False:
                transaction.keterangan = (
                    f"plate mismatch: entered {quote.plate_in}, "
                    f"exited {quote.plate_out}"
                )
            transaction.exit_operator_id = exit_operator_id or None
            transaction.exit_shift_id = exit_shift_id or None

            self._log_event(
                session,
                source="api",
                method="gateout",
                gate=gate,
                transaction_code=transaction.ticket_number,
                detail=(
                    f"total={quote.total} duration={quote.duration} "
                    f"match={quote.plate_match}"
                ),
            )
            await session.commit()

        # FIX for flow.md §7.6: production never commands the exit barrier.
        if open_barrier and (
            self.config is None or self.config.command_exit_barrier
        ):
            await self.publisher.open_barrier(gate, exit_lane=True)

        log.info(
            "gate %s: %s settled, total %s, duration %s",
            gate,
            quote.transaction_code,
            quote.total,
            quote.duration,
        )
        result = GateOutResult(
            **{
                **quote.__dict__,
                "status": (
                    STATUS_SUCCESS_MEMBER if quote.is_member else STATUS_SUCCESS_TICKET
                ),
                "cam_out": image_path,
                "admin_id": admin_id,
                "shift_id": shift_id,
            }
        )
        return result

    async def _lost_tariff_for_class(
        self,
        db: AsyncSession,
        *,
        vehicle_type_id: UUID | None = None,
        vehicle_id: int | None = None,
    ) -> tuple[rates.Tariff | None, UUID | None, str | None]:
        """The lost-ticket tariff for a class — ``(tariff, type_uuid, error)``.

        Shared by :meth:`lost_ticket` and :meth:`preview_fee` so a preview can
        never drift from what settling actually charges.
        """
        if vehicle_type_id is not None:
            chosen = await db.get(VehicleType, vehicle_type_id)
            if chosen is None or chosen.status != VehicleStatus.ACTIVE:
                return None, None, "Jenis kendaraan tidak ditemukan atau nonaktif"
            tariff_row = await self._rate_for_vehicle_type(db, chosen.id)
            if tariff_row is not None:
                return rates.Tariff.from_row(tariff_row), chosen.id, None
            if chosen.price is None:
                return None, None, "Harga jenis kendaraan belum diatur"
            return _flat_tariff_from_price(chosen.price), chosen.id, None

        if not vehicle_id:
            return None, None, "Jenis kendaraan wajib dipilih untuk tiket hilang"
        tariff_row = await self._rate_for(db, vehicle_id)
        if tariff_row is None:
            log.error("lost ticket: no parking_rates row for vehicle %s", vehicle_id)
            return None, None, "Tarif kendaraan tidak ditemukan"
        return rates.Tariff.from_row(tariff_row), await _coerce_vehicle(db, vehicle_id), None

    async def lost_ticket(
        self,
        *,
        gate: str,
        plate: str | None,
        vehicle_id: int | None = None,
        vehicle_type_id: UUID | None = None,
        admin_id: int | None = None,
        shift_id: int | None = None,
        exit_operator_id: UUID | None = None,
        exit_shift_id: UUID | None = None,
        open_barrier: bool = True,
    ) -> GateOutResult:
        """Record a lost ticket without a ticket number.

        The cashier types only the plate and the vehicle class. The lost-ticket
        fee (``ticket_charge`` + one parking period) is written straight into
        ``park_transactions``. If the plate still has an open session, that
        session is settled as lost instead of leaving a duplicate behind.

        ``vehicle_type_id`` addresses an admin-managed class directly; the
        legacy wire ``vehicle_id`` (1-4) still works when no UUID is given.
        """
        plate_norm = normalize_plate(plate)
        if not plate_norm:
            return GateOutResult(
                status=STATUS_NOT_FOUND,
                message="Nomor plat wajib diisi untuk tiket hilang",
            )

        async with self.session_factory() as session:
            tariff, vehicle_type_uuid, err = await self._lost_tariff_for_class(
                session,
                vehicle_type_id=vehicle_type_id,
                vehicle_id=vehicle_id,
            )
            if tariff is None or err is not None:
                return GateOutResult(status=STATUS_NOT_FOUND, message=err)

            now = self.clock()
            now_str = format_wib(now)
            fee = rates.calculate(
                tariff,
                now,
                now,
                type=rates.TYPE_LOST,
            )
            result_vehicle_id = (
                vehicle_id
                if vehicle_type_uuid is None
                else await vehicle_id_of(session, vehicle_type_uuid)
            )

            open_tx = await session.scalar(
                select(ParkTransaction)
                .where(
                    ParkTransaction.police_number == plate_norm,
                    ParkTransaction.exit_time.is_(None),
                )
                .order_by(ParkTransaction.entry_time.desc())
                .limit(1)
            )

            gate_id = await gate_uuid(session, gate)

            if open_tx is not None:
                open_tx.exit_time = now
                open_tx.total_fee = int(fee.total)
                open_tx.duration = fee.duration
                open_tx.payment_status = "lunas"
                open_tx.paid_at = now
                open_tx.exit_gate_id = gate_id
                open_tx.status_parking = ParkingStatus.COMPLETED
                open_tx.vehicle_type_id = vehicle_type_uuid
                open_tx.keterangan = "tiket hilang"
                open_tx.exit_operator_id = exit_operator_id or None
                open_tx.exit_shift_id = exit_shift_id or None
                code = open_tx.ticket_number or ""
            else:
                code = await self.generate_transaction_code(session)
                session.add(
                    ParkTransaction(
                        ticket_number=code,
                        entry_time=now,
                        exit_time=now,
                        vehicle_type_id=vehicle_type_uuid,
                        police_number=plate_norm,
                        total_fee=int(fee.total),
                        duration=fee.duration,
                        status_parking=ParkingStatus.COMPLETED,
                        entry_gate_id=gate_id or await _require_any_gate(session),
                        exit_gate_id=gate_id,
                        payment_status="lunas",
                        paid_at=now,
                        cam_in="-",
                        camin_lpr="-",
                        payment_type="cash",
                        keterangan="tiket hilang",
                        detection_method=DetectionMethodForWire.MANUAL,
                        exit_operator_id=exit_operator_id or None,
                        exit_shift_id=exit_shift_id or None,
                    )
                )
                code = code or ""

            self._log_event(
                session,
                source="api",
                method="gateout_lost",
                gate=gate,
                transaction_code=code,
                detail=f"plate={plate_norm} total={fee.total}",
            )
            await session.commit()

        # FIX for flow.md §7.6: production never commands the exit barrier.
        if open_barrier and (
            self.config is None or self.config.command_exit_barrier
        ):
            await self.publisher.open_barrier(gate, exit_lane=True)

        return GateOutResult(
            status=STATUS_SUCCESS,
            transaction_code=code,
            total=fee.total,
            duration=fee.duration,
            plate_in=plate_norm,
            plate_out=plate_norm,
            plate_match=True,
            breakdown=fee.breakdown,
            vehicle_id=result_vehicle_id,
            admin_id=admin_id,
            shift_id=shift_id,
            payment_status="lunas",
            time_checkin=now_str,
            time_checkout=now_str,
        )

    # -- manual re-entry (the ticket never printed) ---------------------------

    async def _manual_charge_for_class(
        self,
        db: AsyncSession,
        *,
        vehicle_type_id: UUID | None = None,
        vehicle_id: int | None = None,
        explicit_total: float | None = None,
    ) -> tuple[UUID | None, int, str | None]:
        """The manual-ticket charge for a class — ``(type_uuid, charge, error)``.

        Shared by :meth:`manual_ticket` and :meth:`preview_fee`. The
        admin-configured flat price wins; fall back to the class's rate table,
        then to the legacy seed prices for the four wired classes.
        """
        if vehicle_type_id is not None:
            chosen = await db.get(VehicleType, vehicle_type_id)
            if chosen is None or chosen.status != VehicleStatus.ACTIVE:
                return None, 0, "Jenis kendaraan tidak ditemukan atau nonaktif"
            vehicle_type_uuid: UUID | None = chosen.id
        else:
            if vehicle_id not in (1, 2, 3, 4):
                return None, 0, "Jenis kendaraan wajib dipilih (motor, mobil, ojol/paket, atau bus besar)"
            vehicle_type_uuid = await _coerce_vehicle(db, vehicle_id)

        charge = explicit_total
        if charge is None:
            vehicle_type = (
                await db.get(VehicleType, vehicle_type_uuid)
                if vehicle_type_uuid is not None
                else None
            )
            configured = vehicle_type.price if vehicle_type else None
            if configured is None:
                rate_row = await self._rate_for_vehicle_type(db, vehicle_type_uuid)
                configured = rate_row.base_price if rate_row else None
            if configured is not None:
                charge = configured
            elif vehicle_type_uuid is not None:
                return None, 0, "Harga jenis kendaraan belum diatur"
            else:
                charge = {1: 2000, 2: 4000, 3: 0, 4: 6000}[vehicle_id]
        return vehicle_type_uuid, int(charge), None

    async def preview_fee(
        self,
        *,
        kind: str,
        vehicle_type_id: UUID | None = None,
        vehicle_id: int | None = None,
    ) -> GateOutResult:
        """What would a manual / lost ticket cost? Read-only — nothing written.

        Backs the POS payment modal so the operator sees the real amount
        before taking the money. ``kind`` is ``"manual"`` or ``"lost"``.
        """
        async with self.session_factory() as session:
            if kind == "manual":
                _uuid, charge, err = await self._manual_charge_for_class(
                    session,
                    vehicle_type_id=vehicle_type_id,
                    vehicle_id=vehicle_id,
                )
                if err is not None:
                    return GateOutResult(status=STATUS_NOT_FOUND, message=err)
                return GateOutResult(
                    status=STATUS_SUCCESS,
                    total=float(charge),
                    duration=rates.format_duration(rates.elapsed(self.clock(), self.clock())),
                    breakdown=f"manual input, flat {charge}",
                )

            tariff, _uuid, err = await self._lost_tariff_for_class(
                session,
                vehicle_type_id=vehicle_type_id,
                vehicle_id=vehicle_id,
            )
            if tariff is None or err is not None:
                return GateOutResult(status=STATUS_NOT_FOUND, message=err)
            now = self.clock()
            fee = rates.calculate(tariff, now, now, type=rates.TYPE_LOST)
            return GateOutResult(
                status=STATUS_SUCCESS,
                total=fee.total,
                duration=fee.duration,
                breakdown=fee.breakdown,
            )

    async def manual_ticket(
        self,
        *,
        police_number: str,
        vehicle_id: int | None = None,
        vehicle_type_id: UUID | None = None,
        admin_id: int | None = None,
        shift_id: int | None = None,
        exit_operator_id: UUID | None = None,
        exit_shift_id: UUID | None = None,
        gate: str = "1",
        total: float | None = None,
    ) -> GateOutResult:
        """Record a transaction by hand when the ticket did not print.

        The cashier types only the plate and the vehicle class; the code is
        generated here, check-in / check-out / duration are ``now``, and the
        class's configured flat price is charged and marked lunas immediately
        — there is nothing left to settle.

        ``vehicle_type_id`` addresses an admin-managed class directly; the
        legacy wire ``vehicle_id`` (1-4) still works when no UUID is given.
        """
        plate = normalize_plate(police_number)
        if not plate:
            return GateOutResult(
                status=STATUS_NOT_FOUND,
                message="Nomor plat wajib diisi untuk input manual",
            )

        duration = rates.format_duration(
            rates.elapsed(self.clock(), self.clock())
        )

        async with self.session_factory() as session:
            vehicle_type_uuid, charge, err = await self._manual_charge_for_class(
                session,
                vehicle_type_id=vehicle_type_id,
                vehicle_id=vehicle_id,
                explicit_total=total,
            )
            if err is not None:
                return GateOutResult(status=STATUS_NOT_FOUND, message=err)

            now = self.clock()
            now_str = format_wib(now)

            code = await self.generate_transaction_code(session)
            gate_id = await gate_uuid(session, gate)
            result_vehicle_id = (
                vehicle_id
                if vehicle_type_uuid is None
                else await vehicle_id_of(session, vehicle_type_uuid)
            )

            transaction = ParkTransaction(
                ticket_number=code,
                entry_time=now,
                exit_time=now,
                vehicle_type_id=vehicle_type_uuid,
                police_number=plate,
                total_fee=int(charge),
                duration=duration,
                status_parking=ParkingStatus.COMPLETED,
                entry_gate_id=gate_id or await _require_any_gate(session),
                exit_gate_id=gate_id,
                payment_status="lunas",
                paid_at=now,
                cam_in="-",
                camin_lpr="-",
                payment_type="cash",
                keterangan="tiket tidak cetak",
                detection_method=DetectionMethodForWire.MANUAL,
                exit_operator_id=exit_operator_id or None,
                exit_shift_id=exit_shift_id or None,
            )
            session.add(transaction)
            await session.flush()

            self._log_event(
                session,
                source="api",
                method="gatein_manual",
                gate=gate,
                transaction_code=code,
                detail=f"plate={plate} vehicle={vehicle_id} total={charge}",
            )
            await session.commit()

        log.info(
            "manual ticket %s: plate %s, vehicle %s, charged %s",
            code,
            plate,
            result_vehicle_id,
            charge,
        )
        return GateOutResult(
            status=STATUS_SUCCESS,
            transaction_code=code,
            total=charge,
            duration=duration,
            plate_in=plate,
            plate_out=plate,
            plate_match=True,
            breakdown=f"manual input, flat {int(charge)}",
            vehicle_id=result_vehicle_id,
            admin_id=admin_id,
            shift_id=shift_id,
            payment_status="lunas",
            time_checkin=now_str,
            time_checkout=now_str,
        )

    # -- POS actions (void / reprint / receipt) ------------------------------

    async def void_transaction(
        self,
        *,
        code: str,
        operator_id: UUID | None = None,
        shift_id: UUID | None = None,
        reason: str = "",
    ) -> PosActionResult:
        """Cancel a transaction.

        A still-parked session is voided outright; a paid/completed one is
        voided and its ``payments`` rows marked ``Refunded`` (a cash refund row
        is written when the transaction was marked lunas without one). Voided
        transactions can never be settled or reprinted.
        """
        async with self.session_factory() as session:
            transaction = await session.scalar(
                select(ParkTransaction)
                .where(ParkTransaction.ticket_number == code)
                .order_by(ParkTransaction.created_at.desc())
                .limit(1)
            )
            if transaction is None:
                return PosActionResult(
                    status=STATUS_NOT_FOUND,
                    transaction_code=code,
                    message="Transaksi tidak ditemukan",
                )
            if transaction.status_parking == ParkingStatus.VOID:
                return PosActionResult(
                    status="already_void",
                    transaction_code=code,
                    message="Transaksi sudah dibatalkan (void)",
                )

            payments = (
                (
                    await session.execute(
                        select(Payment).where(
                            Payment.park_transaction_id == transaction.id,
                            Payment.status != PaymentStatus.REFUNDED,
                        )
                    )
                )
                .scalars()
                .all()
            )
            refunded = 0
            for payment in payments:
                payment.status = PaymentStatus.REFUNDED
                refunded += 1
            if not payments and _is_paid(transaction):
                session.add(
                    Payment(
                        park_transaction_id=transaction.id,
                        amount=transaction.total_fee,
                        method=PaymentMethod.CASH,
                        status=PaymentStatus.REFUNDED,
                        reference_number=transaction.ticket_number,
                        paid_at=self.clock(),
                    )
                )
                refunded += 1

            gate_codes = await _gate_codes(session)
            gate = gate_codes.get(transaction.exit_gate_id) or gate_codes.get(
                transaction.entry_gate_id
            )
            stamp = self.clock()
            reason_note = f"; reason={reason}" if reason else ""
            transaction.status_parking = ParkingStatus.VOID
            transaction.keterangan = (
                f"{transaction.keterangan} | " if transaction.keterangan else ""
            ) + f"voided by operator{reason_note}"
            transaction.updated_at = stamp
            self._log_event(
                session,
                source="pos",
                method="void",
                gate=gate,
                transaction_code=code,
                detail=f"operator={operator_id} shift={shift_id} refunded={refunded}{reason_note}",
            )
            await session.commit()
            total = transaction.total_fee

        log.info("voided transaction %s (refunded %s)", code, refunded)
        return PosActionResult(
            status=STATUS_SUCCESS,
            transaction_code=code,
            message="Transaksi berhasil dibatalkan (void)",
            refunded=refunded,
            total=total,
        )

    async def reprint_ticket(
        self, *, code: str, gate: str | None = None
    ) -> PosActionResult:
        """Reprint the entry ticket from the transaction record.

        The ESC/POS blocks are rebuilt from the stored facts (entry gate,
        vehicle class, plate, entry time) and the ticket's QR is its own code,
        exactly as on the original print. A voided ticket is not reprinted.
        """
        async with self.session_factory() as session:
            transaction = await session.scalar(
                select(ParkTransaction)
                .where(ParkTransaction.ticket_number == code)
                .order_by(ParkTransaction.created_at.desc())
                .limit(1)
            )
            if transaction is None:
                return PosActionResult(
                    status=STATUS_NOT_FOUND,
                    transaction_code=code,
                    message="Transaksi tidak ditemukan",
                )
            if transaction.status_parking == ParkingStatus.VOID:
                return PosActionResult(
                    status="already_void",
                    transaction_code=code,
                    message="Tidak dapat mencetak ulang tiket yang sudah dibatalkan",
                )

            gate_codes = await _gate_codes(session)
            gate_code = gate or gate_codes.get(transaction.entry_gate_id)
            if gate_code is None:
                return PosActionResult(
                    status=STATUS_NOT_FOUND,
                    transaction_code=code,
                    message="Gerbang masuk tidak diketahui — tidak dapat mencetak ulang",
                )

            vehicle_wire_id = await vehicle_id_of(session, transaction.vehicle_type_id)
            blocks_1, blocks_2 = await self._build_ticket(
                session,
                gate=gate_code,
                transaction_code=transaction.ticket_number or code,
                qr_string=transaction.ticket_number or code,
                type_qr=escpos.TYPE_QR_CASH,
                vehicle_id=vehicle_wire_id,
                plate=transaction.police_number,
                checkin_at=format_wib(transaction.entry_time) or "",
            )
            self._log_event(
                session,
                source="pos",
                method="reprint",
                gate=gate_code,
                transaction_code=code,
                detail="tiket masuk berhasil dicetak ulang",
            )
            await session.commit()

        await self._publish_ticket(gate_code, code, blocks_1, blocks_2)
        log.info("reprinted entry ticket %s on gate %s", code, gate_code)
        return PosActionResult(
            status=STATUS_SUCCESS,
            transaction_code=code,
            message="Tiket masuk berhasil dicetak ulang",
            blocks_printed=len(blocks_1) + len(blocks_2),
        )

    async def print_exit_receipt(
        self, *, code: str, gate: str | None = None
    ) -> PosActionResult:
        """Print the exit (payment) receipt from the transaction record."""
        async with self.session_factory() as session:
            transaction = await session.scalar(
                select(ParkTransaction)
                .where(ParkTransaction.ticket_number == code)
                .order_by(ParkTransaction.created_at.desc())
                .limit(1)
            )
            if transaction is None:
                return PosActionResult(
                    status=STATUS_NOT_FOUND,
                    transaction_code=code,
                    message="Transaksi tidak ditemukan",
                )
            if transaction.status_parking == ParkingStatus.VOID:
                return PosActionResult(
                    status="already_void",
                    transaction_code=code,
                    message="Tidak dapat mencetak struk untuk tiket yang sudah dibatalkan",
                )

            gate_codes = await _gate_codes(session)
            gate_code = (
                gate
                or gate_codes.get(transaction.exit_gate_id)
                or gate_codes.get(transaction.entry_gate_id)
            )
            if gate_code is None:
                return PosActionResult(
                    status=STATUS_NOT_FOUND,
                    transaction_code=code,
                    message="Gerbang tidak diketahui — tidak dapat mencetak struk",
                )

            blocks = escpos.build_gate_out_receipt(
                escpos.GateOutReceipt(
                    store_name=self.config.site_name if self.config else "",
                    trx=transaction.ticket_number or code,
                    plate=transaction.police_number,
                    datetime=format_wib(transaction.entry_time) or "",
                    exit_datetime=format_wib(transaction.exit_time)
                    or format_wib(self.clock())
                    or "",
                    duration=transaction.duration or "",
                    total=float(transaction.total_fee or 0),
                )
            )
            self._log_event(
                session,
                source="pos",
                method="receipt",
                gate=gate_code,
                transaction_code=code,
                detail="struk keluar berhasil dicetak",
            )
            await session.commit()

        from api_trafix.services.protocol import message_id

        async with self._print_lock(gate_code):
            await self.publisher.print_ticket(
                gate_code, blocks, message_id(code, 1)
            )
        log.info("printed exit receipt for %s on gate %s", code, gate_code)
        return PosActionResult(
            status=STATUS_SUCCESS,
            transaction_code=code,
            message="Struk keluar berhasil dicetak",
            blocks_printed=len(blocks),
        )

    # -- the automated RFID exit (PUT /api/lpr/gateoutcard) -----------------

    async def gate_out_rfid(
        self,
        *,
        card: str,
        gate: str,
        plate_num: str | None,
        url_gambar: str | None,
        admin_id: int | None = None,
        shift_id: int | None = None,
        exit_operator_id: UUID | None = None,
        exit_shift_id: UUID | None = None,
    ) -> str:
        """Port of ``GateoutController::GateOutRfidLpr`` (:1603).

        Returns only the sparse status string the route echoes back, exactly
        like the PHP: ``success_member``, ``success_ticket``, ``ticket_used``
        or ``failed_member``. The card is looked up as a member's ``card_number``
        (still inside) before it is tried as a ticket code.
        """
        raw = str(card or "").strip()
        padded = raw.zfill(10)  # str_pad(…, 10, '0', STR_PAD_LEFT)
        lookups = [candidate for candidate in (raw, padded) if candidate]

        async with self.session_factory() as session:
            member_transaction = await session.scalar(
                select(ParkTransaction)
                .where(
                    ParkTransaction.card_number.in_(lookups),
                    ParkTransaction.exit_time.is_(None),
                )
                .order_by(ParkTransaction.updated_at.desc())
                .limit(1)
            )
            if member_transaction is not None:
                await self._settle_rfid(
                    session,
                    member_transaction,
                    gate=gate,
                    plate_num=plate_num,
                    url_gambar=url_gambar,
                    admin_id=admin_id,
                    shift_id=shift_id,
                    exit_operator_id=exit_operator_id,
                    exit_shift_id=exit_shift_id,
                )
                await session.commit()
                return STATUS_SUCCESS_MEMBER

            ticket_transaction = await session.scalar(
                select(ParkTransaction)
                .where(ParkTransaction.ticket_number.in_(lookups))
                .order_by(ParkTransaction.updated_at.desc())
                .limit(1)
            )
            if ticket_transaction is None:
                self._log_event(
                    session,
                    source="api",
                    method="gateout_rfid_notfound",
                    gate=gate,
                    detail=f"card={card!r}",
                )
                await session.commit()
                return STATUS_FAILED_MEMBER

            if _is_paid(ticket_transaction) and ticket_transaction.exit_time is not None:
                self._log_event(
                    session,
                    source="api",
                    method="gateout_rfid_used",
                    gate=gate,
                    transaction_code=ticket_transaction.ticket_number,
                )
                await session.commit()
                return STATUS_TICKET_USED

            await self._settle_rfid(
                session,
                ticket_transaction,
                gate=gate,
                plate_num=plate_num,
                url_gambar=url_gambar,
                admin_id=admin_id,
                shift_id=shift_id,
                exit_operator_id=exit_operator_id,
                exit_shift_id=exit_shift_id,
            )
            await session.commit()
            return STATUS_SUCCESS_TICKET

    async def _settle_rfid(
        self,
        db: AsyncSession,
        transaction: ParkTransaction,
        *,
        gate: str,
        plate_num: str | None,
        url_gambar: str | None,
        admin_id: int | None,
        shift_id: int | None,
        exit_operator_id: UUID | None = None,
        exit_shift_id: UUID | None = None,
    ) -> None:
        quote = await self._price(db, transaction, plate_out=plate_num)

        image_path = transaction.cam_out
        if url_gambar and self.storage is not None:
            image_path = self.storage.download_async(
                url_gambar,
                "lpr/gateout",
                self.storage.lpr_filename(url_gambar, prefix="CAMOUT_LPR"),
            )
        elif url_gambar:
            image_path = url_gambar

        transaction.exit_time = _parse_wire(quote.time_checkout) if quote.time_checkout else None
        transaction.total_fee = int(quote.total)
        transaction.duration = quote.duration
        transaction.payment_status = "lunas"
        transaction.paid_at = self.clock()
        transaction.exit_gate_id = await gate_uuid(db, gate)
        transaction.status_parking = ParkingStatus.COMPLETED
        if url_gambar:
            transaction.cam_out = image_path
            transaction.camout_lpr = image_path
        plate = normalize_plate(plate_num)
        if plate:
            transaction.police_number = plate
        transaction.exit_operator_id = exit_operator_id or None
        transaction.exit_shift_id = exit_shift_id or None

        self._log_event(
            db,
            source="api",
            method="gateout-rfid",
            gate=gate,
            transaction_code=transaction.ticket_number,
            detail=(
                f"total={quote.total} duration={quote.duration} "
                f"match={quote.plate_match}"
            ),
        )


# -- module helpers -----------------------------------------------------------

class DetectionMethodForWire:
    """Wire detection methods, as stored on park_transactions.detection_method."""

    AUTO_LPR = "Auto_LPR"
    SCANNER = "Scanner"
    RFID = "RFID"
    MANUAL = "Manual"


def _parse_wire(value: str) -> datetime:
    """Parse a wire WIB timestamp (naive) back into aware UTC."""
    naive = datetime.strptime(value, DATETIME_FORMAT)  # noqa: DTZ007 - wire string has no tz
    return naive.replace(tzinfo=WIB).astimezone(UTC)


def _is_paid(transaction: ParkTransaction) -> bool:
    return transaction.payment_status == "lunas"


async def _coerce_vehicle(
    db: AsyncSession, vehicle_id: int | None
) -> UUID | None:
    from api_trafix.services.vehicles import coerce_vehicle_type_id

    return await coerce_vehicle_type_id(db, vehicle_id)


def _flat_tariff_from_price(price: float) -> rates.Tariff:
    """A synthetic Flat tariff charging exactly ``price``.

    Used when a class the admin created has no parking_rates row: the flat
    price *is* the tariff (ticket_charge 0 so a lost ticket also costs just
    the configured price).
    """
    return rates.Tariff(
        fee_category=rates.FEE_FLAT,
        grace_periode=0,
        fee_first_time=0,
        fee_first_price=float(price),
        fee_time_1=0,
        fee_price_1=0,
        fee_price_max=0,
        ticket_charge=0,
        stay_charge=0,
    )


async def _gate_codes(db: AsyncSession) -> dict[UUID, str]:
    gates = (await db.execute(select(Gate))).scalars().all()
    return {gate.id: gate.gate_code for gate in gates if gate.gate_code}


def _gate_code_of(gate_id: UUID | None, codes: dict[UUID, str]) -> str | None:
    if gate_id is None:
        return None
    return codes.get(gate_id)


async def _require_any_gate(db: AsyncSession) -> UUID:
    gate = await db.scalar(select(Gate).limit(1))
    if gate is None:
        raise GateCycleError("no gate row exists — run the seeder")
    return gate.id
