#!/usr/bin/env python3
"""Mock TCP Controller — simulates a gate controller that speaks raw TCP.

Handles the length-delimited frame protocol used by the real gate hardware:
  [2 bytes big-endian length] [JSON payload]

Responds to heartbeat, TRIG, and outputCtrl commands.
Publishes sensor events periodically.

Usage:
    python mock_tcp_controller.py              # default port 5000
    GATE_CODE=2 python mock_tcp_controller.py  # simulate gate 2
"""

import asyncio
import json
import os
import struct
import time

GATE_CODE = int(os.environ.get("GATE_CODE", "1"))
PORT = int(os.environ.get("PORT", "5000"))
SERIAL_NO = f"MOCK-{GATE_CODE:03d}"

# Sensor states
inputs = {"input1": 0, "input2": 0, "input3": 0, "input4": 0}
relays = {"relay1": 0, "relay2": 0, "relay3": 0}


def encode_frame(payload: dict) -> bytes:
    """Encode a JSON payload into a length-delimited TCP frame."""
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack(">H", len(data)) + data


def decode_frame(data: bytes) -> tuple[dict | None, bytes]:
    """Decode a length-delimited TCP frame. Returns (payload, remaining)."""
    if len(data) < 2:
        return None, data
    length = struct.unpack(">H", data[:2])[0]
    if len(data) < 2 + length:
        return None, data
    payload = json.loads(data[2:2 + length])
    return payload, data[2 + length:]


def build_status() -> dict:
    """Build a status heartbeat envelope."""
    return {
        "id": 1,
        "serialNo": SERIAL_NO,
        "version": "1.0",
        "method": "status",
        "taskNo": 2,
        "data": {
            **inputs,
            **relays,
            "beep": 0,
        },
    }


def build_input_info(changed: dict) -> dict:
    """Build an inputInfo envelope."""
    return {
        "id": 1,
        "serialNo": SERIAL_NO,
        "version": "1.0",
        "method": "inputInfo",
        "taskNo": 2,
        "data": changed,
    }


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single TCP client connection."""
    addr = writer.get_extra_info("peername")
    print(f"[TCP] Client connected: {addr}")

    buffer = b""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break

            buffer += data
            while True:
                payload, buffer = decode_frame(buffer)
                if payload is None:
                    break

                method = payload.get("method", "")
                print(f"[TCP] Received: {method}")

                # Handle commands
                if method == "heartbeat":
                    resp = {
                        "id": payload.get("id", 1),
                        "serialNo": SERIAL_NO,
                        "version": "1.0",
                        "method": "heartbeat",
                        "taskNo": 2,
                        "data": {"status": "ok"},
                    }
                    writer.write(encode_frame(resp))
                    await writer.drain()
                    print(f"[TCP] Sent heartbeat ack")

                elif method == "trig":
                    resp = {
                        "id": payload.get("id", 1),
                        "serialNo": SERIAL_NO,
                        "version": "1.0",
                        "method": "trig",
                        "taskNo": 1,
                        "data": {"code": "0"},
                    }
                    writer.write(encode_frame(resp))
                    await writer.drain()
                    print(f"[TCP] Sent TRIG ack")

                elif method == "outputCtrl":
                    data = payload.get("data", {})
                    if "relay1Out" in data:
                        relays["relay1"] = 1
                        print(f"[TCP] Relay 1 activated: {data['relay1Out']}")
                    if "beepOut" in data:
                        print(f"[TCP] Beep: {data['beepOut']}")
                    resp = {
                        "id": payload.get("id", 1),
                        "serialNo": SERIAL_NO,
                        "version": "1.0",
                        "method": "outputCtrl",
                        "taskNo": 1,
                        "data": {},
                    }
                    writer.write(encode_frame(resp))
                    await writer.drain()
                    print(f"[TCP] Sent outputCtrl ack")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[TCP] Error: {e}")
    finally:
        writer.close()
        print(f"[TCP] Client disconnected: {addr}")


async def heartbeat_loop():
    """Send periodic heartbeat messages (simulated via stdout)."""
    while True:
        await asyncio.sleep(30)
        print(f"[TCP] Heartbeat: {json.dumps(build_status()['data'])}")


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    print(f"[TCP] Mock TCP controller listening on port {PORT}")
    print(f"[TCP] Gate code: {GATE_CODE}")
    print(f"[TCP] Serial: {SERIAL_NO}")
    print(f"[TCP] Waiting for connections...")

    async with server:
        await asyncio.gather(
            server.serve_forever(),
            heartbeat_loop(),
        )


if __name__ == "__main__":
    asyncio.run(main())
