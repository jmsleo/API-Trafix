# API-Trafix Test Plan

## Prerequisites

```bash
# Start the API server
cd /home/americano/kerja/API-Trafix
uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000 --reload

# Open Swagger docs
# http://localhost:8000/docs
```

## Phase 1: System Health

| # | Endpoint | Method | Expected |
|---|---|---|---|
| 1 | `/api/system/health` | GET | `{"status": "healthy", "uptime_seconds": ..., "mqtt": {...}, "tcp": {...}}` |
| 2 | `/api/system/mqtt/status` | GET | `{"connected": false, "host": "", "port": 0, ...}` (if MQTT not enabled) |
| 3 | `/api/system/tcp/status` | GET | `{"enabled": false, "connected_gates": 0, "total_gates": 0}` (if TCP not enabled) |

## Phase 2: Gate Status

| # | Endpoint | Method | Expected |
|---|---|---|---|
| 4 | `/api/gates/status` | GET | `[]` (empty if no devices in DB), or array of gate health objects |
| 5 | `/api/gates/1/status` | GET | 404 if gate "1" not registered, else gate health detail |
| 6 | `/api/gates/1/sensors` | GET | 404 if not found, else `{"gate_code": "1", "sensors": {...}}` |

## Phase 3: Barrier Control

| # | Endpoint | Method | Expected |
|---|---|---|---|
| 7 | `/api/gates/1/barrier/open` | POST | 404 if no controller, else `{"status": "command_sent", "gate": "1", "mqtt_topic": "...", "tcp_sent": false}` |
| 8 | `/api/gates/1/relay/relay1/pulse` | POST | Same structure as above with `output_id` field |

## Phase 4: Events

| # | Endpoint | Method | Expected |
|---|---|---|---|
| 9 | `/api/events/stream` | GET | SSE stream (text/event-stream). Connect via browser or curl, should get keepalive frames |
| 10 | `/api/gate/events` | GET | `{"events": [...], "offset": 0, "limit": 50}` paginated history |

## Phase 5: TCP Gateway (if `TCP_ENABLED=true`)

| # | Endpoint | Method | Expected |
|---|---|---|---|
| 11 | `/api/system/tcp/status` | GET | `{"enabled": true, "connected_gates": N, "total_gates": M, "connections": [...]}` |
| 12 | `/api/gates/1/barrier/open` | POST | `{"tcp_sent": true}` if TCP connected for that gate |

## Manual Testing Checklist

```bash
# 1. Health check
curl http://localhost:8000/api/system/health | python3 -m json.tool

# 2. MQTT status
curl http://localhost:8000/api/system/mqtt/status | python3 -m json.tool

# 3. All gates status
curl http://localhost:8000/api/gates/status | python3 -m json.tool

# 4. Single gate status (replace "1" with your gate code)
curl http://localhost:8000/api/gates/1/status | python3 -m json.tool

# 5. Sensors
curl http://localhost:8000/api/gates/1/sensors | python3 -m json.tool

# 6. Open barrier (careful — will trigger gate!)
curl -X POST http://localhost:8000/api/gates/1/barrier/open | python3 -m json.tool

# 7. Pulse relay (generic)
curl -X POST http://localhost:8000/api/gates/1/relay/relay1/pulse | python3 -m json.tool

# 8. Paginated gate events
curl "http://localhost:8000/api/gate/events?limit=10" | python3 -m json.tool

# 9. SSE stream (keep open for 30s to see keepalive)
curl -N http://localhost:8000/api/events/stream
```

## On-Site Testing (with live gate controllers)

1. Set `MQTT_ENABLED=true` and `TCP_ENABLED=true` in `.env`
2. Start server: `uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000`
3. Watch logs for:
   - `system_status: MQTT connected to ...`
   - `gate_health: heartbeat from ...`
   - `tcp_gateway: connected to gate ...`
4. Press ticket button on gate → verify `GET /api/gates/1/sensors` shows input changes
5. Verify `GET /api/events/stream` shows `gate_heartbeat` and `gate_online` events
6. Test TCP frame format: capture with `tcpdump -i any port 5000 -w /tmp/tcp_capture.pcap` then open in Wireshark to confirm 2-byte vs 4-byte length field

## TCP Protocol Validation

If TCP commands don't work, check frame format:

```python
# Quick test in Python shell
from api_trafix.services.tcp_protocol import encode_frame, decode_frames
frame = encode_frame(b'{"cmd":"heartbeat"}')
print(frame.hex())  # Should show: 00127b22636d64223a22686561727462656174227d
# 0012 = 18 bytes length (2 bytes big-endian)
# Then the JSON payload
```

## Troubleshooting

| Issue | Fix |
|---|---|
| `ModuleNotFoundError: api_trafix.db` | Should be fixed — uses `api_trafix.config.database` |
| Gate shows offline | Check MQTT broker is running, verify gate controller is sending status messages |
| TCP not connecting | Verify gate IP/port in devices table config JSON: `{"connection_type": "tcp", "tcp_port": 5000}` |
| SSE stream disconnects | Check Redis is running, stream falls back to keepalive if Redis unavailable |
