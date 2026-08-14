"""The MQTT orchestrator — the component missing from the production repo.

flow.md §2 and open question 1: something on the server subscribes to
``/GATE/event/1``, reacts to the sensor inputs, calls the LPR, asks the API for
a ticket, and publishes the barrier command. This module is that component,
port of ``trafix-api-mock/trafix/orchestrator.py``, running as an asyncio task
inside the API process (when ``MQTT_ENABLED``) instead of a separate binary.

Entry, per the capture::

    1. controller  inputInfo input3=1            vehicle on the arrival loop
    2. server      /GATE/IN/1/status "welcome"
    3. controller  inputInfo input2=1            ticket button pressed
    4. server      GET .130:8090/checklpr        read the plate
    5. server      POST /api/gatein              ticket issued, printed
    6. server      /GATE/IN/1/status "thanks"
    7. server      outputCtrl relay1             BARRIER OPENS
    8. controller  inputInfo input4=1            vehicle clears the lane

Exit is not in the capture, because on site the automated path is dead. Here
the exit LPR's ``gate/out/{gate}/pos`` announcement drives it.

The API calls go over loopback HTTP to ``settings.api_base_url`` — which is why
they never show up in a capture of the external interface (flow.md §3).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from api_trafix.config.settings import Settings
from api_trafix.services.device_registry import DeviceRegistry, RegistryError
from api_trafix.services.protocol import (
    INPUT_ARRIVAL_LOOP,
    INPUT_PASS_LOOP,
    INPUT_TICKET_BUTTON,
    METHOD_INPUT_INFO,
    METHOD_OUTPUT_CTRL,
    METHOD_READ_CARD,
    METHOD_TX_UART_DATA,
    STATUS_THANKS,
    STATUS_WELCOME,
    Envelope,
    gate_event_topic,
    gate_in_topic,
    gate_out_pos_topic,
    gate_out_topic,
    gate_status_topic,
    open_barrier,
    signage,
)

logger = logging.getLogger(__name__)

# The plate the LPR reports when it saw nothing. 4 of 6 tickets on site.
NO_PLATE = ""

# Sent by ``_request_member_entry`` when the card belongs to a registered member
# whose entry was refused (expired subscription or vehicle-class mismatch) —
# distinct from None, which means the card is unknown.
MEMBER_REFUSED = object()


@dataclass
class LaneState:
    """What the orchestrator remembers about one lane."""

    occupied: bool = False
    last_ticket_at: float = 0.0
    last_ticket_code: str | None = None
    tickets_issued: int = 0


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        bus: Any,
        registry: DeviceRegistry,
        vehicle_id: int = 1,
        rfid_only: bool = False,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.registry = registry
        # The gate hardware cannot tell a car from a motorcycle. On a
        # single-class site this is fixed; a mixed site needs either a
        # per-lane setting or an operator button.
        self.vehicle_id = vehicle_id
        # On-site live testing mode: react to nothing but readCard so we never
        # issue a second ticket for a real car or the ticket button.
        self.rfid_only = rfid_only

        self.http = httpx.AsyncClient(timeout=settings.lpr_timeout_seconds)
        self.lanes: dict[str, LaneState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        for gate in self.registry.controllers():
            self.lanes[gate] = LaneState()
            self._locks[gate] = asyncio.Lock()
            self.bus.subscribe(
                gate_event_topic(gate), self._make_event_handler(gate)
            )
            logger.info("watching gate %s on %s", gate, gate_event_topic(gate))

        # The exit LPR announces reads instead of being polled.
        for gate, lpr in self.registry.lpr_items().items():
            if gate in self.registry.entry_gate_codes():
                continue
            self.bus.subscribe_raw(
                gate_out_pos_topic(lpr.pos_topic_gate), self._make_exit_handler(gate)
            )
            logger.info(
                "watching exit reads on %s (logical gate %s)",
                gate_out_pos_topic(lpr.pos_topic_gate),
                gate,
            )

        await self.bus.start()
        await self._check_dependencies()

    async def stop(self) -> None:
        await self.bus.stop()
        await self.http.aclose()

    async def _check_dependencies(self) -> None:
        try:
            response = await self.http.get(f"{self.settings.api_base_url}/api/health")
            logger.info("API reachable: %s", response.json())
        except httpx.HTTPError as exc:
            logger.error(
                "API NOT reachable at %s: %s", self.settings.api_base_url, exc
            )

        for gate, lpr in self.registry.lpr_items().items():
            if not lpr.serves_http:
                logger.warning(
                    "LPR %s serves no HTTP (as on site, §7.2) — gate %s relies on "
                    "its MQTT announcements",
                    lpr.name,
                    gate,
                )
                continue
            try:
                response = await self.http.get(f"{lpr.base_url}/checklpr", timeout=2)
                response.raise_for_status()
                logger.info("LPR %s reachable at %s", lpr.name, lpr.base_url)
            except httpx.HTTPError as exc:
                logger.error(
                    "LPR %s NOT reachable at %s: %s", lpr.name, lpr.base_url, exc
                )

    # -- entry lane --------------------------------------------------------

    def _make_event_handler(self, gate: str):
        async def handler(_topic: str, message: Envelope) -> None:
            if self.rfid_only and message.method != METHOD_READ_CARD:
                logger.debug(
                    "gate %s: rfid-only, ignoring %s", gate, message.method
                )
                return
            if message.method == METHOD_INPUT_INFO:
                async with self._locks[gate]:
                    await self._on_inputs(gate, message)
            elif message.method == METHOD_READ_CARD:
                async with self._locks[gate]:
                    await self._on_card(gate, message)
            elif message.method in (METHOD_TX_UART_DATA, METHOD_OUTPUT_CTRL):
                logger.debug("gate %s: controller acked %s", gate, message.method)
            else:
                logger.debug("gate %s: %s", gate, message.method)

        return handler

    async def _on_inputs(self, gate: str, message: Envelope) -> None:
        lane = self.lanes[gate]
        arrival = _as_int(message.get(INPUT_ARRIVAL_LOOP))
        button = _as_int(message.get(INPUT_TICKET_BUTTON))
        passed = _as_int(message.get(INPUT_PASS_LOOP))

        if arrival and not lane.occupied:
            lane.occupied = True
            logger.info("gate %s: vehicle arrived", gate)
            self.bus.publish_raw(gate_status_topic(gate), signage(STATUS_WELCOME))

        if button:
            await self._handle_button(gate, message)

        if passed:
            if lane.occupied:
                logger.info("gate %s: vehicle cleared the lane", gate)
            lane.occupied = False

    async def _handle_button(self, gate: str, message: Envelope) -> None:
        lane = self.lanes[gate]
        now = time.monotonic()

        # Drivers press twice when the printer is slow. A second ticket for one
        # car leaves an orphan record that can never be checked out.
        window = self.settings.button_debounce_seconds
        if lane.last_ticket_code and (now - lane.last_ticket_at) < window:
            logger.info(
                "gate %s: repeat press within %.0fs, ignoring (ticket %s stands)",
                gate,
                window,
                lane.last_ticket_code,
            )
            return

        logger.info("gate %s: TICKET BUTTON — reading plate", gate)
        plate, image_url = await self._read_plate(gate)

        ticket = await self._request_ticket(
            gate=gate,
            plate=plate,
            image_url=image_url,
            serial_no=message.serial_no,
        )
        if ticket is None:
            # The API failed. Do not open: without a ticket the driver has no
            # way to check out, and an unrecorded car is worse than a delay.
            logger.error("gate %s: no ticket issued, barrier stays shut", gate)
            self.bus.publish_raw(gate_status_topic(gate), signage(STATUS_THANKS))
            return

        lane.last_ticket_code = ticket
        lane.last_ticket_at = now
        lane.tickets_issued += 1

        self.bus.publish_raw(gate_status_topic(gate), signage(STATUS_THANKS))
        self._open(gate)

    async def _on_card(self, gate: str, message: Envelope) -> None:
        """An RFID tag was presented. Resolve it to a member and open the gate.

        A member entry creates no paper ticket, so there is no orphan risk from
        repeat taps, but a debounce still stops a double-tap opening twice.
        """
        card_no = str(message.get("cardNo") or "").strip()
        if not card_no:
            logger.warning("gate %s: readCard with no cardNo", gate)
            return

        lane = self.lanes[gate]
        now = time.monotonic()
        window = self.settings.button_debounce_seconds
        if lane.last_ticket_code and (now - lane.last_ticket_at) < window:
            logger.info(
                "gate %s: repeat card tap within %.0fs, ignoring",
                gate,
                window,
            )
            return

        member = await self._request_member_entry(gate, card_no, message.serial_no)
        if member is None:
            if self.settings.card_fallback_to_ticket:
                logger.warning(
                    "gate %s: card %s not registered — falling back to a "
                    "paper ticket so the driver is not stranded",
                    gate,
                    card_no,
                )
                await self._handle_button(gate, message)
            else:
                logger.warning(
                    "gate %s: member entry refused for card %s", gate, card_no
                )
            return

        if member is MEMBER_REFUSED:
            # A registered member whose subscription is expired or whose
            # vehicle class mismatches must never get a paper ticket — they are
            # a known member, not a walk-up driver. Let them in and tell the
            # operator why; staff resolves the subscription.
            lane.last_ticket_code = card_no
            lane.last_ticket_at = now
            logger.warning(
                "gate %s: card %s is a registered member but refused — "
                "opening the barrier with no ticket",
                gate,
                card_no,
            )
            self.bus.publish_raw(gate_status_topic(gate), signage(STATUS_THANKS))
            self._open(gate)
            return

        lane.last_ticket_code = member.get("kode_tiket")
        lane.last_ticket_at = now
        lane.tickets_issued += 1

        logger.info(
            "gate %s: member %s entered on card %s (ticket %s)",
            gate,
            member.get("name"),
            card_no,
            member.get("kode_tiket"),
        )
        self.bus.publish_raw(gate_status_topic(gate), signage(STATUS_THANKS))
        self._open(gate)

    async def _request_member_entry(
        self, gate: str, card_no: str, serial_no: str
    ) -> dict | None:
        """POST /api/gatein/card.

        Returns the member payload dict when the card is accepted, the
        ``MEMBER_REFUSED`` sentinel when the card belongs to a registered
        member whose entry was refused (expired subscription or vehicle-class
        mismatch), and None when the card is unknown or the API failed.
        """
        try:
            response = await self.http.post(
                f"{self.settings.api_base_url}/api/gatein/card",
                json={
                    "gate": gate,
                    "card_no": card_no,
                    "serialNo": serial_no,
                    "vehicle_id": self.vehicle_id,
                },
                timeout=10,
            )
            if response.status_code == 404:
                logger.info("gate %s: card %s not a member", gate, card_no)
                return None
            if response.status_code == 403:
                logger.warning(
                    "gate %s: card %s is a registered member but refused: %s",
                    gate,
                    card_no,
                    response.json().get("message"),
                )
                return MEMBER_REFUSED
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("gate %s: /api/gatein/card failed: %s", gate, exc)
            return None

        if not payload.get("kode_tiket"):
            logger.error(
                "gate %s: /api/gatein/card returned no ticket: %s", gate, payload
            )
            return None

        logger.info("gate %s: member entry accepted for card %s", gate, card_no)
        return payload

    async def _read_plate(self, gate: str) -> tuple[str, str]:
        """Ask the entry LPR what it can see.

        A failure here is never fatal: on site 4 of 6 tickets recorded no plate
        at all and the gate still worked. The ticket code is what gets the
        driver out, not the plate.
        """
        try:
            lpr = self.registry.lpr_for(gate)
        except RegistryError:
            logger.warning("gate %s has no LPR configured", gate)
            return NO_PLATE, ""

        if not lpr.serves_http:
            logger.warning(
                "gate %s: LPR serves no HTTP, issuing a ticket with no plate", gate
            )
            return NO_PLATE, ""

        attempts = max(1, self.settings.lpr_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                response = await self.http.get(f"{lpr.base_url}/checklpr")
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "gate %s: checklpr attempt %s/%s failed: %s",
                    gate,
                    attempt,
                    attempts,
                    exc,
                )
                continue

            plate = str(data.get("plate_num") or "").strip()
            image_url = str(data.get("url_gambar") or "").strip()
            if plate:
                logger.info("gate %s: plate %s", gate, plate)
            else:
                logger.warning("gate %s: LPR read no plate", gate)
            return plate, image_url

        logger.error(
            "gate %s: LPR unreachable, issuing a ticket with no plate", gate
        )
        return NO_PLATE, ""

    async def _request_ticket(
        self, *, gate: str, plate: str, image_url: str, serial_no: str
    ) -> str | None:
        """POST /api/gatein."""
        try:
            response = await self.http.post(
                f"{self.settings.api_base_url}/api/gatein",
                json={
                    "gate": gate,
                    "vehicle_id": self.vehicle_id,
                    "plate_num": plate,
                    "url_gambar": image_url,
                    "serialNo": serial_no,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("gate %s: /api/gatein failed: %s", gate, exc)
            return None

        code = payload.get("kode_tiket")
        if not code:
            logger.error("gate %s: /api/gatein returned no ticket: %s", gate, payload)
            return None

        logger.info("gate %s: ticket %s issued", gate, code)
        return str(code)

    # -- exit lane ---------------------------------------------------------

    def _make_exit_handler(self, gate: str):
        async def handler(_topic: str, payload: str) -> None:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning(
                    "gate %s: undecodable exit announcement: %r", gate, payload
                )
                return

            plate = str(data.get("plate_num") or "").strip()
            image_url = str(data.get("url_gambar") or "").strip()

            if not plate:
                logger.warning(
                    "gate %s: exit LPR read no plate, cannot resolve a ticket", gate
                )
                return

            logger.info("gate %s: exit read %s", gate, plate)
            await self._settle_by_plate(gate, plate, image_url)

        return handler

    async def _settle_by_plate(self, gate: str, plate: str, image_url: str) -> None:
        """Automated exit through the production ``gateoutcard`` contract.

        On site the exit gate controller itself calls ``PUT /api/lpr/gateoutcard``
        (``GateoutController::GateOutRfidLpr`` :1603) with the scanned RFID/ticket;
        the backend answers ``success_member``/``success_ticket`` and the device
        firmware raises the barrier. The simulator has no device, so the
        orchestrator plays it: it quotes the fee first (only free sessions are
        released — a chargeable ticket is left for the cashier), settles through
        the real endpoint, then raises the exit barrier on success.
        """
        quote = await self._quote_exit(gate, plate)
        if quote is None:
            return
        code, total = quote

        if total > 0:
            logger.info(
                "gate %s: %s owes %s — waiting for the cashier",
                gate,
                plate,
                total,
            )
            return

        try:
            response = await self.http.put(
                f"{self.settings.api_base_url}/api/lpr/gateoutcard",
                json={
                    "card": code,
                    "plate_num": plate,
                    "url_gambar": image_url,
                    "gate_out": gate,
                },
                timeout=10,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error(
                "gate %s: /api/lpr/gateoutcard failed: %s", gate, exc
            )
            return

        status = payload.get("status")
        if status in ("success_member", "success_ticket"):
            logger.info(
                "gate %s: %s released (%s), raising the barrier",
                gate,
                plate,
                status,
            )
            # The device firmware opens on success_*; stand in for it here.
            self._open(gate, exit_lane=True)
            return

        logger.warning(
            "gate %s: automated exit refused for %s: %s", gate, plate, status
        )

    async def _quote_exit(self, gate: str, plate: str) -> tuple[str, float] | None:
        """The cashier's own quote for the plate: (transaction code, fee)."""
        try:
            response = await self.http.post(
                f"{self.settings.api_base_url}/api/gateout/detailtransaction",
                json={"transaction_code": "", "police_number": plate},
                timeout=10,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("gate %s: exit quote failed: %s", gate, exc)
            return None

        if payload.get("status") != "success":
            logger.warning(
                "gate %s: no open transaction for %s (%s)",
                gate,
                plate,
                payload.get("status"),
            )
            return None

        data = payload.get("data") or {}
        code = data.get("transaction_code")
        if not code:
            logger.warning("gate %s: quote carried no transaction code", gate)
            return None
        return str(code), float(data.get("total") or 0)

    # -- barrier -----------------------------------------------------------

    def _open(self, gate: str, *, exit_lane: bool = False) -> None:
        try:
            controller = self.registry.controller_for(gate)
        except RegistryError:
            logger.warning(
                "gate %s: no controller configured, barrier stays shut", gate
            )
            return
        topic = gate_out_topic(gate) if exit_lane else gate_in_topic(gate)
        self.bus.publish(
            topic,
            open_barrier(
                controller.serial_no,
                pulse_ms=self.settings.barrier_pulse_ms,
                beep_ms=self.settings.barrier_beep_ms,
            ),
        )
        logger.info("gate %s: barrier command sent (%s)", gate, topic)


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
