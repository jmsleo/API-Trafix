import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api_trafix.config.database import async_session_maker, init_db
from api_trafix.config.redis import close_redis
from api_trafix.config.settings import get_settings
from api_trafix.models import Backup, BackupStatus
from sqlalchemy import update as sa_update
from api_trafix.core.middleware import (
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
)
from api_trafix.core.scheduler import run_periodic_tasks
from api_trafix.services.device_registry import DeviceRegistry
from api_trafix.services.gate_cycle import GateCycleConfig, GateCycleService, NullPublisher
from api_trafix.services.lpr_plates import LprPlateBuffer
from api_trafix.services.mqtt_bus import MqttBus
from api_trafix.services.orchestrator import Orchestrator
from api_trafix.services.publisher import MqttPublisher
from api_trafix.services.seed import seed_reference_data
from api_trafix.services.signage_publisher import SignagePublisher
from api_trafix.services.snapshots import SnapshotStore
from api_trafix.routes import (
    backup,
    finance_dashboard,
    finance_reports,
    gate_cycle,
    member,
    member_subscription,
    operator_session,
    operator_shift_assignment,
    parking_rate,
    pos,
    shift,
    subscription_plan,
    users,
    vehicle_type,
)
from api_trafix.routes.auth import router as auth_router
from api_trafix.routes import member, shift, vehicle_type, parking_rate, users, finance_dashboard, finance_reports, operator_shift_assignment, operator_session, subscription_plan, member_subscription, signage, backup, audit_log
from api_trafix.routes import devices, gates

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session_maker() as db:
        await seed_reference_data(db)

    # Reset any backups stuck in RUNNING from a previous crash/restart.
    async with async_session_maker() as db:
        await db.execute(
            sa_update(Backup)
            .where(Backup.status == BackupStatus.RUNNING)
            .values(
                status=BackupStatus.FAILED,
                error_message="Process restarted while operation was in progress",
            )
        )
        await db.commit()

    settings = get_settings()
    storage = SnapshotStore(Path(settings.storage_dir))
    registry = DeviceRegistry(async_session_maker)
    await registry.reload()
    app.state.device_registry = registry
    app.state.snapshot_store = storage
    plates = LprPlateBuffer()
    app.state.lpr_plates = plates

    orchestrator: Orchestrator | None = None
    signage_publisher: SignagePublisher | None = None
    if settings.mqtt_enabled:
        bus = MqttBus(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username or None,
            password=settings.mqtt_password or None,
            client_id=settings.mqtt_client_id_prefix,
            keepalive=settings.mqtt_keepalive,
        )
        mirrors: list[MqttBus] = []
        for index, broker in enumerate(settings.signage_legacy_brokers):
            mirror = MqttBus(
                host=str(broker.get("host") or "127.0.0.1"),
                port=int(broker.get("port") or 1883),
                username=broker.get("username") or None,
                password=broker.get("password") or None,
                client_id=f"{settings.mqtt_client_id_prefix}-signage-mirror-{index}",
                keepalive=settings.mqtt_keepalive,
            )
            await mirror.start()
            mirrors.append(mirror)
        signage_publisher = SignagePublisher(
            bus, mirrors, base_url=settings.signage_public_base_url
        )
        app.state.signage_publisher = signage_publisher
        publisher = MqttPublisher(
            bus,
            registry,
            pulse_ms=settings.barrier_pulse_ms,
            beep_ms=settings.barrier_beep_ms,
        )
    else:
        app.state.signage_publisher = None
        publisher = NullPublisher()

    app.state.gate_cycle = GateCycleService(
        async_session_maker,
        publisher=publisher,
        storage=storage,
        config=GateCycleConfig(
            site_name=settings.site_name,
            site_address=settings.site_address,
            storage_dir=Path(settings.storage_dir),
            require_plate_match=settings.require_plate_match,
            command_exit_barrier=settings.command_exit_barrier,
        ),
    )

    if settings.mqtt_enabled:
        orchestrator = Orchestrator(
            settings=settings,
            bus=bus,
            registry=registry,
            plates=plates,
            signage=signage_publisher,
        )
        await orchestrator.start()

        if signage_publisher is not None:
            # Push a full content sync once the brokers are up, so a display
            # that just came online does not wait for the periodic sync.
            await asyncio.gather(
                *(candidate.wait_connected(15) for candidate in signage_publisher.buses)
            )
            async with async_session_maker() as db:
                await signage_publisher.sync_from_db(db)

    background_task = asyncio.create_task(run_periodic_tasks(signage=signage_publisher))
    yield
    background_task.cancel()
    with suppress(asyncio.CancelledError):
        await background_task
    if orchestrator is not None:
        await orchestrator.stop()
    if signage_publisher is not None:
        for mirror in signage_publisher.mirrors:
            await mirror.stop()
    storage.shutdown()
    await close_redis()

