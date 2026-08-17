"""System-level monitoring endpoints — the API equivalent of the
Parkways Monitoring desktop dashboard's top-level health panel.

No authentication required (per design decision: monitoring is open).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/system", tags=["System"])


@router.get("/health")
async def system_health(request: Request):
    """Overall system health including MQTT, TCP gate counts, uptime."""
    status = request.app.state.system_status
    health = status.get_system_health()
    gate_health = getattr(request.app.state, "gate_health", None)
    if gate_health is not None:
        gates = gate_health.get_all()
        health["gates_online"] = sum(1 for g in gates if g["is_online"])
        health["gates_offline"] = sum(1 for g in gates if not g["is_online"])
        health["gates_total"] = len(gates)
    return health


@router.get("/mqtt/status")
async def mqtt_status(request: Request):
    """MQTT broker connection state, uptime, reconnect count."""
    return request.app.state.system_status.get_mqtt_status()


@router.get("/tcp/status")
async def tcp_status(request: Request):
    """TCP gateway connection counts."""
    tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
    if tcp_gateway is None:
        return {"enabled": False, "connected_gates": 0, "total_gates": 0}
    return {
        "enabled": True,
        "connected_gates": tcp_gateway.get_connected_count(),
        "total_gates": tcp_gateway.get_total_count(),
        "connections": tcp_gateway.get_health_all(),
    }
