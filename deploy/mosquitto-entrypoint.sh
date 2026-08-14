#!/bin/sh
# Entrypoint for the api-trafix MQTT broker.
#
# Creates the mosquitto password file from the MQTT_USERNAME / MQTT_PASSWORD
# environment variables (passed by docker-compose from the project .env), so
# credentials live in exactly one place and are re-created on every start.
#
# Runs as root (as the eclipse-mosquitto image does) and hands off to mosquitto,
# which drops privileges to the `mosquitto` user via mosquitto.conf.

set -eu

if [ -z "${MQTT_USERNAME:-}" ] || [ -z "${MQTT_PASSWORD:-}" ]; then
    echo "FATAL: MQTT_USERNAME and MQTT_PASSWORD must be set" >&2
    exit 1
fi

PASSWD_FILE=/mosquitto/config/passwd
touch "$PASSWD_FILE"
mosquitto_passwd -b "$PASSWD_FILE" "$MQTT_USERNAME" "$MQTT_PASSWORD"
echo "MQTT user ${MQTT_USERNAME} configured"

chown mosquitto:mosquitto "$PASSWD_FILE" /mosquitto/data /mosquitto/log
chmod 0700 "$PASSWD_FILE"

exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
