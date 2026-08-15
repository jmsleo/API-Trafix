"""Full-stack end-to-end: the API, orchestrator, MQTT bus and a real broker.

One uvicorn process runs ``api_trafix.main:app`` (gate cycle + orchestrator +
publisher) against the shared ``trafix_test`` database, talking to an
in-process amqtt broker. A background capture client plays the gate hardware:
it publishes controller events (``inputInfo`` / ``readCard``) and watches the
server's command topics (prints, relays, signage). A tiny ``/checklpr`` HTTP
stub stands in for the entry LPR unit, so the ticket button can pick up a plate
the way it does on site.

Port of ``trafix-api-mock/tests/test_e2e.py`` without Docker or extra
processes: the broker is in-process, and the LPR/controller mocks are collapsed
into MQTT messages and the stub server.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aiomqtt
import asyncpg
import httpx
import pytest
from amqtt.broker import Broker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://trafix:trafix@localhost:5432/trafix_test",
)
PG_URL = DB_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

# Matches BUTTON_DEBOUNCE_SECONDS below; every entry-triggering action must be
# spaced by more than this so the orchestrator's debounce never eats a ticket.
DEBOUNCE_SECONDS = 2.0

ENTRY_SERIAL = "441D6491AF17"
EXIT_SERIAL = "771122334455"
MEMBER_CARD = "006343040"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _unique_plate() -> str:
    return f"H{uuid.uuid4().hex[:6].upper()}"


# -- database helpers (short-lived connections, tests are sync) ---------------


def _db_fetchrow(sql: str, *params):
    async def run():
        conn = await asyncpg.connect(PG_URL)
        try:
            return await conn.fetchrow(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def _db_fetch(sql: str, *params):
    async def run():
        conn = await asyncpg.connect(PG_URL)
        try:
            return await conn.fetch(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def _db_execute(sql: str, *params) -> None:
    async def run():
        conn = await asyncpg.connect(PG_URL)
        try:
            await conn.execute(sql, *params)
        finally:
            await conn.close()

    asyncio.run(run())


# -- the entry LPR HTTP stub --------------------------------------------------


class _LprHandler(BaseHTTPRequestHandler):
    server_version = "LprStub/1"

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/").endswith("/checklpr"):
            body = json.dumps(
                {"plate_num": self.server.plate, "url_gambar": self.server.image_url}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class _LprServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.plate = ""
        self.image_url = ""
        super().__init__(("127.0.0.1", 0), _LprHandler)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


# -- the in-process broker + capture client -----------------------------------


class MqttRig:
    """The amqtt broker and a capture client, both on one background loop.

    Messages the server publishes are appended to ``self.seen``; tests poll it
    through :meth:`mark` / :meth:`wait_new` / :meth:`count_new`. Publishing to
    the broker is done with ``run_coroutine_threadsafe``.
    """

    def __init__(self, port: int):
        self.port = port
        self.seen: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._collector: asyncio.Future | None = None
        self._thread = threading.Thread(target=self._run, name="e2e-mqtt", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=20):
            raise RuntimeError("MQTT rig never started")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start())
        self._loop.run_forever()

    async def _start(self) -> None:
        broker = Broker(
            {
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
                "auth": {"allow-anonymous": True},
            }
        )
        await broker.start()
        client = aiomqtt.Client(
            hostname="127.0.0.1", port=self.port, identifier="e2e-capture"
        )
        await client.__aenter__()
        for topic in ("/GATE/IN/1", "/GATE/IN/1/status", "/GATE/OUT/2"):
            await client.subscribe(topic)
        self._client = client
        self._collector = asyncio.ensure_future(self._collect())
        self._ready.set()

    async def _collect(self) -> None:
        async for message in self._client.messages:
            with self._lock:
                self.seen.append((str(message.topic), message.payload.decode()))

    def publish(self, topic: str, payload: str) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._client.publish(topic, payload, qos=1), self._loop
        )
        future.result(timeout=10)

    def mark(self) -> int:
        with self._lock:
            return len(self.seen)

    def wait_new(self, mark: int, predicate, timeout: float = 15.0) -> tuple[str, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for message in self.seen[mark:]:
                    if predicate(message):
                        return message
            time.sleep(0.05)
        raise AssertionError("no matching MQTT message arrived in time")

    def count_new(self, mark: int, predicate) -> int:
        with self._lock:
            return sum(1 for message in self.seen[mark:] if predicate(message))

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)


# -- device seeding and the uvicorn subprocess --------------------------------


def _seed_devices(lpr_url: str) -> None:
    _db_execute(
        "INSERT INTO gates (id, name, gate_code, type, status, created_at, updated_at) VALUES "
        "($1, 'Gate Masuk', '1', 'gate_in', 'online', now(), now()) "
        "ON CONFLICT (gate_code) DO NOTHING",
        uuid.uuid4(),
    )
    _db_execute(
        "INSERT INTO gates (id, name, gate_code, type, status, created_at, updated_at) VALUES "
        "($1, 'Gate Keluar', '2', 'gate_out', 'online', now(), now()) "
        "ON CONFLICT (gate_code) DO NOTHING",
        uuid.uuid4(),
    )
    gate_ids = {
        row["gate_code"]: row["id"]
        for row in _db_fetch("SELECT id, gate_code FROM gates WHERE gate_code IN ('1', '2')")
    }

    devices = [
        ("E2E Entry Controller", "Controller", gate_ids["1"], ENTRY_SERIAL,
         {"serial_no": ENTRY_SERIAL}),
        ("E2E Exit Controller", "Controller", gate_ids["2"], EXIT_SERIAL,
         {"serial_no": EXIT_SERIAL}),
        ("E2E Entry LPR", "Camera LPR", gate_ids["1"], "127.0.0.1",
         {"base_url": lpr_url, "serves_http": True}),
        ("E2E Exit LPR", "Camera LPR", gate_ids["2"], "127.0.0.1",
         {"serves_http": False}),
    ]
    _db_execute("DELETE FROM devices WHERE name LIKE 'E2E %'")
    for name, kind, gate_id, ip, config in devices:
        _db_execute(
            "INSERT INTO devices (id, gate_id, name, type, ip_address, config, status) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'online')",
            uuid.uuid4(), gate_id, name, kind, ip, json.dumps(config),
        )


def _cleanup_devices() -> None:
    _db_execute("DELETE FROM devices WHERE name LIKE 'E2E %'")


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.4)
    raise TimeoutError(f"{url} never answered")


def _wait_row(sql: str, *params, timeout: float = 20.0, predicate=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = _db_fetchrow(sql, *params)
        if row is not None and (predicate is None or predicate(row)):
            return row
        time.sleep(0.3)
    raise AssertionError(f"DB row never appeared: {sql}")


class E2ESystem:
    def __init__(self, *, rig, lpr, api_url: str) -> None:
        self.rig = rig
        self.lpr = lpr
        self.api_url = api_url
        self._last_press = 0.0

    def spaced(self) -> None:
        """Wait out the orchestrator's button debounce before the next entry."""
        remaining = DEBOUNCE_SECONDS + 0.6 - (time.monotonic() - self._last_press)
        if remaining > 0:
            time.sleep(remaining)
        self._last_press = time.monotonic()

    def set_plate(self, plate: str) -> None:
        self.lpr.plate = plate
        self.lpr.image_url = ""

    def press_button(self, gate: str = "1") -> None:
        self.rig.publish(
            f"/GATE/event/{gate}",
            json.dumps(
                {
                    "method": "inputInfo",
                    "serialNo": ENTRY_SERIAL,
                    "data": {"input2": 1},
                }
            ),
        )

    def announce_arrival(self, gate: str = "1") -> None:
        self.rig.publish(
            f"/GATE/event/{gate}",
            json.dumps(
                {
                    "method": "inputInfo",
                    "serialNo": ENTRY_SERIAL,
                    "data": {"input3": 1},
                }
            ),
        )

    def clear_lane(self, gate: str = "1") -> None:
        self.rig.publish(
            f"/GATE/event/{gate}",
            json.dumps(
                {
                    "method": "inputInfo",
                    "serialNo": ENTRY_SERIAL,
                    "data": {"input4": 1},
                }
            ),
        )

    def tap_member_card(self) -> None:
        self.rig.publish(
            "/GATE/event/1",
            json.dumps(
                {
                    "method": "readCard",
                    "serialNo": ENTRY_SERIAL,
                    "data": {"reader": 1, "cardLen": 10, "cardNo": MEMBER_CARD},
                }
            ),
        )


