"""Real-time gate events for the POS, relayed over Redis pub/sub.

The orchestrator and the gate cycle publish barrier / settle facts onto a
single Redis channel; ``GET /api/pos/events/stream`` subscribes and streams
them as Server-Sent Events to the cashier. ``gate_events`` remains the durable
record, and the SSE endpoint re-reads it when Redis is down, so a message lost
between publish and subscribe is not fatal.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis.exceptions

from api_trafix.config.redis import get_redis

log = logging.getLogger(__name__)

GATE_EVENTS_CHANNEL = "gate:events"

# Event ``type`` values.
TYPE_BARRIER_COMMAND = "barrier_command"
TYPE_BARRIER_OPENED = "barrier_opened"
TYPE_TRANSACTION_SETTLED = "transaction_settled"
TYPE_TRANSACTION_VOIDED = "transaction_voided"


async def publish_gate_event(
    type: str,
    *,
    gate: str | None = None,
    transaction_code: str | None = None,
    **extra: Any,
) -> None:
    """Publish one event onto ``GATE_EVENTS_CHANNEL``.

    Never raises: the real-time stream is best-effort on top of the durable
    ``gate_events`` table, so a Redis outage must not take the gate cycle down.
    """
    event: dict[str, Any] = {
        "type": type,
        "ts": datetime.now(UTC).isoformat(),
    }
    if gate is not None:
        event["gate"] = gate
    if transaction_code is not None:
        event["transaction_code"] = transaction_code
    event.update(extra)
    try:
        r = await get_redis()
        await r.publish(GATE_EVENTS_CHANNEL, json.dumps(event, default=str))
    except (redis.exceptions.RedisError, OSError) as exc:
        log.warning("could not publish gate event %s: %s", type, exc)
