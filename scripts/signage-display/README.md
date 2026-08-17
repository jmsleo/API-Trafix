# BSS Parking Signage Display

Web-based signage display that replaces the Vala signage app.

## Features

- Fullscreen kiosk mode display
- Real-time updates via SSE
- Welcome/Thanks status display
- Plate number display
- Ads slideshow
- Audio playback (welcome, thanks sounds)
- Idle background image
- Clock display
- Connection status indicator

## Installation (Raspberry Pi)

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y chromium-browser unclutter

# Create display directory
mkdir -p /home/pi/signage-display

# Copy files
cp start.sh /home/pi/signage-display/
chmod +x /home/pi/signage-display/start.sh

# Install systemd service
sudo cp signage-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signage-display
sudo systemctl start signage-display
```

## Configuration

Edit `start.sh` to set:
- `GATE_CODE`: Gate number (default: 1)
- `API_URL`: API-Trafix server URL

Or pass as arguments:
```bash
./start.sh 2 http://192.168.1.13:8000
```

## Manual Testing

Open in browser:
```
http://192.168.1.13:8000/signage/?gate=1
```

## API Endpoints Used

| Endpoint | Purpose |
|---|---|
| `GET /api/signage/stream/{gate}` | SSE stream for real-time updates |
| `GET /api/signage/status/{gate}` | Get current status |
| `POST /api/signage/status/{gate}` | Update status |

## Audio Files

Place audio files in `/storage/signage/audio/`:
- `welcome.wav` - Vehicle arrival sound
- `thanks.wav` - Exit thank you sound
- `error.wav` - Error sound

## Troubleshooting

1. **Display not showing**: Check if Chromium is running
2. **No updates**: Check SSE connection in browser console
3. **Audio not playing**: Check audio files exist and are accessible
4. **Fullscreen not working**: Click anywhere on screen to trigger fullscreen
