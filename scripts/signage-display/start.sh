#!/bin/bash
# Startup script for BSS Parking Signage Display
# Runs Chromium in kiosk mode on Raspberry Pi

GATE_CODE="${1:-1}"
API_URL="${2:-http://192.168.1.13:8000}"

echo "Starting signage display for Gate $GATE_CODE"
echo "API URL: $API_URL"

# Wait for network
sleep 10

# Disable screen blanking
export DISPLAY=:0
xset s off
xset s noblank
xset -dpms

# Hide cursor
unclutter -idle 0 -root &

# Start Chromium in kiosk mode
chromium-browser \
    --noerrdialogs \
    --disable-infobars \
    --kiosk \
    --kiosk-printing \
    --disable-features=TranslateUI \
    --disable-extensions \
    --disable-translate \
    --disable-sync \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-features=TranslateUI \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --autoplay-policy=no-user-gesture-required \
    "${API_URL}/signage/?gate=${GATE_CODE}" &

echo "Signage display started. Press Ctrl+C to stop."

# Keep script running
wait
