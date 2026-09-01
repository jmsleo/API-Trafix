"""Export endpoint tests for the finance report downloads (CSV/XLSX/PDF).

Mirrors ``test_admin_routes.py``: a minimal FastAPI app carrying only the
finance-reports router, auth short-circuited by overriding
``get_current_finance``, real ``trafix_test`` database per request.

Seeded rows are cleaned up afterwards because the shared test database is
persistent and other suites assert exact reference-data counts.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_finance
from api_trafix.models import (
    DetectionMethod,
    Gate,
    GateStatus,
    GateType,
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentMethod,
    PaymentStatus,
    User,
    UserRole,
    UserStatus,
    VehicleStatus,
    VehicleType,
)
from api_trafix.routes import finance_reports
from api_trafix.routes.finance_reports import _guard_export_size
from api_trafix.crud import finance_reports as finance_reports_crud


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(scope="session")
async def finance_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Export Test Finance",
            username=f"export-finance-{_suffix()}",
            password="unused",
            role=UserRole.FINANCE,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(db_sessionmaker, finance_user):
    app = FastAPI()
    app.include_router(finance_reports.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_finance():
        return finance_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_finance] = override_finance

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_report_data(db_sessionmaker):
    """One COMPLETED transaction (+ SUCCESS payment) and one PARKED ticket."""
    async with db_sessionmaker() as db:
        suffix = _suffix()
        vehicle_type = VehicleType(
            code=f"EXP-{suffix}", name="Mobil Ekspor", status=VehicleStatus.ACTIVE
        )
        entry_gate = Gate(
            gate_code=suffix[:4] + "E",
            name="Gate Export Masuk",
            type=GateType.GATE_IN,
            status=GateStatus.ONLINE,
        )
        exit_gate = Gate(
            gate_code=suffix[:4] + "X",
            name="Gate Export Keluar",
            type=GateType.GATE_OUT,
            status=GateStatus.ONLINE,
        )
        db.add_all([vehicle_type, entry_gate, exit_gate])
        await db.flush()

        now = datetime.now(UTC)
        completed = ParkTransaction(
            ticket_number=f"EXP-{suffix}-1",
            police_number=f"EX{suffix[:3]}AA",
            vehicle_type_id=vehicle_type.id,
            entry_time=now - timedelta(hours=2),
            exit_time=now - timedelta(hours=1),
            entry_gate_id=entry_gate.id,
            exit_gate_id=exit_gate.id,
            status_parking=ParkingStatus.COMPLETED,
            total_fee=4000,
            detection_method=DetectionMethod.MANUAL,
        )
        parked = ParkTransaction(
            ticket_number=f"EXP-{suffix}-2",
            police_number=f"EX{suffix[:3]}BB",
            vehicle_type_id=vehicle_type.id,
            entry_time=now - timedelta(minutes=30),
            entry_gate_id=entry_gate.id,
            status_parking=ParkingStatus.PARKED,
            detection_method=DetectionMethod.MANUAL,
        )
        db.add_all([completed, parked])
        await db.flush()

        payment = Payment(
            park_transaction_id=completed.id,
            amount=4000,
            method=PaymentMethod.QRIS,
            status=PaymentStatus.SUCCESS,
            paid_at=now - timedelta(hours=1),
        )
        db.add(payment)
        await db.commit()

        ids = {
            "ticket": f"EXP-{suffix}-1",
            "parked_ticket": f"EXP-{suffix}-2",
            "police": f"EX{suffix[:3]}AA",
            "payment_id": payment.id,
            "tx_ids": [completed.id, parked.id],
            "vehicle_type_id": vehicle_type.id,
            "gate_ids": [entry_gate.id, exit_gate.id],
        }
        yield ids

        # Teardown: keep the shared test database clean for the other suites.
        async with db_sessionmaker() as cleanup:
            for pid in [ids["payment_id"]]:
                obj = await cleanup.get(Payment, pid)
                if obj is not None:
                    await cleanup.delete(obj)
            for tid in ids["tx_ids"]:
                obj = await cleanup.get(ParkTransaction, tid)
                if obj is not None:
                    await cleanup.delete(obj)
            vt = await cleanup.get(VehicleType, ids["vehicle_type_id"])
            if vt is not None:
                await cleanup.delete(vt)
            for gid in ids["gate_ids"]:
                g = await cleanup.get(Gate, gid)
                if g is not None:
                    await cleanup.delete(g)
            await cleanup.commit()


EXPORT_ENDPOINTS = [
    "/finance/reports/transactions/export",
    "/finance/reports/pending-tickets/export",
    "/finance/reports/revenue/export",
    "/finance/reports/vehicles/export",
    "/finance/reports/operator-performance/export",
    "/finance/reports/members/export",
    "/finance/reports/gate-events/export",
]

FORMAT_MAGIC = {
    "csv": (b"\xef\xbb\xbf", "text/csv"),
    "xlsx": (b"PK", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pdf": (b"%PDF", "application/pdf"),
}


@pytest.mark.parametrize("endpoint", EXPORT_ENDPOINTS)
@pytest.mark.parametrize("file_format", ["csv", "xlsx", "pdf"])
async def test_report_exports_render(client, endpoint, file_format):
    resp = await client.get(endpoint, params={"format": file_format})
    assert resp.status_code == 200
    magic, media_type = FORMAT_MAGIC[file_format]
    assert resp.headers["content-type"].startswith(media_type)
    assert resp.content.startswith(magic)
    disposition = resp.headers["content-disposition"]
    assert f".{file_format}" in disposition
    assert "attachment" in disposition


async def test_transactions_csv_contains_seeded_row(client, seeded_report_data):
    resp = await client.get("/finance/reports/transactions/export", params={"format": "csv"})
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert seeded_report_data["ticket"] in body
    assert seeded_report_data["police"] in body
    assert "Rp4.000" in body
    assert "QRIS" in body


async def test_revenue_csv_has_summary_and_methods(client, seeded_report_data):
    resp = await client.get("/finance/reports/revenue/export", params={"format": "csv"})
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert "Total Pendapatan" in body
    assert "Pendapatan Harian" in body
    assert "Metode Pembayaran" in body
    assert "QRIS" in body


async def test_pending_tickets_csv_contains_parked_ticket(client, seeded_report_data):
    resp = await client.get("/finance/reports/pending-tickets/export", params={"format": "csv"})
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert seeded_report_data["parked_ticket"] in body


async def test_export_rejects_unknown_format(client):
    resp = await client.get("/finance/reports/transactions/export", params={"format": "xml"})
    assert resp.status_code == 422


def test_guard_export_size_raises():
    with pytest.raises(HTTPException) as exc_info:
        _guard_export_size(10_001)


async def test_transaction_report_shows_no_method_without_payment_row(
    client, db_sessionmaker
):
    """Transactions without a Payment row surface blank (null) payment method."""
    async with db_sessionmaker() as db:
        suffix = _suffix()
        vehicle_type = VehicleType(
            code=f"EXP-{suffix}", name="Mobil Legacy", status=VehicleStatus.ACTIVE
        )
        exit_gate = Gate(
            gate_code=suffix[:4] + "X",
            name="Gate Legacy Keluar",
            type=GateType.GATE_OUT,
            status=GateStatus.ONLINE,
        )
        db.add_all([vehicle_type, exit_gate])
        await db.flush()

        now = datetime.now(UTC)
        tx = ParkTransaction(
            ticket_number=f"EXP-{suffix}-LEG",
            police_number=f"EX{suffix[:3]}LC",
            vehicle_type_id=vehicle_type.id,
            entry_time=now - timedelta(hours=2),
            exit_time=now - timedelta(hours=1),
            entry_gate_id=exit_gate.id,
            exit_gate_id=exit_gate.id,
            status_parking=ParkingStatus.COMPLETED,
            total_fee=4000,
            detection_method=DetectionMethod.MANUAL,
        )
        db.add(tx)
        await db.commit()
        tx_id = tx.id
        vt_id = vehicle_type.id
        gate_id = exit_gate.id

        try:
            report = await finance_reports_crud.get_transaction_report(
                db, page=1, size=100, search=tx.ticket_number
            )
        finally:
            in_db = await db.get(ParkTransaction, tx_id)
            if in_db is not None:
                await db.delete(in_db)
            await db.commit()
            vt = await db.get(VehicleType, vt_id)
            if vt is not None:
                await db.delete(vt)
            g = await db.get(Gate, gate_id)
            if g is not None:
                await db.delete(g)
            await db.commit()

    assert len(report["items"]) == 1
    assert report["items"][0]["payment_method"] is None
