"""Smoke tests for the gate-in / gate-out cycle service.

These run the full check-in -> quote -> check-out flow against a real Postgres
database with the gate-cycle schema, proving the service layer binds correctly
to the API-Trafix models (enum columns, relationships, UUID keys) before the
HTTP and MQTT layers are wired on top.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from api_trafix.models import DetectionMethod, ParkTransaction
from api_trafix.services import gate_cycle as service
from api_trafix.services.gate_cycle import GateCycleConfig, GateCycleService
from api_trafix.services.seed import seed_reference_data
from api_trafix.services.snapshots import SnapshotStore

BASE = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)


@pytest.fixture()
async def gate_service(db_sessionmaker, tmp_path):
    """A seeded service whose clock advances 20 minutes per call, so a
    check-in is always 20 minutes older than the next check-out."""
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

    calls = {"n": 0}

    def clock() -> datetime:
        calls["n"] += 1
        return BASE + timedelta(minutes=20 * calls["n"])

    publisher = service.NullPublisher()
    svc = GateCycleService(
        db_sessionmaker,
        publisher=publisher,
        storage=SnapshotStore(Path(tmp_path)),
        config=GateCycleConfig(
            site_name="Trafix Test",
            site_address="Jl. Test 1",
            storage_dir=Path(tmp_path),
        ),
        clock=clock,
        print_gap_seconds=0,
    )
    return svc, publisher


async def _open_transaction(db_sessionmaker, ticket: str) -> ParkTransaction:
    async with db_sessionmaker() as db:
        return (
            await db.execute(
                select(ParkTransaction).where(ParkTransaction.ticket_number == ticket)
            )
        ).scalar_one()


async def test_gate_in_issues_ticket_and_prints(gate_service):
    svc, publisher = gate_service
    result = await svc.gate_in(
        gate="1",
        vehicle_id=2,
        plate_num="H 1234 CD",
        url_gambar=None,
        serial_no="serial-1",
        ipcam=None,
    )
    assert result.status == service.STATUS_SUCCESS
    assert result.transaction_code
    assert result.type_qr == "cash"
    # The ticket prints in two halves, serialised per gate.
    assert [gate for gate, _ in publisher.printed] == ["1", "1"]

    async with svc.session_factory() as db:
        tx = (
            await db.execute(
                select(ParkTransaction).where(
                    ParkTransaction.ticket_number == result.transaction_code
                )
            )
        ).scalar_one()
        assert tx.police_number == "H1234CD"
        assert tx.detection_method == DetectionMethod.SCANNER
        assert tx.status_parking.value == "Parked"


async def test_member_gate_in_opens_no_ticket(gate_service):
    svc, publisher = gate_service
    result = await svc.member_gate_in(
        gate="1", card_no="006343040", serial_no="s", vehicle_id=1
    )
    assert result.status == service.STATUS_SUCCESS
    assert result.member_name == "Angelo"
    assert result.transaction_code
    assert not publisher.printed


async def test_member_gate_in_unknown_card_is_not_found(gate_service):
    svc, _ = gate_service
    result = await svc.member_gate_in(gate="1", card_no="999999", serial_no="s")
    assert result.status == service.STATUS_NOT_FOUND


async def test_member_gate_in_vehicle_class_mismatch_is_refused(gate_service):
    svc, _ = gate_service
    # The gate is configured for cars (vehicle_id=2) but Angelo rides a MOTOR.
    result = await svc.member_gate_in(
        gate="1", card_no="006343040", serial_no="s", vehicle_id=2
    )
    assert result.status == service.STATUS_MEMBER_EXPIRED


async def test_quote_prices_flat_tariff_after_grace(gate_service):
    svc, _ = gate_service
    await svc.gate_in(
        gate="1", vehicle_id=2, plate_num="H 1234 CD", url_gambar=None, serial_no="s"
    )
    quote = await svc.quote(plate="H 1234 CD")
    assert quote.status == service.STATUS_SUCCESS
    assert quote.total == 4000
    assert quote.duration == "20 m 0 s"


async def test_gate_out_settles_and_commands_exit_barrier(gate_service):
    svc, publisher = gate_service
    await svc.gate_in(
        gate="1", vehicle_id=2, plate_num="H 1234 CD", url_gambar=None, serial_no="s"
    )
    quote = await svc.quote(plate="H 1234 CD")

    result = await svc.gate_out(gate="2", code=quote.transaction_code)
    assert result.status == service.STATUS_SUCCESS_TICKET
    assert result.total == 4000
    assert publisher.barriers == [("2", True)]

    # A second check-out is refused: the ticket was already used.
    used = await svc.gate_out(gate="2", code=quote.transaction_code)
    assert used.status == service.STATUS_TICKET_USED


async def test_lpr_gate_in_stores_upload(gate_service):
    svc, publisher = gate_service
    result = await svc.lpr_gate_in(plate="H 1234 CD", image=b"fake-jpeg-bytes")
    assert result.status == service.STATUS_SUCCESS
    assert result.image_path.startswith("storage/")
    assert not publisher.printed

    tx = await _open_transaction(svc.session_factory, result.transaction_code)
    assert tx.detection_method == DetectionMethod.AUTO_LPR
    assert tx.camin_lpr == result.image_path


async def test_attach_gatein_image_sets_plate_and_photo(gate_service):
    svc, _ = gate_service
    result = await svc.lpr_gate_in(plate="", image=b"fake")
    attached = await svc.attach_gatein_image(
        transaction_code=result.transaction_code, plate="H 9999 ZZ", image=b"fake2"
    )
    assert attached["status"] == service.STATUS_SUCCESS

    tx = await _open_transaction(svc.session_factory, result.transaction_code)
    assert tx.police_number == "H9999ZZ"
    assert tx.camin_lpr == attached["camin_lpr"]


async def test_gate_in_unknown_gate_raises(gate_service):
    svc, _ = gate_service
    with pytest.raises(service.GateCycleError):
        await svc.gate_in(
            gate="99", vehicle_id=1, plate_num=None, url_gambar=None, serial_no="s"
        )


async def test_lost_ticket_charges_ticket_charge_plus_period(gate_service):
    svc, _ = gate_service
    result = await svc.lost_ticket(gate="2", plate="H 1234 CD", vehicle_id=2)
    assert result.status == service.STATUS_SUCCESS
    assert result.total == 30000 + 4000
    assert result.payment_status == "lunas"


async def test_manual_ticket_charges_flat_rate(gate_service):
    svc, _ = gate_service
    result = await svc.manual_ticket(police_number="B 1234 ZZ", vehicle_id=2, gate="1")
    assert result.status == service.STATUS_SUCCESS
    assert result.total == 4000