@pytest.fixture(scope="module")
def e2e_system(tmp_path_factory, db_engine):
    """One app + broker + LPR stub for the whole module."""
    storage_dir = tmp_path_factory.mktemp("e2e-storage")
    mqtt_port = _free_port()
    api_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"

    rig = MqttRig(mqtt_port)
    lpr = _LprServer()
    threading.Thread(target=lpr.serve_forever, name="e2e-lpr", daemon=True).start()
    _seed_devices(lpr.base_url)

    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": DB_URL,
            "MQTT_ENABLED": "true",
            "MQTT_HOST": "127.0.0.1",
            "MQTT_PORT": str(mqtt_port),
            "MQTT_USERNAME": "",
            "MQTT_PASSWORD": "",
            "MQTT_CLIENT_ID_PREFIX": f"e2e-{uuid.uuid4().hex[:8]}",
            "API_BASE_URL": api_url,
            "STORAGE_DIR": str(storage_dir),
            "BUTTON_DEBOUNCE_SECONDS": str(DEBOUNCE_SECONDS),
            "LPR_TIMEOUT_SECONDS": "2",
            "LPR_RETRIES": "0",
        }
    )
    server = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "api_trafix.main:app",
            "--port",
            str(api_port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        try:
            _wait_for_http(f"{api_url}/api/health")
        except TimeoutError:
            out, _ = server.communicate(timeout=5)
            raise RuntimeError(f"uvicorn never came up:\n{out}")
        # The MQTT bus connects a beat after the app serves; give it time so the
        # first event is not published to a broker with no subscriber yet.
        time.sleep(2.5)
        yield E2ESystem(rig=rig, lpr=lpr, api_url=api_url)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        lpr.shutdown()
        lpr.server_close()
        _cleanup_devices()
        rig.stop()


# -- the scenarios ------------------------------------------------------------


def _is(method: str):
    def check(message: tuple[str, str]) -> bool:
        try:
            return json.loads(message[1]).get("method") == method
        except (json.JSONDecodeError, AttributeError):
            return False

    return check


def test_button_press_issues_a_ticket_and_opens_the_barrier(e2e_system):
    system = e2e_system
    plate = _unique_plate()
    system.set_plate(plate)
    system.spaced()

    marker = system.rig.mark()
    system.announce_arrival()
    system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1/status" and "welcome" in m[1])
    system.press_button()

    tx = _wait_row(
        "SELECT pt.ticket_number, g.gate_code AS gate, pt.status_parking, "
        "pt.police_number FROM park_transactions pt "
        "JOIN gates g ON g.id = pt.entry_gate_id "
        "WHERE pt.police_number = $1 ORDER BY pt.created_at DESC LIMIT 1",
        plate,
    )
    assert tx["gate"] == "1"
    assert tx["status_parking"] == "Parked"
    assert tx["ticket_number"]

    system.clear_lane()
    # Two print halves (QR + body) then the relay opening the barrier.
    # ``wait_new`` polls, because the halves are published ~0.2s apart and an
    # instantaneous ``count_new`` would race the second one.
    system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("txUartData")(m))
    system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("txUartData")(m))
    assert system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("outputCtrl")(m))
    system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1/status" and "thanks" in m[1])