app = FastAPI(
    title=get_settings().app_name,
    version=get_settings().app_version,
    description="Fix Trafing System API - Admin, Teknisi, Operator",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().debug else None,
    redoc_url="/redoc" if get_settings().debug else None,
)

app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Membersihkan objek error agar aman di-serialize ke JSON
    errors = []
    for error in exc.errors():
        err_copy = error.copy()
        if "ctx" in err_copy:
            err_copy["ctx"] = {k: str(v) for k, v in err_copy["ctx"].items()}
        errors.append(err_copy)

    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed", "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    settings = get_settings()
    if settings.debug:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "error": str(exc)},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.include_router(auth_router)
app.include_router(users.router)
app.include_router(vehicle_type.router)
app.include_router(shift.router)
app.include_router(member.router)
app.include_router(parking_rate.router)
app.include_router(finance_dashboard.router)
app.include_router(finance_reports.router)
app.include_router(operator_session.router)
app.include_router(operator_shift_assignment.router)
app.include_router(subscription_plan.router)
app.include_router(member_subscription.router)
app.include_router(signage.router)
app.include_router(backup.router)
app.include_router(audit_log.router)
app.include_router(gate_cycle.router)
app.include_router(pos.router)
app.include_router(gates.router)
app.include_router(devices.router)
storage_dir = Path(get_settings().storage_dir)
storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=storage_dir), name="storage")

@app.get("/")
async def root():
    return {
        "app": get_settings().app_name,
        "version": get_settings().app_version,
        "status": "running",
        "docs": "/docs" if get_settings().debug else None,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/healt", include_in_schema=False)
async def health_check_legacy():
    return {"status": "healthy"}


def _parse_multipart(body: bytes, content_type: str) -> list[dict[str, str]]:
    """Split a ``multipart/form-data`` body into its parts.

    The ECV86 camera uploads snapshots as raw multipart (``sn`` + ``bigFile``)
    and ``python-multipart`` is not a dependency, so parse it directly.
    """
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        return []
    boundary = ("--" + match.group(1)).encode()
    parts: list[dict[str, str]] = []
    for raw in body.split(boundary):
        if raw in (b"", b"--", b"\r\n"):
            continue
        raw = raw.lstrip(b"\r\n")
        if raw.startswith(b"--"):
            break
        header_blob, _, content = raw.partition(b"\r\n\r\n")
        headers: dict[str, str] = {}
        for line in header_blob.decode("latin1").split("\r\n"):
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        name = filename = None
        for match_ in re.finditer(r'name="([^"]*)"|filename="([^"]*)"', headers.get("content-disposition", "")):
            if match_.group(1) is not None:
                name = match_.group(1)
            if match_.group(2) is not None:
                filename = match_.group(2)
        parts.append(
            {
                "name": name or "",
                "filename": filename or "",
                "content_type": headers.get("content-type", ""),
                "content": content.rstrip(b"\r\n"),
            }
        )
    return parts


@app.post("/api/lpr/camera/upload", include_in_schema=False)
async def camera_upload(request: Request):
    """Receive the ECV86 camera's pushed snapshot and attach it to the
    buffered plate read for the gate-in lane."""
    body = await request.body()
    parts = _parse_multipart(body, request.headers.get("content-type", ""))
    plates = request.app.state.lpr_plates
    store: SnapshotStore = request.app.state.snapshot_store

    saved = []
    for part in parts:
        if not part["filename"]:
            continue
        basename = part["filename"].rstrip("/").rsplit("/", 1)[-1]
        relative = store.save_upload(
            f"lpr/gatein/{SnapshotStore.lpr_filename(part['filename'])}",
            part["content"],
        )
        gate = plates.attach_image(basename, relative)
        saved.append(
            {
                "field": part["name"],
                "basename": basename,
                "bytes": len(part["content"]),
                "gate": gate,
                "path": relative,
            }
        )
        print(
            f"camera-upload field={part['name']} basename={basename} "
            f"bytes={len(part['content'])} gate={gate} -> {relative}",
            flush=True,
        )

    if not saved:
        print(
            f"camera-upload: no file parts (ct={request.headers.get('content-type')} "
            f"len={len(body)})",
            flush=True,
        )
    return JSONResponse({"status": "ok", "stored": saved})
