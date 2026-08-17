#!/usr/bin/env python3
"""GPIO Bridge for BSS Parking Signage.

Runs on Raspberry Pi to replace the Vala signage app's GPIO handling.
Reads physical GPIO pins for vehicle detection and help button,
then calls API-Trafix endpoints to trigger signage updates.

Requirements:
    pip install requests RPi.GPIO

Usage:
    python gpio_bridge.py --config config.json

Config file (config.json):
    {
        "api_base_url": "http://192.168.1.13:8000",
        "gate_code": "1",
        "gpio_pin_vehicle": 17,
        "gpio_pin_help": 27,
        "poll_interval_ms": 100,
        "mqtt_enabled": true,
        "mqtt_host": "192.168.1.1",
        "mqtt_port": 1883,
        "mqtt_username": "bssparking",
        "mqtt_password": "BCTDev_2025"
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    api_base_url: str = "http://192.168.1.13:8000"
    gate_code: str = "1"
    gpio_pin_vehicle: int = 17
    gpio_pin_help: int = 27
    poll_interval_ms: int = 100
    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    debounce_seconds: float = 2.0
    help_debounce_seconds: float = 5.0

    @classmethod
    def from_file(cls, path: str) -> "Config":
        with open(path) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Config":
        config = cls()
        if args.config:
            config = cls.from_file(args.config)
        if args.gate_code:
            config.gate_code = args.gate_code
        if args.api_base_url:
            config.api_base_url = args.api_base_url
        return config


# ---------------------------------------------------------------------------
# MQTT Publisher (optional, for backward compatibility)
# ---------------------------------------------------------------------------

class MqttPublisher:
    """Publish MQTT messages for legacy signage compatibility."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = None
        if config.mqtt_enabled:
            try:
                import paho.mqtt.client as mqtt
                self.client = mqtt.Client(
                    client_id=f"gpio-bridge-{config.gate_code}",
                    protocol=mqtt.MQTTv311,
                )
                if config.mqtt_username:
                    self.client.username_pw_set(config.mqtt_username, config.mqtt_password)
                self.client.connect(config.mqtt_host, config.mqtt_port, 60)
                self.client.loop_start()
                logging.info("MQTT connected to %s:%d", config.mqtt_host, config.mqtt_port)
            except Exception as e:
                logging.error("MQTT connection failed: %s", e)
                self.client = None

    def publish_gate_status(self, gate: str, status: str) -> None:
        """Publish gate status to legacy topics."""
        if self.client is None:
            return
        try:
            payload = json.dumps({"status": status})
            self.client.publish("/GATE/IN/{gate}/status", payload)
            self.client.publish("gate/text", payload)
        except Exception as e:
            logging.error("MQTT publish failed: %s", e)

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# ---------------------------------------------------------------------------
# GPIO Handler
# ---------------------------------------------------------------------------

class GpioHandler:
    """Read GPIO pins and trigger API calls."""

    def __init__(self, config: Config, mqtt: MqttPublisher) -> None:
        self.config = config
        self.mqtt = mqtt
        self.last_vehicle_trigger = 0.0
        self.last_help_trigger = 0.0
        self._running = True

        # Try to import RPi.GPIO
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self._setup_gpio()
            self._has_gpio = True
            logging.info("GPIO initialized: vehicle=%d, help=%d",
                        config.gpio_pin_vehicle, config.gpio_pin_help)
        except ImportError:
            self._has_gpio = False
            logging.warning("RPi.GPIO not available, running in HTTP-only mode")

    def _setup_gpio(self) -> None:
        """Setup GPIO pins."""
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(self.config.gpio_pin_vehicle, self.GPIO.IN, pull_up_down=self.GPIO.PUD_UP)
        self.GPIO.setup(self.config.gpio_pin_help, self.GPIO.IN, pull_up_down=self.GPIO.PUD_UP)

    def check_pins(self) -> None:
        """Check GPIO pins and trigger actions."""
        if not self._has_gpio:
            return

        now = time.time()

        # Check vehicle detection pin
        if self.GPIO.input(self.config.gpio_pin_vehicle) == self.GPIO.LOW:
            if (now - self.last_vehicle_trigger) > self.config.debounce_seconds:
                self.last_vehicle_trigger = now
                self._on_vehicle_detected()

        # Check help button pin
        if self.GPIO.input(self.config.gpio_pin_help) == self.GPIO.LOW:
            if (now - self.last_help_trigger) > self.config.help_debounce_seconds:
                self.last_help_trigger = now
                self._on_help_button()

    def _on_vehicle_detected(self) -> None:
        """Vehicle detected on GPIO pin."""
        logging.info("Vehicle detected on gate %s", self.config.gate_code)
        self._call_api("/api/signage/vehicle-detected", {"gate": self.config.gate_code})
        self.mqtt.publish_gate_status(self.config.gate_code, "welcome")

    def _on_help_button(self) -> None:
        """Help button pressed."""
        logging.info("Help button pressed on gate %s", self.config.gate_code)
        self._call_api("/api/signage/help-button", {"gate": self.config.gate_code})

    def _call_api(self, endpoint: str, data: dict[str, Any]) -> None:
        """Call API-Trafix endpoint."""
        url = f"{self.config.api_base_url}{endpoint}"
        try:
            response = requests.post(url, json=data, timeout=5)
            if response.ok:
                logging.debug("API call %s: %s", endpoint, response.status_code)
            else:
                logging.warning("API call %s failed: %s", endpoint, response.status_code)
        except requests.RequestException as e:
            logging.error("API call %s error: %s", endpoint, e)

    def stop(self) -> None:
        self._running = False
        if self._has_gpio:
            self.GPIO.cleanup()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="GPIO Bridge for BSS Parking Signage")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--gate-code", "-g", help="Gate code (e.g., '1', '2')")
    parser.add_argument("--api-base-url", "-u", help="API base URL")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    config = Config.from_args(args)
    mqtt = MqttPublisher(config)
    gpio = GpioHandler(config, mqtt)

    # Handle shutdown
    def shutdown(signum, frame):
        logging.info("Shutting down...")
        gpio.stop()
        mqtt.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logging.info("GPIO Bridge started for gate %s", config.gate_code)
    logging.info("API: %s", config.api_base_url)

    # Main loop
    interval = config.poll_interval_ms / 1000.0
    while gpio._running:
        gpio.check_pins()
        time.sleep(interval)


if __name__ == "__main__":
    main()
