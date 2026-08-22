"""Cleanup semantics of the unified SSE event-stream iterator.

The dedicated pubsub connection must be released back to the pool when a
client disconnects — ``unsubscribe()`` alone leaks one pool slot per client
until ``MaxConnectionsError`` breaks every Redis command (routes/events.py).
"""

import asyncio
import json

from api_trafix.routes.events import _unified_events_iter


class FakePubSub:
    """Stand-in for ``redis.asyncio.Redis.pubsub()``."""

    def __init__(self, messages):
        self._queue = list(messages)
        self.unsubscribed = False
        self.closed = False

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        if self._queue:
            return {"data": json.dumps(self._queue.pop(0))}
        await asyncio.Event().wait()

    async def unsubscribe(self, *channels):
        self.unsubscribed = True

    async def aclose(self):
        self.closed = True


async def test_unified_iter_releases_pubsub_on_disconnect():
    pubsub = FakePubSub([])

    async def snapshot():
        return
        yield  # pragma: no cover - empty generator

    frames = [
        frame
        async for frame in _unified_events_iter(
            gate=None,
            snapshot=snapshot(),
            pubsub=pubsub,
            disconnect=lambda: True,
        )
    ]
    assert frames == []
    assert pubsub.unsubscribed
    assert pubsub.closed


async def test_unified_iter_replays_snapshot_filters_by_gate_and_closes():
    pubsub = FakePubSub(
        [
            {"type": "transaction_settled", "gate": "1"},
            {"type": "transaction_settled", "gate": "2"},
        ]
    )

    async def snapshot():
        yield {"type": "snapshot", "gate": "1"}

    stream = _unified_events_iter(
        gate="1",
        snapshot=snapshot(),
        pubsub=pubsub,
        disconnect=lambda: False,
    )
    snapshot_frame = await anext(stream)
    event_frame = await anext(stream)
    await stream.aclose()

    assert "event: snapshot" in snapshot_frame
    assert "event: transaction_settled" in event_frame
    assert '"gate": "1"' in event_frame
    # The gate-2 event must be filtered out, never surfaced.
    assert '"gate": "2"' not in event_frame
    assert pubsub.unsubscribed
    assert pubsub.closed


async def test_unified_iter_survives_missing_pubsub():
    """A Redis outage degrades the stream to keepalives instead of dying."""

    async def snapshot():
        return
        yield  # pragma: no cover - empty generator

    stream = _unified_events_iter(
        gate=None,
        snapshot=snapshot(),
        pubsub=None,
        disconnect=lambda: False,
    )
    frame = await asyncio.wait_for(anext(stream), timeout=5)
    assert frame == ": keepalive\n\n"
    await stream.aclose()
