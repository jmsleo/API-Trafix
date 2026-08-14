"""Legacy ``/api/*`` wire routes for the gate-in / gate-out cycle.

Route names, request fields and response shapes follow
``trafix-api-mock/trafix/api.py`` (itself a port of ``routes/api.php`` and the
responses captured on the wire, flow.md §6, §9), so the existing Tauri
cashier frontend and the LPR units keep working against this server unchanged.

The one behavioural difference is the point of the exercise:
``POST /api/lpr/gateout`` is implemented here. In production that route points
at a method that does not exist and returns 500 on every automated exit.

Unlike the mock, these endpoints are deliberately API-only: the cashier desk
is a separate Tauri app, so no HTML pages are served.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api_trafix.config.settings import get_settings
from api_trafix.crud.park_transaction import list_recent
from api_trafix.models import Member, MemberVehicle
from api_trafix.services import gate_cycle as service
from api_trafix.services.gate_cycle import GateCycleService, _member_context
from api_trafix.services.vehicles import vehicle_id_of

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _service(request: Request) -> GateCycleService:
    return request.app.state.gate_cycle


def _json(payload: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


@router.post("/gatein")
async def gatein(request: Request) -> JSONResponse:
    """Issue a ticket and print it.

    Called by the orchestrator over loopback, which is why it never appears in
    a capture of the external interface (flow.md §3).
    """
    body = await _body(request)
    result = await _service(request).gate_in(
        gate=str(body.get("gate", "1")),
        vehicle_id=_int(body.get("vehicle_id")),
        plate_num=body.get("plate_num"),
        url_gambar=body.get("url_gambar"),
        serial_no=str(body.get("serialNo") or body.get("serial_no") or ""),
        ipcam=body.get("ipcam"),
    )
    return _json(
        {
            "status": result.status,
            "kode_tiket": result.transaction_code,
            "police_number": result.plate,
            "typeqr": result.type_qr,
        }
    )


@router.post("/gatein/card")
async def gatein_card(request: Request) -> JSONResponse:
    """Member auto-entry: an RFID ``readCard`` tag resolved to a member.

    Called by the orchestrator over loopback. No ticket is printed — the
    member's subscription covers the stay.
    """
    body = await _body(request)
    result = await _service(request).member_gate_in(
        gate=str(body.get("gate", "1")),
        card_no=str(
            body.get("card_no") or body.get("cardNo") or body.get("card") or ""
        ),
        serial_no=str(body.get("serialNo") or body.get("serial_no") or ""),
        vehicle_id=_int(body.get("vehicle_id")),
    )
    if result.status == service.STATUS_NOT_FOUND:
        return _json(
            {"status": "member_notfound", "message": result.message},
            status_code=404,
        )
    if result.status == service.STATUS_MEMBER_EXPIRED:
        return _json(
            {
                "status": "member_expired",
                "message": result.message,
                "name": result.member_name,
            },
            status_code=403,
        )
    return _json(
        {
            "status": result.status,
            "kode_tiket": result.transaction_code,
            "member_code": result.member_code,
            "name": result.member_name,
            "police_number": result.plate,
        }
    )


# ---------------------------------------------------------------------------
# Entry — the LPR unit drives it directly (multipart image uploads)
# ---------------------------------------------------------------------------


@router.post("/lpr/gatein")
async def lpr_gatein(request: Request) -> JSONResponse:
    """The entry LPR unit opens a session from its own read.

    Port of ``GateController::GateInLpr``: the unit uploads its photo and the
    plate it read; a transaction is created and nothing else happens.
    """
    body, image = await _body_and_file(request)
    plate = body.get("plate_num")
    if image is None or not plate:
        return _json(
            {"status": "error", "message": "Missing image or plate_num"},
            status_code=400,
        )
    result = await _service(request).lpr_gate_in(plate=str(plate), image=image)
    return _json(
        {"status": result.status, "transaction_code": result.transaction_code}
    )


@router.post("/lpr/gateinimage")
async def lpr_gateinimage(request: Request) -> JSONResponse:
    """Attach the LPR photo to an open session.

    Port of ``GateController::GateinImageLpr``: the session is found by its
    ticket code or member card, then the photo and plate read are recorded.
    """
    body, image = await _body_and_file(request)
    trxcode = body.get("transaction_code")
    if image is None or not trxcode:
        return _json(
            {"status": "error", "message": "Missing image or transaction_code"},
            status_code=400,
        )
    result = await _service(request).attach_gatein_image(
        transaction_code=str(trxcode),
        plate=body.get("plate_num"),
        image=image,
    )
    if result["status"] == service.STATUS_NOT_FOUND:
        return _json(
            {"status": "error", "message": result["message"]}, status_code=404
        )
    return _json(result)


@router.post("/lpr/checkimage")
async def lpr_checkimage(request: Request) -> JSONResponse:
    """Check the entry LPR's photo is fetchable for an open session.

    Port of ``GateController::checkLprImage``. The probe is a real network
    call, so it lives here rather than in the service layer.
    """
    body = await _body(request)
    plate = body.get("plate_num")
    url_image = body.get("url_image")
    if not url_image or not plate:
        return _json(
            {"status": "error", "message": "Missing url_image or plate_num"},
            status_code=400,
        )

    srv = _service(request)
    transaction_code = await srv.find_open_plate_code(plate=str(plate))
    if transaction_code is None:
        return _json(
            {
                "status": "error",
                "message": "Active transaction not found for this plate_num",
                "plate_num": plate,
            },
            status_code=404,
        )

    try:
        probe = await asyncio.to_thread(
            httpx.get, url_image, timeout=5, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        return _json(
            {"status": "error", "message": f"Error checking image: {exc}"},
            status_code=500,
        )
    if not probe.is_success:
        return _json(
            {
                "status": "error",
                "message": "Image is not available or unreachable",
                "status_code": probe.status_code,
            },
            status_code=404,
        )
    content_type = probe.headers.get("content-type", "")
    if "image" not in content_type:
        return _json(
            {
                "status": "error",
                "message": "URL is reachable but not an image",
                "content_type": content_type,
            },
            status_code=400,
        )
    if srv.storage is not None:
        srv.storage.download_async(
            url_image, "lpr/gatein", srv.storage.lpr_filename(url_image)
        )
    return _json(
        {
            "status": "success",
            "message": "Image is available",
            "plate_num": plate,
            "transaction_code": transaction_code,
            "url_image": url_image,
        }
    )


# ---------------------------------------------------------------------------
# Exit — the automated LPR path
# ---------------------------------------------------------------------------


@router.post("/lpr/gateout")
async def lpr_gateout(request: Request) -> JSONResponse:
    """Automated exit by plate or ticket.

    **This is the fix for flow.md §7.1.** ``routes/api.php:205`` maps this path
    to ``GateoutController::GateOutLpr``, a method that was never written, so
    the live site returns::

        Method App\\Http\\Controllers\\GateoutController::GateOutLpr does not exist.

    once per exit event. Modelled on ``GateOutRfidLpr`` (:1603), which is the
    closest working template.
    """
    body = await _body(request)
    result = await _service(request).gate_out(
        gate=str(body.get("gate_out") or body.get("gate") or "2"),
        code=body.get("transaction_code") or body.get("card"),
        plate_num=body.get("plate_num"),
        url_gambar=body.get("url_gambar"),
        admin_id=_int(body.get("admin_id")),
        shift_id=_int(body.get("shift_id")),
        lost=_bool(body.get("lost_ticket")),
    )
    return _json(_gateout_payload(result))


@router.put("/lpr/gateoutcard")
async def lpr_gateoutcard(request: Request) -> JSONResponse:
    """Automated exit driven by an RFID card + plate.

    Port of ``GateoutController::GateOutRfidLpr``: the card is resolved as a
    member's entry or as a ticket code, the session is settled, and only the
    sparse status string is echoed back.
    """
    body = await _body(request)
    try:
        status = await _service(request).gate_out_rfid(
            card=str(body.get("card") or ""),
            gate=str(body.get("gate_out") or body.get("gate") or "2"),
            plate_num=body.get("plate_num"),
            url_gambar=body.get("url_gambar"),
            admin_id=_int(body.get("admin_id")),
            shift_id=_int(body.get("shift_id")),
        )
    except Exception:
        log.exception("PUT /api/lpr/gateoutcard failed")
        return _json({"status": "error"}, status_code=500)
    return _json({"status": status})


@router.post("/lpr/checkimagegateout")
async def check_image_gateout(request: Request) -> JSONResponse:
    """Look up an open session by plate, without settling it.

    Response matches ``checkLprImageGateOut``, including the nested
    ``image``/``gatein``/``gateout`` groups. Returns 404 when nothing matches —
    the same status the live site returns, though there it fires for a
    different reason (§7.7: the plate strings never agree).
    """
    body = await _body(request)
    plate_num = body.get("plate_num")
    url_image = body.get("url_image") or body.get("url_gambar")
    if not plate_num:
        return _json(
            {"status": "error", "message": "Missing plate_num"}, status_code=400
        )

    srv = _service(request)
    quote = await srv.quote_gateout_image(plate=str(plate_num))
    if quote is None:
        return _json(
            {
                "status": "error",
                "message": "Active transaction not found for this plate_num",
                "plate_num": plate_num,
            },
            status_code=404,
        )

    available = False
    message = "No url_image provided"
    if url_image:
        try:
            probe = await asyncio.to_thread(
                httpx.get, url_image, timeout=5, follow_redirects=True
            )
            if not probe.is_success:
                message = "Image is not available or unreachable"
            elif "image" not in probe.headers.get("content-type", ""):
                message = "URL is reachable but not an image"
            else:
                if srv.storage is not None:
                    srv.storage.download_async(
                        url_image,
                        "lpr/gateout",
                        srv.storage.lpr_filename(url_image, prefix="CAMOUT_LPR"),
                    )
                available = True
                message = "Image is available, download queued"
        except httpx.HTTPError as exc:
            message = f"Error checking image: {exc}"

    return _json(
        {
            "status": "success",
            "plate_num": plate_num,
            "image": {"available": available, "message": message, "url_image": url_image},
            "gatein": {
                "transaction_id": quote.transaction_id,
                "transaction_code": quote.transaction_code,
                "police_number": quote.police_number,
                "card_number": quote.card_number,
                "vehicle_id": quote.vehicle_id,
                "vehicle_name": quote.vehicle_name,
                "time_checkin": quote.time_checkin,
                "gate_in": quote.gate_in,
                "gate_status": quote.gate_status,
                "payment_status": quote.payment_status,
                "cam_in": quote.cam_in,
                "camin_lpr": quote.camin_lpr,
            },
            "gateout": {
                "gate_out": quote.gate_out,
                "cam_out": quote.cam_out,
                "camout_lpr": quote.camout_lpr,
            },
        }
    )


# ---------------------------------------------------------------------------
# Exit — the cashier path (the one that works in production)
# ---------------------------------------------------------------------------


@router.post("/gateout/detailtransaction")
async def detail_transaction(request: Request) -> JSONResponse:
    """Price a ticket for the cashier. Read-only.

    Response mirrors the captured one, including the Indonesian status strings
    and ``transaction: 'member'`` discriminator the frontend switches on.
    """
    body = await _body(request)
    result = await _service(request).quote(
        code=body.get("transaction_code"),
        plate=body.get("police_number") or body.get("plate_num"),
        vehicle_id=_int(body.get("vehicle_id")) or None,
    )
    if result.status == service.STATUS_NOT_FOUND:
        return _json(
            {"status": "notfound", "status_code": 404, "message": "transaction_notfound"},
            status_code=404,
        )

    payload: dict[str, Any] = {
        "status": "success",
        "status_code": 200,
        "transaction": "member" if result.is_member else "not_member",
        "data": {
            "member_code": result.plate_in if result.is_member else None,
            "name": result.member_name,
            "transaction_code": result.transaction_code,
            "card_number": result.card_number,
            "vehicle_id": result.vehicle_id,
            "time_checkin": result.time_checkin,
            "time_checkout": result.time_checkout,
            "duration": result.duration,
            "total": result.total,
            "cam_in": result.cam_in or "-",
            "cam_out": result.cam_out or "-",
            "payment_status": "lunas" if result.total == 0 else "belum_lunas",
            "police_number": result.plate_in,
            "breakdown": result.breakdown,
        },
    }
    # The captured member body carries message: success_member; the not-member
    # branch in Laravel omits it.
    if result.is_member:
        payload["message"] = "success_member"
    return _json(payload)


@router.put("/gateout/gateoutKasir")
async def gateout_kasir(request: Request) -> JSONResponse:
    """The cashier settles and releases the vehicle.

    In production this is the only path that works, and it never opens the
    exit barrier — nothing does (§7.6). Here it does.

    A lost ticket without a ticket number is written straight into the
    ``park_transactions`` table from the plate and vehicle class alone.
    """
    body = await _body(request)
    lost = _bool(body.get("lost_ticket"))
    code = body.get("transaction_code")

    if lost and not code:
        result = await _service(request).lost_ticket(
            gate=str(body.get("gate_out") or "2"),
            plate=body.get("police_number") or body.get("plate_num"),
            vehicle_id=_int(body.get("vehicle_id")) or None,
            admin_id=_int(body.get("admin_id")),
            shift_id=_int(body.get("shift_id")),
        )
        if result.status == service.STATUS_NOT_FOUND:
            return _json({"status": "error", "message": result.message}, status_code=400)
        return _json(
            {
                "status": "success",
                "status_code": 200,
                "data": _kasir_payload(result),
            }
        )

    result = await _service(request).gate_out(
        gate=str(body.get("gate_out") or "2"),
        code=code,
        plate_num=body.get("police_number") or body.get("plate_num"),
        admin_id=_int(body.get("admin_id")),
        shift_id=_int(body.get("shift_id")),
        lost=lost,
        vehicle_id=_int(body.get("vehicle_id")) or None,
    )
    if result.status == service.STATUS_TICKET_USED:
        return _json({"status": "already_paid", "message": result.message})
    if result.status == service.STATUS_NOT_FOUND:
        return _json(
            {"status": "notfound", "status_code": 404, "message": result.message},
            status_code=404,
        )
    return _json(
        {
            "status": "success",
            "status_code": 200,
            "data": _kasir_payload(result),
        }
    )


# ---------------------------------------------------------------------------
# Lookups the cashier frontend reads (no HTML pages — API only)
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    return _json({"status": "ok", "env": get_settings().app_env})


@router.get("/members")
async def list_members(request: Request) -> JSONResponse:
    """Every member, for the desk's member directory screen."""
    srv = _service(request)
    async with srv.session_factory() as session:
        members = (
            (await session.execute(select(Member).order_by(Member.name))).scalars().all()
        )
        vehicles = (
            (
                await session.execute(
                    select(MemberVehicle).options(selectinload(MemberVehicle.vehicle_type))
                )
            )
            .scalars()
            .all()
        )
        first_vehicle = {vehicle.member_id: vehicle for vehicle in vehicles}
        rows = []
        for member in members:
            ctx = await _member_context(session, member, first_vehicle.get(member.id))
            rows.append(
                {
                    "member_id": str(member.id),
                    "name": ctx.name,
                    "phone": member.phone_number,
                    "email": member.email,
                    "police_number": ctx.police_number,
                    "member_code": ctx.member_code,
                    "card_number": ctx.card_number,
                    "vehicle_id": ctx.vehicle_id,
                    "time_limit": (
                        ctx.time_limit.isoformat() if ctx.time_limit else None
                    ),
                }
            )
    return _json({"status": "success", "data": rows})


