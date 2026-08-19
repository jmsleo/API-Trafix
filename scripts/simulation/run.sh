#!/bin/bash
# run.sh — Start the full API-Trafix simulation stack.
#
# Usage:
#   bash scripts/simulation/run.sh
#
# This will:
#   1. Build and start Docker containers (DB, Redis, MQTT, API, Mock LPR, Mock TCP)
#   2. Wait for the API to be healthy
#   3. Print URLs and instructions
#   4. Launch the interactive mock gate controller

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.sim.yml"

cd "$PROJECT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        API-Trafix Simulation Stack                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not found. Install Docker first."
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "ERROR: Docker daemon not running. Start Docker Desktop first."
    exit 1
fi

# Check paho-mqtt for mock controller
if ! python3 -c "import paho.mqtt.client" 2>/dev/null; then
    echo "Installing paho-mqtt for mock gate controller..."
    pip install paho-mqtt 2>/dev/null || pip3 install paho-mqtt 2>/dev/null || {
        echo "WARNING: Could not install paho-mqtt."
        echo "Mock gate controller may not work. Install manually:"
        echo "  pip install paho-mqtt"
    }
fi

# Build and start containers
echo "Building and starting Docker containers..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "Waiting for API to be ready..."

# Wait for API health
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    printf "."
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo "WARNING: API did not respond within ${MAX_WAIT}s."
    echo "Check logs: docker compose -f $COMPOSE_FILE logs api"
fi

echo ""
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Simulation ready!                                  ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  Swagger docs:  http://localhost:8000/docs           ║"
echo "║  Signage:       http://localhost:8000/signage/?gate=1║"
echo "║  Adminer (DB):  http://localhost:8080                ║"
echo "║                                                      ║"
echo "║  MQTT broker:   localhost:1883                       ║"
echo "║  Mock LPR:      localhost:8090                       ║"
echo "║  Mock TCP:      localhost:5000                       ║"
echo "║                                                      ║"
echo "║  Ctrl+C to stop the mock controller                  ║"
echo "║  docker compose -f docker-compose.sim.yml down       ║"
echo "║    to stop all containers                            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Launch interactive mock gate controller
echo "Starting mock gate controller..."
echo ""
python3 "$SCRIPT_DIR/mock_gate_controller.py"

# When controller exits, ask to stop containers
echo ""
read -p "Stop Docker containers? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose -f "$COMPOSE_FILE" down
    echo "Containers stopped."
fi