def test_a_plate_the_camera_cannot_read_still_gets_a_ticket(e2e_system):
    system = e2e_system
    system.set_plate("")
    system.spaced()
    before = time.time()

    marker = system.rig.mark()
    system.announce_arrival()
    system.press_button()

    tx = _wait_row(
        "SELECT pt.police_number, pt.ticket_number, g.gate_code AS gate "
        "FROM park_transactions pt JOIN gates g ON g.id = pt.entry_gate_id "
        "WHERE pt.created_at > to_timestamp($1) ORDER BY pt.created_at DESC LIMIT 1",
        before,
    )
    assert tx["police_number"] is None, "4 of 6 on-site tickets record no plate (§7.7)"
    assert tx["ticket_number"]
    assert system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("outputCtrl")(m))
    system.clear_lane()


def test_repeat_button_press_does_not_issue_two_tickets(e2e_system):
    system = e2e_system
    plate = _unique_plate()
    system.set_plate(plate)
    system.spaced()

    system.announce_arrival()
    system.press_button()
    tx = _wait_row(
        "SELECT pt.ticket_number, pt.police_number FROM park_transactions pt "
        "WHERE pt.police_number = $1 ORDER BY pt.created_at DESC LIMIT 1",
        plate,
    )
    first_code = tx["ticket_number"]

    time.sleep(0.8)  # within the debounce window
    system.press_button()
    time.sleep(DEBOUNCE_SECONDS + 0.5)

    latest = _db_fetchrow(
        "SELECT pt.ticket_number FROM park_transactions pt "
        "JOIN gates g ON g.id = pt.entry_gate_id "
        "WHERE g.gate_code = '1' ORDER BY pt.created_at DESC LIMIT 1"
    )
    assert latest["ticket_number"] == first_code, "a second press issued a second ticket"
    system.clear_lane()


