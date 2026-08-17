"""TCP wire protocol for gate controllers — Python port of the Parkways
Rust TCP layer (``src/infrastructure/tcp/tcp_protocol.rs``).

Frame format (per reverse-engineering analysis):
- Length-delimited: ``[LENGTH 2 bytes big-endian] [PAYLOAD]``
- Payloads are JSON-encoded command/response envelopes

Reference: length_delimited_codec = LengthDelimitedCodec::new(512, LENGTH, 0, 4096)
"""

from __future__ import annotations

import json
import logging
import struct
from typing import Any

logger = logging.getLogger(__name__)

# -- Frame constants -------------------------------------------------------

MAX_FRAME_PAYLOAD = 4096
LENGTH_FIELD_BYTES = 2
LENGTH_BYTE_ORDER = "big"  # big-endian, confirmed by analysis


# -- Frame encode/decode ---------------------------------------------------


def encode_frame(payload: bytes) -> bytes:
    """Prepend 2-byte big-endian length header to payload."""
    length = len(payload)
    if length > MAX_FRAME_PAYLOAD:
        raise ValueError(f"payload too large: {length} > {MAX_FRAME_PAYLOAD}")
    return struct.pack(LENGTH_BYTE_ORDER + "H", length) + payload


def decode_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Extract complete frames from a byte buffer.

    Returns (frames, remainder) where remainder is the incomplete tail.
    """
    frames: list[bytes] = []
    while len(buffer) >= LENGTH_FIELD_BYTES:
        length = struct.unpack(LENGTH_BYTE_ORDER + "H", buffer[:LENGTH_FIELD_BYTES])[0]
        if length > MAX_FRAME_PAYLOAD:
            logger.warning("invalid frame length %d, discarding buffer", length)
            return [], b""
        total = LENGTH_FIELD_BYTES + length
        if len(buffer) < total:
            break
        frames.append(buffer[LENGTH_FIELD_BYTES:total])
        buffer = buffer[total:]
    return frames, buffer


# -- Command builders (JSON payloads) --------------------------------------


def build_trig(*, output_id: str | None = None) -> bytes:
    """TRIG command — triggers a gate input.

    With output_id: ``{"cmd":"trig","output":"<output_id>"}``
    Without:        ``{"cmd":"trig"}``
    """
    cmd: dict[str, Any] = {"cmd": "trig"}
    if output_id:
        cmd["output"] = output_id
    return encode_frame(json.dumps(cmd, separators=(",", ":")).encode())


def build_output_ctrl(*, output_id: str, pulse_ms: int = 1000) -> bytes:
    """OUTPUT_CTRL command — actuate a relay.

    ``{"cmd":"outputCtrl","output":"<output_id>","pulse":<pulse_ms>}``
    """
    cmd = {
        "cmd": "outputCtrl",
        "output": output_id,
        "pulse": pulse_ms,
    }
    return encode_frame(json.dumps(cmd, separators=(",", ":")).encode())


def build_heartbeat() -> bytes:
    """HEARTBEAT command — controller status poll.

    ``{"cmd":"heartbeat"}``
    """
    return encode_frame(json.dumps({"cmd": "heartbeat"}, separators=(",", ":")).encode())


def build_gate_in(*, gate_id: str, serial_no: str = "", ts: int | None = None) -> bytes:
    """GATE_IN command — announce entry event.

    ``{"cmd":"gateIn","gateId":"<gate_id>","serialNo":"<serial>","ts":<unix_ts>}``
    """
    cmd: dict[str, Any] = {"cmd": "gateIn", "gateId": gate_id}
    if serial_no:
        cmd["serialNo"] = serial_no
    if ts is not None:
        cmd["ts"] = ts
    return encode_frame(json.dumps(cmd, separators=(",", ":")).encode())


def build_gate_in_card(
    *,
    gate_id: str,
    card_no: str,
    serial_no: str = "",
    ts: int | None = None,
) -> bytes:
    """GATE_IN_CARD command — announce RFID entry event.

    ``{"cmd":"gateInCard","gateId":"<gate>","cardNo":"<card>",
       "serialNo":"<serial>","ts":<unix_ts>}``
    """
    cmd: dict[str, Any] = {
        "cmd": "gateInCard",
        "gateId": gate_id,
        "cardNo": card_no,
    }
    if serial_no:
        cmd["serialNo"] = serial_no
    if ts is not None:
        cmd["ts"] = ts
    return encode_frame(json.dumps(cmd, separators=(",", ":")).encode())


def build_mt(
    *,
    gate_id: str,
    serial_no: str = "",
    data: dict[str, Any] | None = None,
) -> bytes:
    """MT (UART passthrough) command.

    ``{"cmd":"mt","gateId":"<gate>","serialNo":"<serial>","data":{...}}``
    """
    cmd: dict[str, Any] = {"cmd": "mt", "gateId": gate_id}
    if serial_no:
        cmd["serialNo"] = serial_no
    if data:
        cmd["data"] = data
    return encode_frame(json.dumps(cmd, separators=(",", ":")).encode())


# -- Response parsers ------------------------------------------------------


def parse_response(frame: bytes) -> dict[str, Any]:
    """Parse a raw frame (without length header) into a dict.

    Returns the parsed JSON, or ``{"error": "<message>", "raw": <hex>}`` on
    failure.
    """
    try:
        return json.loads(frame)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("cannot parse TCP frame: %s (raw=%s)", exc, frame.hex())
        return {"error": str(exc), "raw": frame.hex()}


def parse_trig_ack(data: dict) -> dict[str, Any]:
    """Extract fields from a TRIG ACK response."""
    return {
        "type": "trig_ack",
        "output": data.get("output"),
        "status": data.get("status"),
        "ts": data.get("ts"),
    }


def parse_input_frame(data: dict) -> dict[str, Any]:
    """Extract fields from an Input Frame (sensor states) response.

    Input frames contain: ``input1``-``input4``, ``pos1``-``pos3``,
    ``relay1``-``relay3``, ``beep``, ``ts``.
    """
    return {
        "type": "input_frame",
        "input1": data.get("input1"),
        "input2": data.get("input2"),
        "input3": data.get("input3"),
        "input4": data.get("input4"),
        "pos1": data.get("pos1"),
        "pos2": data.get("pos2"),
        "pos3": data.get("pos3"),
        "relay1": data.get("relay1"),
        "relay2": data.get("relay2"),
        "relay3": data.get("relay3"),
        "beep": data.get("beep"),
        "ts": data.get("ts"),
    }


def parse_status_code(data: dict) -> int:
    """Extract the numeric status code from a controller response."""
    return int(data.get("status") or data.get("code") or 0)