@router.get("/transactions")
async def list_transactions(request: Request) -> JSONResponse:
    """Every parking transaction, newest first, for the history screen."""
    srv = _service(request)
    async with srv.session_factory() as session:
        transactions = await list_recent(session)
        gate_codes = await service._gate_codes(session)
        rows = []
        for tx in transactions:
            rows.append(
                {
                    "transaction_code": tx.ticket_number,
                    "police_number": tx.police_number,
                    "vehicle_id": await vehicle_id_of(session, tx.vehicle_type_id),
                    "card_number": tx.card_number,
                    "time_checkin": service.format_wib(tx.entry_time),
                    "time_checkout": service.format_wib(tx.exit_time),
                    "duration": tx.duration,
                    "total": tx.total_fee,
                    "payment_status": tx.payment_status,
                    "gate_in": gate_codes.get(tx.entry_gate_id),
                    "gate_out": gate_codes.get(tx.exit_gate_id),
                }
            )
    return _json({"status": "success", "data": rows})


@router.post("/transactions")
async def add_manual_transaction(request: Request) -> JSONResponse:
    """Record a transaction by hand — the ticket never printed.

    The code is generated server-side; plate and vehicle class come from the
    cashier; check-in, check-out and duration are filled in automatically and
    the flat rate for the class is charged and marked lunas immediately.
    """
    body = await _body(request)
    result = await _service(request).manual_ticket(
        police_number=str(body.get("police_number") or ""),
        vehicle_id=_int(body.get("vehicle_id")),
        admin_id=_int(body.get("admin_id")),
        shift_id=_int(body.get("shift_id")),
        gate=str(body.get("gate") or body.get("gate_in") or "1"),
        total=_int(body.get("total")) or None,
    )
    if result.status == service.STATUS_NOT_FOUND:
        return _json({"status": "error", "message": result.message}, status_code=400)
    return _json(
        {
            "status": "success",
            "status_code": 200,
            "data": _kasir_payload(result),
        }
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _gateout_payload(result: service.GateOutResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "transaction_code": result.transaction_code,
        "total": result.total,
        "duration": result.duration,
        "police_number": result.plate_in,
        "plate_out": result.plate_out,
        "plate_match": result.plate_match,
        "time_checkin": result.time_checkin,
        "time_checkout": result.time_checkout,
        "cam_in": result.cam_in,
        "cam_out": result.cam_out,
        "member": result.is_member,
        "name": result.member_name,
        "breakdown": result.breakdown,
        "message": result.message,
    }


def _kasir_payload(result: service.GateOutResult) -> dict[str, Any]:
    """``responData()`` — the body ``gateoutKasir`` returns on success."""
    return {
        "transaction_code": result.transaction_code,
        "vehicle_id": result.vehicle_id,
        "time_checkin": result.time_checkin,
        "time_checkout": result.time_checkout,
        "duration": result.duration,
        "total": result.total,
        "cam_in": result.cam_in,
        "cam_out": result.cam_out,
        "payment_status": result.payment_status,
        "police_number": result.plate_in,
        "admin_id": result.admin_id,
        "shift_id": result.shift_id,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
        "discount": "false",
    }


async def _body(request: Request) -> dict[str, Any]:
    """Accept JSON, form-urlencoded, or multipart.

    The cashier app sends multipart for ``detailtransaction`` and
    form-urlencoded for ``gateoutKasir`` (flow.md §6), while the LPR units send
    JSON, so all three have to work.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    if "form-data" in content_type or "x-www-form-urlencoded" in content_type:
        form = await request.form()
        return {key: form[key] for key in form}

    # Fall back to the query string, which is how checkimagegateout is called.
    return dict(request.query_params)


async def _body_and_file(request: Request) -> tuple[dict[str, Any], bytes | None]:
    """The parsed body and the ``image`` upload (multipart), else None.

    The LPR entry endpoints (``lpr/gatein``, ``lpr/gateinimage``) receive the
    photo as an ``image`` file in a multipart request. JSON bodies carry no
    file.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await _body(request), None

    form = await request.form()
    payload = {key: form[key] for key in form if key != "image"}
    image = form.get("image")
    if image is None or not hasattr(image, "read"):
        return payload, None
    return payload, await image.read()


def _int(value: Any) -> int | None:
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")
