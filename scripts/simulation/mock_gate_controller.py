#!/usr/bin/env python3
"""Mock Gate Controller — interactive CLI that simulates gate hardware via MQTT.

Connects to the MQTT broker and lets you trigger gate events by pressing keys.
The API-Trafix orchestrator reacts to these events as if they came from
real hardware.

Usage:
    python mock_gate_controller.py                      # default gate 1
    GATE_CODE=2 MQTT_HOST=localhost python mock_gate_controller.py

Requirements:
    pip install paho-mqtt
"""

import json
import os
import sys
import time
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GATE_CODE = int(os.environ.get("GATE_CODE", "1"))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "bssparking")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "BCTDev_2025")

SERIAL_NO = f"MOCK-{GATE_CODE:03d}"
EVENT_TOPIC = f"/GATE/event/{GATE_CODE}"
STATUS_TOPIC = f"/GATE/IN/{GATE_CODE}/status"
COMMAND_TOPIC = f"/GATE/IN/{GATE_CODE}"

# State
inputs = {"input1": 0, "input2": 0, "input3": 0, "input4": 0}
relays = {"relay1": 0, "relay2": 0, "relay3": 0}
connected = False


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------

def on_connect(client, userdata, flags, rc, properties=None):
    global connected
    if rc == 0:
        connected = True
        # Subscribe to commands from the API
        client.subscribe(COMMAND_TOPIC)
        client.subscribe(STATUS_TOPIC)
        print(f"\r  ✓ Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
        print(f"  ✓ Subscribed to {COMMAND_TOPIC}")
    else:
        print(f"\r  ✗ Connection failed: code {rc}")


def on_disconnect(client, userdata, rc, properties=None):
    global connected
    connected = False
    print(f"\r  ✗ Disconnected (code {rc})")


def on_message(client, userdata, msg):
    """Handle commands from the API (barrier open, print, etc.)."""
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        print(f"\n  ⚠ Unparseable message on {msg.topic}")
        return

    if msg.topic == STATUS_TOPIC:
        status = payload.get("status")
        if status == "member_not_found":
            print(f"\n  🔊 VOICE: Member Tidak Terdaftar")
        return

    method = payload.get("method", "unknown")
    data = payload.get("data", {})

        if method == "outputCtrl":
            if "relay1Out" in data:
                relays["relay1"] = 1
                print(f"\n  ⚡ BARRIER OPENED (relay1: {data['relay1Out']})")
                # Auto-reset relay after pulse
                def reset_relay():
                    time.sleep(1.5)
                    relays["relay1"] = 0
                threading.Thread(target=reset_relay, daemon=True).start()
            if "beepOut" in data:
                print(f"  🔔 Beep: {data['beepOut']}")

        elif method == "txUartData":
            print(f"  🎫 TICKET PRINTED")

        else:
            print(f"\n  📨 Command received: {method}")

    except json.JSONDecodeError:
        print(f"\n  ⚠ Unparseable message on {msg.topic}")


# ---------------------------------------------------------------------------
# Event publishers
# ---------------------------------------------------------------------------

def publish_event(client, method, data):
    """Publish an event envelope to the gate's event topic."""
    payload = {
        "id": 1,
        "serialNo": SERIAL_NO,
        "version": "1.0",
        "method": method,
        "taskNo": 2,
        "data": data,
    }
    client.publish(EVENT_TOPIC, json.dumps(payload, separators=(",", ":")))
    print(f"  → Published {method} to {EVENT_TOPIC}")


def publish_heartbeat(client):
    """Publish a status heartbeat."""
    publish_event(client, "status", {
        **inputs,
        **relays,
        "beep": 0,
    })


def vehicle_arrives(client):
    """Simulate vehicle on the arrival loop."""
    inputs["input3"] = 1
    publish_event(client, "inputInfo", {"input3": 1})
    print("  🚗 Vehicle on arrival loop (input3=1)")


def ticket_button(client):
    """Simulate ticket button press."""
    inputs["input2"] = 1
    publish_event(client, "inputInfo", {"input2": 1})
    print("  🔘 Ticket button pressed (input2=1)")
    # Auto-release after debounce
    def release():
        time.sleep(0.5)
        inputs["input2"] = 0
    threading.Thread(target=release, daemon=True).start()


def vehicle_clears(client):
    """Simulate vehicle clearing the lane."""
    inputs["input3"] = 0
    inputs["input4"] = 1
    publish_event(client, "inputInfo", {"input4": 1})
    print("  ✅ Vehicle cleared lane (input4=1)")
    def release():
        time.sleep(0.5)
        inputs["input4"] = 0
    threading.Thread(target=release, daemon=True).start()


def rfid_card(client):
    """Simulate RFID card tap."""
    publish_event(client, "readCard", {
        "reader": 1,
        "cardLen": 10,
        "cardNo": "006343040",
    })
    print("  🃏 RFID card tapped: 006343040 (member: Angelo)")


def force_welcome(client):
    """Force welcome status on signage."""
    client.publish(STATUS_TOPIC, json.dumps({"status": "welcome"}))
    client.publish("gate/text", json.dumps({"status": "welcome"}))
    print("  📺 Status → welcome")


def force_thanks(client):
    """Force thanks status on signage."""
    client.publish(STATUS_TOPIC, json.dumps({"status": "thanks"}))
    client.publish("gate/text", json.dumps({"status": "thanks"}))
    print("  📺 Status → thanks")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

BANNER = """
╔══════════════════════════════════════════════════════╗
║         Mock Gate Controller — Gate {gate}              ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  [1] Vehicle arrives (loop sensor)                   ║
║  [2] Ticket button pressed                           ║
║  [3] Vehicle clears lane                             ║
║  [4] RFID card tap (member: Angelo)                  ║
║                                                      ║
║  [h] Send heartbeat                                  ║
║  [w] Force welcome status                            ║
║  [t] Force thanks status                             ║
║                                                      ║
║  [q] Quit                                            ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
"""

ACTIONS = {
    "1": ("Vehicle arrives", vehicle_arrives),
    "2": ("Ticket button", ticket_button),
    "3": ("Vehicle clears", vehicle_clears),
    "4": ("RFID card", rfid_card),
    "h": ("Heartbeat", publish_heartbeat),
    "w": ("Force welcome", force_welcome),
    "t": ("Force thanks", force_thanks),
}


def main():
    print(BANNER.format(gate=GATE_CODE))
    print(f"  Connecting to MQTT broker at {MQTT_HOST}:{MQTT_PORT}...")

    client = mqtt.Client(
        client_id=f"mock-gate-{GATE_CODE}",
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
    except Exception as e:
        print(f"  ✗ Cannot connect to MQTT broker: {e}")
        print(f"    Make sure Docker containers are running:")
        print(f"    docker compose -f docker-compose.sim.yml up -d")
        sys.exit(1)

    client.loop_start()

    # Wait for connection
    time.sleep(1)
    if not connected:
        print("  ⚠ Waiting for MQTT connection...")
        for _ in range(10):
            time.sleep(1)
            if connected:
                break
        if not connected:
            print("  ✗ Failed to connect. Check broker is running.")
            sys.exit(1)

    print()
    while True:
        try:
            choice = input("  ▸ ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break

        if choice == "q":
            print("  Bye!")
            break

        if choice in ACTIONS:
            name, func = ACTIONS[choice]
            func(client)
        elif choice:
            print(f"  ⚠ Unknown command: {choice}")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
