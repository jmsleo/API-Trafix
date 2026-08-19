"""System-level monitoring endpoints — the API equivalent of the
Parkways Monitoring desktop dashboard's top-level health panel.

No authentication required (per design decision: monitoring is open).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.crud import system_config as config_crud
from api_trafix.models import User

router = APIRouter(prefix="/api/system", tags=["System"])

_MQTT_SECTION = "mqtt"


class MqttConfig(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=1883, ge=1, le=65535)
    keepalive: int = Field(default=60, ge=1)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    client_id_prefix: str = Field(default="api-trafix", max_length=100)


def _effective_mqtt(db_values: dict[str, dict], settings) -> dict:
    """Merge DB overrides on top of environment defaults."""
    out = {
        "host": settings.mqtt_host,
        "port": settings.mqtt_port,
        "keepalive": settings.mqtt_keepalive,
        "username": settings.mqtt_username or None,
        "password": settings.mqtt_password or None,
        "client_id_prefix": settings.mqtt_client_id_prefix,
    }
    for key, value in db_values.items():
        if key in out:
            out[key] = value.get("value", out[key])
    return out


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


@router.get("/mqtt/config", response_model=MqttConfig)
async def mqtt_config_get(
    db: AsyncSession = Depends(get_db),
):
    """Effective MQTT broker configuration (DB override, else env default).

    Readable without auth so the Teknisi dashboard can render the broker form.
    """
    db_values = await config_crud.get_section(db, _MQTT_SECTION)
    return _effective_mqtt(db_values, get_settings())


@router.put("/mqtt/config", response_model=MqttConfig)
async def mqtt_config_put(
    payload: MqttConfig,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    """Persist MQTT broker configuration. Changes apply on the next restart."""
    for key in ("host", "port", "keepalive", "username", "password", "client_id_prefix"):
        value = getattr(payload, key)
        await config_crud.upsert(db, _MQTT_SECTION, key, {"value": value})
    db_values = await config_crud.get_section(db, _MQTT_SECTION)
    return _effective_mqtt(db_values, get_settings())
