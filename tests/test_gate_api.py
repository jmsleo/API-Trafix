"""Route-level parity tests for the legacy ``/api/*`` wire surface.

Port of ``trafix-api-mock/tests/test_api.py`` against the real service. The
bare app mounts only ``routes.gate_cycle`` with a fresh ``GateCycleService``,
so every handler runs against real Postgres while the MQTT layer stays out.
Assertions that hard-coded the mock's tariff (e.g. ``total == 34000``) are
replaced with checks against our flat rates (MOTOR 2000 / MOBIL 4000 /
OJOL 0 / BUS 6000).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_trafix.routes import gate_cycle as gate_routes
from api_trafix.services.gate_cycle import (
    GateCycleConfig,
    GateCycleService,
    NullPublisher,
)
from api_trafix.services.seed import seed_reference_data
from api_trafix.services.snapshots import SnapshotStore

PLATE = "H488AI"
BASE = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)


class AdvancingClock:
    """Returns the current time, ticking 1s per call, with explicit jumps."""

    def __init__(self, base: datetime) -> None:
        self.current = base

    def __call__(self) -> datetime:
        current = self.current
        self.current += timedelta(seconds=1)
        return current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@pytest.fixture()
async def api(db_sessionmaker, tmp_path):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

    publisher = NullPublisher()
    svc = GateCycleService(
        db_sessionmaker,
        publisher=publisher,
        storage=SnapshotStore(Path(tmp_path)),
        config=GateCycleConfig(
            site_name="Trafix Test",
            site_address="Jl. Test 1",
            storage_dir=Path(tmp_path),
        ),
        clock=AdvancingClock(BASE),
        print_gap_seconds=0,
    )
    app = FastAPI()
    app.include_router(gate_routes.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.gate_cycle = svc

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            svc=svc,
            publisher=publisher,
            clock=svc.clock,
        )


async def _enter(api, plate=PLATE, vehicle_id=1):
    resp = await api.client.post(
        "/api/gatein",
        json={
            "gate": "1",
            "vehicle_id": vehicle_id,
            "plate_num": plate,
            "url_gambar": "",
            "serialNo": "441D6491AF17",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    return body


# -- the push-button entry route --------------------------------------------


async def test_gatein_returns_the_ticket_code(api):
    body = await _enter(api)
    assert body["status"] == "success"
    assert len(body["kode_tiket"]) == 10
    assert body["police_number"] == PLATE


async def test_gatein_prints(api):
    await _enter(api)
    assert len(api.publisher.printed) == 2


async def test_gatein_without_a_plate_still_issues_a_ticket(api):
    body = await _enter(api, plate="")
    assert body["status"] == "success"
    assert body["kode_tiket"]


# -- the LPR-driven entry routes ---------------------------------------------


async def test_lpr_gatein_creates_a_transaction(api):
    resp = await api.client.post(
        "/api/lpr/gatein",
        data={"plate_num": PLATE},
        files={"image": ("CAMIN_LPR.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["transaction_code"]) == 10


async def test_lpr_gatein_requires_plate_and_image(api):
    no_plate = await api.client.post(
        "/api/lpr/gatein", files={"image": ("a.jpg", b"x", "image/jpeg")}
    )
    assert no_plate.status_code == 400
    assert no_plate.json()["message"] == "Missing image or plate_num"

    no_image = await api.client.post("/api/lpr/gatein", data={"plate_num": PLATE})
    assert no_image.status_code == 400


async def test_lpr_gateinimage_attaches_to_an_open_ticket(api):
    ticket = await _enter(api)
    api.clock.advance(minutes=5)
    resp = await api.client.post(
        "/api/lpr/gateinimage",
        data={"transaction_code": ticket["kode_tiket"], "plate_num": PLATE},
        files={"image": ("CAMIN_LPR_2.jpg", b"\xff\xd8fake", "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["camin_lpr"].startswith("storage/")
    assert body["transaction_code"] == ticket["kode_tiket"]


async def test_lpr_gateinimage_404s_for_an_unknown_ticket(api):
    resp = await api.client.post(
        "/api/lpr/gateinimage",
        data={"transaction_code": "0000000000"},
        files={"image": ("a.jpg", b"x", "image/jpeg")},
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "Transaction not found"


async def test_lpr_checkimage_reports_a_reachable_image(api, monkeypatch):
    plate = f"H{uuid.uuid4().hex[:6].upper()}"  # unique so the open-session lookup is unambiguous
    ticket = await _enter(api, plate=plate)
    probe = SimpleNamespace(is_success=True, status_code=200, headers={"content-type": "image/jpeg"})
    monkeypatch.setattr("api_trafix.routes.gate_cycle.httpx.get", lambda *a, **k: probe)

    resp = await api.client.post(
        "/api/lpr/checkimage",
        data={"plate_num": plate, "url_image": "http://lpr/x.jpg"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["transaction_code"] == ticket["kode_tiket"]


async def test_lpr_checkimage_rejects_a_non_image_url(api, monkeypatch):
    await _enter(api)
    probe = SimpleNamespace(is_success=True, status_code=200, headers={"content-type": "text/html"})
    monkeypatch.setattr("api_trafix.routes.gate_cycle.httpx.get", lambda *a, **k: probe)

    resp = await api.client.post(
        "/api/lpr/checkimage",
        data={"plate_num": PLATE, "url_image": "http://lpr/index.html"},
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "URL is reachable but not an image"


async def test_lpr_checkimage_404s_without_an_open_session(api, monkeypatch):
    probe = SimpleNamespace(is_success=True, status_code=200, headers={"content-type": "image/jpeg"})
    monkeypatch.setattr("api_trafix.routes.gate_cycle.httpx.get", lambda *a, **k: probe)

    resp = await api.client.post(
        "/api/lpr/checkimage",
        data={"plate_num": "NOPE", "url_image": "http://lpr/x.jpg"},
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "Active transaction not found for this plate_num"


async def test_lpr_checkimage_requires_url_and_plate(api):
    resp = await api.client.post("/api/lpr/checkimage", data={"plate_num": PLATE})
    assert resp.status_code == 400
    assert resp.json()["message"] == "Missing url_image or plate_num"


# -- the automated LPR exit --------------------------------------------------


async def test_lpr_gateout_works(api):
    """flow.md §7.1: this route 500s on site because the method is missing."""
    ticket = await _enter(api)
    api.clock.advance(hours=2)

    resp = await api.client.post(
        "/api/lpr/gateout",
        json={
            "gate_out": "2",
            "transaction_code": ticket["kode_tiket"],
            "plate_num": PLATE,
            "url_gambar": "",
        },
    )
    assert resp.status_code == 200, "production returns 500 here"
    body = resp.json()
    assert body["status"] == "success_ticket"
    assert body["total"] > 0
    assert api.publisher.barriers == [("2", True)]


async def test_lpr_gateout_by_plate_alone(api):
    await _enter(api)
    api.clock.advance(hours=1)
    resp = await api.client.post("/api/lpr/gateout", json={"gate_out": "2", "plate_num": PLATE})
    assert resp.json()["status"] == "success_ticket"


async def test_lpr_gateout_for_an_unknown_vehicle(api):
    resp = await api.client.post("/api/lpr/gateout", json={"gate_out": "2", "plate_num": "ZZ9999ZZ"})
    assert resp.json()["status"] == "notfound"


async def test_lpr_gateout_refuses_a_used_ticket(api):
    ticket = await _enter(api)
    api.clock.advance(hours=1)
    await api.client.post("/api/lpr/gateout", json={"transaction_code": ticket["kode_tiket"]})

    again = await api.client.post(
        "/api/lpr/gateout", json={"transaction_code": ticket["kode_tiket"]}
    )
    assert again.json()["status"] == "ticket_used"


# -- the cashier path --------------------------------------------------------


async def test_detailtransaction_accepts_multipart(api):
    """The real cashier app posts multipart here."""
    ticket = await _enter(api)
    api.clock.advance(hours=2)

    resp = await api.client.post(
        "/api/gateout/detailtransaction",
        files={
            "transaction_code": (None, ticket["kode_tiket"]),
            "gate_out": (None, "2"),
            "admin_id": (None, "1"),
            "shift_id": (None, "1"),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["status_code"] == 200
    assert body["data"]["transaction_code"] == ticket["kode_tiket"]
    assert body["data"]["total"] > 0
    assert body["data"]["duration"]


async def test_detailtransaction_does_not_settle(api):
    ticket = await _enter(api)
    api.clock.advance(hours=1)
    await api.client.post(
        "/api/gateout/detailtransaction",
        data={"transaction_code": ticket["kode_tiket"]},
    )
    # Still chargeable, so it was not checked out.
    second = await api.client.post(
        "/api/gateout/detailtransaction",
        data={"transaction_code": ticket["kode_tiket"]},
    )
    assert second.json()["data"]["total"] > 0


async def test_detailtransaction_404s_for_an_unknown_ticket(api):
    resp = await api.client.post(
        "/api/gateout/detailtransaction", data={"transaction_code": "0000000000"}
    )
    assert resp.status_code == 404
    assert resp.json()["status"] == "notfound"


async def test_gateoutkasir_accepts_form_encoding_and_settles(api):
    ticket = await _enter(api)
    api.clock.advance(hours=3)

    resp = await api.client.put(
        "/api/gateout/gateoutKasir",
        data={
            "transaction_code": ticket["kode_tiket"],
            "gate_out": "2",
            "admin_id": "1",
            "shift_id": "1",
            "discount_card": "",
            "total_discount": "0",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["status_code"] == 200
    assert body["data"]["total"] > 0
    assert api.publisher.barriers == [("2", True)], "production never opens the exit (§7.6)"


async def test_gateoutkasir_reports_an_already_used_ticket(api):
    ticket = await _enter(api)
    api.clock.advance(hours=1)
    await api.client.put(
        "/api/gateout/gateoutKasir", data={"transaction_code": ticket["kode_tiket"]}
    )

    again = await api.client.put(
        "/api/gateout/gateoutKasir", data={"transaction_code": ticket["kode_tiket"]}
    )
    assert again.json()["status"] == "already_paid"


async def test_gateoutkasir_lost_ticket_without_a_code_creates_a_transaction(api):
    """Tiket hilang: plate + jenis kendaraan only, no ticket number needed."""
    resp = await api.client.put(
        "/api/gateout/gateoutKasir",
        data={
            "police_number": "h 488 ai",
            "vehicle_id": "2",
            "lost_ticket": "1",
            "gate_out": "2",
            "admin_id": "1",
            "shift_id": "1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["total"] == 34000  # MOBIL lost ticket: ticket_charge 30000 + base 4000
    assert body["data"]["police_number"] == PLATE
    assert api.publisher.barriers == [("2", True)]


async def test_gateoutkasir_lost_ticket_requires_a_plate(api):
    resp = await api.client.put(
        "/api/gateout/gateoutKasir",
        data={"vehicle_id": "1", "lost_ticket": "1"},
    )
    assert resp.status_code == 400
    assert resp.json()["status"] == "error"


async def test_gateoutkasir_lost_ticket_for_ojol_paket_is_free(api):
    """Ojol/Paket has no tariff: a lost ticket settles at Rp 0."""
    resp = await api.client.put(
        "/api/gateout/gateoutKasir",
        data={
            "police_number": "h 488 ai",
            "vehicle_id": "3",
            "lost_ticket": "1",
            "gate_out": "2",
            "admin_id": "1",
            "shift_id": "1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["total"] == 0
    assert body["data"]["vehicle_id"] == 3
    assert api.publisher.barriers == [("2", True)]


# -- checkimagegateout -------------------------------------------------------


async def test_checkimagegateout_returns_the_laravel_nested_shape(api):
    await _enter(api)
    api.clock.advance(minutes=30)
    resp = await api.client.post(
        "/api/lpr/checkimagegateout", params={"plate_num": PLATE}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert {"image", "gatein", "gateout"} <= set(body)
    assert body["gatein"]["transaction_code"]
    assert body["gatein"]["police_number"] == PLATE
    assert body["image"] == {
        "available": False,
        "message": "No url_image provided",
        "url_image": None,
    }


async def test_checkimagegateout_404s_like_the_real_one(api):
    resp = await api.client.post("/api/lpr/checkimagegateout", params={"plate_num": "NOPE"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["message"].lower()


# -- the automated RFID exit (PUT /api/lpr/gateoutcard) ----------------------


async def test_lpr_gateoutcard_resolves_a_member(api):
    entered = await api.client.post(
        "/api/gatein/card",
        json={
            "gate": "1",
            "card_no": "006343040",
            "serialNo": "441D6491AF17",
            "vehicle_id": 1,
        },
    )
    assert entered.status_code == 200

    api.clock.advance(hours=1)
    resp = await api.client.put(
        "/api/lpr/gateoutcard",
        data={
            "card": "006343040",
            "gate_out": "2",
            "plate_num": "H4818AI",
            "url_gambar": "",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success_member"}


async def test_lpr_gateoutcard_resolves_a_ticket(api):
    ticket = await _enter(api)
    api.clock.advance(hours=1)
    resp = await api.client.put(
        "/api/lpr/gateoutcard",
        data={"card": ticket["kode_tiket"], "gate_out": "2", "plate_num": PLATE},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success_ticket"}


async def test_lpr_gateoutcard_reports_an_unknown_card(api):
    resp = await api.client.put(
        "/api/lpr/gateoutcard",
        data={"card": "0000000001", "gate_out": "2", "plate_num": "ZZ9999ZZ"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "failed_member"}


async def test_lpr_gateoutcard_refuses_a_used_ticket(api):
    ticket = await _enter(api)
    api.clock.advance(hours=1)
    await api.client.put(
        "/api/lpr/gateoutcard", data={"card": ticket["kode_tiket"], "gate_out": "2"}
    )
    again = await api.client.put(
        "/api/lpr/gateoutcard", data={"card": ticket["kode_tiket"], "gate_out": "2"}
    )
    assert again.json() == {"status": "ticket_used"}


# -- manual re-entry (the ticket never printed) ------------------------------


async def test_manual_transaction_for_a_motor(api):
    resp = await api.client.post(
        "/api/transactions",
        json={"police_number": "h 488 ai", "vehicle_id": "1", "gate": "1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    assert len(data["transaction_code"]) == 10
    assert data["police_number"] == PLATE
    assert data["total"] == 2000
    assert data["time_checkin"] == data["time_checkout"]
    assert data["payment_status"] == "lunas"


async def test_manual_transaction_for_an_ojol_paket_is_free(api):
    resp = await api.client.post(
        "/api/transactions",
        json={"police_number": "H 1234 DE", "vehicle_id": "3"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["vehicle_id"] == 3
    assert data["payment_status"] == "lunas"


async def test_manual_transaction_requires_a_plate(api):
    resp = await api.client.post(
        "/api/transactions", json={"police_number": "", "vehicle_id": "1"}
    )
    assert resp.status_code == 400
    assert resp.json()["status"] == "error"


async def test_manual_transaction_requires_a_vehicle(api):
    resp = await api.client.post(
        "/api/transactions", json={"police_number": "H 488 AI", "vehicle_id": ""}
    )
    assert resp.status_code == 400
    assert resp.json()["status"] == "error"


# -- lookups and CORS --------------------------------------------------------


async def test_list_members_returns_the_seeded_member(api):
    resp = await api.client.get("/api/members")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    plates = {m["police_number"] for m in body["data"]}
    assert "H4818AI" in plates  # the demo member
    for member in body["data"]:
        assert {
            "name",
            "police_number",
            "member_code",
            "vehicle_id",
            "time_limit",
        } <= set(member)


async def test_list_transactions_returns_the_open_session(api):
    ticket = await _enter(api)
    resp = await api.client.get("/api/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    codes = {t["transaction_code"] for t in body["data"]}
    assert ticket["kode_tiket"] in codes


async def test_preflight_from_the_tauri_origin_is_allowed(api):
    resp = await api.client.options(
        "/api/gateout/gateoutKasir",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert resp.status_code in (200, 204)
    assert "access-control-allow-origin" in resp.headers


async def test_health(api):
    resp = await api.client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