def test_an_rfid_card_opens_the_gate_for_a_member(e2e_system):
    system = e2e_system
    system.spaced()

    marker = system.rig.mark()
    system.tap_member_card()

    tx = _wait_row(
        "SELECT pt.ticket_number, pt.card_number, pt.total_fee, pt.payment_status, "
        "pt.detection_method FROM park_transactions pt "
        "WHERE pt.card_number = $1 ORDER BY pt.created_at DESC LIMIT 1",
        MEMBER_CARD,
    )
    assert tx["ticket_number"]
    assert tx["card_number"] == MEMBER_CARD
    assert tx["total_fee"] == 0, "an active member parks free"
    assert tx["payment_status"] == "lunas"

    # No paper ticket is printed for a member; the barrier still opens.
    assert system.rig.count_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("txUartData")(m)) == 0
    assert system.rig.wait_new(marker, lambda m: m[0] == "/GATE/IN/1" and _is("outputCtrl")(m))
    system.clear_lane()


def test_the_automated_exit_path_works(e2e_system):
    """flow.md §7.1: the exit LPR announces a plate and the gate releases."""
    system = e2e_system
    plate = _unique_plate()
    system.set_plate(plate)
    system.spaced()

    system.announce_arrival()
    system.press_button()
    entry = _wait_row(
        "SELECT pt.ticket_number, pt.exit_time FROM park_transactions pt "
        "WHERE pt.police_number = $1 ORDER BY pt.created_at DESC LIMIT 1",
        plate,
    )
    assert entry["exit_time"] is None

    marker = system.rig.mark()
    system.rig.publish(
        "gate/out/2/pos",
        json.dumps({"plate_num": plate, "url_gambar": ""}),
    )

    settled = _wait_row(
        "SELECT pt.payment_status, pt.status_parking, pt.total_fee FROM park_transactions pt "
        "WHERE pt.police_number = $1 AND pt.exit_time IS NOT NULL ORDER BY pt.created_at DESC LIMIT 1",
        plate,
    )
    assert settled["payment_status"] == "lunas"
    assert settled["status_parking"] == "Completed"
    assert settled["total_fee"] == 0, "left within the grace period"
    # The exit barrier must actually be commanded (§7.6).
    assert system.rig.wait_new(marker, lambda m: m[0] == "/GATE/OUT/2" and _is("outputCtrl")(m))
    system.clear_lane()


def test_a_used_ticket_cannot_be_reused(e2e_system):
    """Straight HTTP proof that the missing method now exists (§7.1)."""
    system = e2e_system
    plate = _unique_plate()
    system.set_plate(plate)
    system.spaced()

    system.announce_arrival()
    system.press_button()
    entry = _wait_row(
        "SELECT pt.ticket_number FROM park_transactions pt "
        "WHERE pt.police_number = $1 ORDER BY pt.created_at DESC LIMIT 1",
        plate,
    )

    for _ in range(2):
        response = httpx.post(
            f"{system.api_url}/api/lpr/gateout",
            json={
                "gate_out": "2",
                "transaction_code": entry["ticket_number"],
                "plate_num": plate,
            },
            timeout=10,
        )
    assert response.status_code == 200, "production returns 500 here"
    assert response.json()["status"] == "ticket_used"
    system.clear_lane()
