"""Gate control and health monitoring endpoints — replaces the per-gate
status panel from the Parkways Monitoring desktop app.

No authentication required (per design decision: monitoring is open).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api_trafix.config.settings import get_settings

router = APIRouter(prefix="/api/gates", tags=["Gate Control"])


def _settings(request: Request):
    return getattr(request.app.state, "settings", None) or get_settings()


@router.get("/status")
async def gates_status(request: Request):
    """All gates: online/offline, last heartbeat, sensor states."""
    gate_health = request.app.state.gate_health
    return gate_health.get_all()


@router.get("/{gate_code}/status")
async def gate_status(gate_code: str, request: Request):
    """Single gate health detail."""
    gate_health = request.app.state.gate_health
    entry = gate_health.get_one(gate_code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Gerbang {gate_code} tidak ditemukan")
    return entry


@router.get("/{gate_code}/sensors")
async def gate_sensors(gate_code: str, request: Request):
    """Current input/sensor states for a gate."""
    gate_health = request.app.state.gate_health
    entry = gate_health.get_one(gate_code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Gerbang {gate_code} tidak ditemukan")
    return {
        "gate_code": gate_code,
        "sensors": entry["sensor_states"],
    }


@router.post("/{gate_code}/barrier/open")
async def open_barrier(gate_code: str, request: Request):
    """Manually open a gate barrier.

    Sends the open_barrier command via MQTT and TCP (if connected).
    """
    from api_trafix.services.device_registry import RegistryError
    from api_trafix.services.protocol import gate_in_topic, open_barrier as make_open

    registry = request.app.state.device_registry
    bus = request.app.state.bus
    settings = _settings(request)

    try:
        controller = registry.controller_for(gate_code)
    except RegistryError:
        raise HTTPException(
            status_code=404, detail=f"Tidak ada kontroller yang dikonfigurasi untuk gerbang {gate_code}"
        )

    # MQTT command
    topic = gate_in_topic(gate_code)
    bus.publish(
        topic,
        make_open(
            controller.serial_no,
            pulse_ms=settings.barrier_pulse_ms,
            beep_ms=settings.barrier_beep_ms,
        ),
    )

    # TCP command if gateway is connected
    tcp_sent = False
    tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
    if tcp_gateway is not None and controller.connection_type in ("tcp", "both"):
        tcp_sent = await tcp_gateway.send_output_ctrl(
            gate_code,
            output_id="relay1",
            pulse_ms=settings.barrier_pulse_ms,
        )

    return {
        "status": "command_sent",
        "gate": gate_code,
        "mqtt_topic": topic,
        "tcp_sent": tcp_sent,
    }


@router.post("/{gate_code}/relay/{output_id}/pulse")
async def pulse_relay(gate_code: str, output_id: str, request: Request):
    """Generic relay pulse command for a gate.

    Triggers a specific output relay for the configured pulse duration.
    """
    from api_trafix.services.device_registry import RegistryError
    from api_trafix.services.protocol import gate_in_topic, open_barrier as make_open

    registry = request.app.state.device_registry
    bus = request.app.state.bus
    settings = _settings(request)

    try:
        controller = registry.controller_for(gate_code)
    except RegistryError:
        raise HTTPException(
            status_code=404, detail=f"Tidak ada kontroller yang dikonfigurasi untuk gerbang {gate_code}"
        )

    # MQTT command
    topic = gate_in_topic(gate_code)
    bus.publish(
        topic,
        make_open(
            controller.serial_no,
            relay=output_id,
            pulse_ms=settings.barrier_pulse_ms,
            beep_ms=0,
        ),
    )

    # TCP command if gateway is connected
    tcp_sent = False
    tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
    if tcp_gateway is not None and controller.connection_type in ("tcp", "both"):
        tcp_sent = await tcp_gateway.send_output_ctrl(
            gate_code,
            output_id=output_id,
            pulse_ms=settings.barrier_pulse_ms,
        )

    return {
        "status": "command_sent",
        "gate": gate_code,
        "output_id": output_id,
        "mqtt_topic": topic,
        "tcp_sent": tcp_sent,
    }
