# PW Signage Package Analysis

Two Debian packages analyzed for the BSS Parking digital signage system.

---

## Package 1: `pw-signage-gateout` (v1.0.0)

**Purpose:** Gate-out signage — displays plate number + transaction info on a screen after the LPR camera reads the exiting vehicle.

**Binary:** 1.7MB ELF 32-bit ARM (Vala/GTK3 + libmosquitto + libsoup + GStreamer + SQLite)

**Source path:** `/Users/dytstudio/Documents/Development/BSS/Internals/pw-signage/pw-signage-gateout/`

### Database: `pw-signage-gateout-lpr.db`

```
CREATE TABLE data_lpr (
    picture TEXT,
    plate_num TEXT,
    transaction_code TEXT,
    upload_status TEXT DEFAULT 'not_uploaded',
    created_at TEXT
)
```

### MQTT Topics Subscribed

| Topic | Purpose |
|---|---|
| `gate/idle` | Idle screen content (ads carousel) |
| `gate/ads` | Advertisement playlist |
| `gate/text` | Text overlay (plate number, transaction) |
| `gate/out/1/pos` | POS trigger (publishes `outputCtrl` response) |

### MQTT Publishing

- **POS trigger response:** Publishes `gate/out/1/pos` with JSON:
  ```json
  {"id":1,"serialNo":"...","version":"1.0","method":"outputCtrl","taskNo":1,
   "data":{"beepOut":[1,100],"relay1Out":[1,1000]}}
  ```
- **PCLess trigger:** Publishes to `pcless_topic`

### HTTP API (GateOut upload)

- `POST http://{server_ip}/api/lpr/gateout`
  - Body: `admin_id`, `shift_id`, `plate_num`, `gate_out`, `url_image`
- `GET http://{server_ip}/image/{plate}.jpg` (local plate images)
- `GET https://drive.google.com/uc?export=download&id={id}` (Google Drive image download)
- Image saved locally at `http://{local_ip}:8090/image/{plate}.jpg`

### WebServer: Port 8090

- Serves local plate images
- POST endpoint receives LPR results from camera
- Publishes MQTT on `pos_topic` and `pcless_topic`

### GPIO

- `gpio_pin` config — used for input sensor (not exposed to API, just internal trigger)

### Config Keys (SQLite `settings` table)

| Key | Description |
|---|---|
| `gate_number` | Gate identifier |
| `mqtt_host` | MQTT broker address |
| `mqtt_username` | MQTT username |
| `mqtt_password` | MQTT password |
| `text_topic` | MQTT text topic |
| `idle_topic` | Idle screen MQTT topic |
| `ads_topic` | Ads playlist MQTT topic |
| `pos_topic` | POS trigger MQTT topic |
| `pcless_topic` | PCLess trigger MQTT topic |
| `admin_id` | Admin ID for API upload |
| `server_ip` | Backend server IP |

### Audio Assets

| File | Purpose |
|---|---|
| `welcome.wav` | Vehicle entry welcome |
| `welcome-bak.wav` | Backup welcome |
| `thankyou.wav` | Exit thank you |
| `thanks.wav` | Exit thanks (alt) |
| `thanks-short.wav` | Short exit thanks |
| `error.wav` | Error sound |
| `enter.wav` | Entry sound |
| `plate_not_found.wav` | Unknown plate |
| `nopaper.wav` | No paper/ticket |
| `card-not-registered.wav` | Unregistered card |
| `card-expired.wav` | Expired card |
| `card-expired-3days.wav` | Card expiring soon |
| `card-already-entered.wav` | Duplicate entry |
| `jinglebss.mp3` | BSS jingle |

---

## Package 2: `pw-signage` (v1.0.0)

**Purpose:** Gate-in signage — displays welcome screen, plays audio when vehicle enters, manages ads/BGM/intercom.

**Binary:** 524KB ELF 32-bit ARM (Vala/GTK3 + libmosquitto + GStreamer + SQLite)

**Source path:** `/home/ztl/Documents/development/pw-signage/`

### Database: SQLite

```
-- Settings table
CREATE TABLE settings (
    gate_number TEXT PRIMARY KEY,
    text_topic TEXT,
    media_topic TEXT,
    mqtt_host TEXT,
    mqtt_username TEXT,
    mqtt_password TEXT,
    volume_audio INTEGER,
    volume_media INTEGER,
    layout TEXT,
    is_bgm_enabled INTEGER DEFAULT 1
)

-- Playlist table (ads)
CREATE TABLE playlist (
    gate_number TEXT,
    start_date TEXT,
    end_date TEXT,
    media_type TEXT,
    url TEXT,
    local_path TEXT,
    audio_url TEXT,
    audio_local_path TEXT
)
```

### MQTT Topics Subscribed

| Topic | Purpose |
|---|---|
| `gate/text` | Text overlay (plate number, welcome message) |
| `gate/setting` | Dynamic config update (hot-reload MQTT credentials/topics) |
| `gate/ads` | Advertisement playlist |
| `gate/idle` | Idle screen content |

### MQTT Topics Published

- None directly (responds to gate/text messages only)

### GPIO

- **GpioService** — reads physical GPIO pin for:
  - Vehicle detection (welcome trigger)
  - Help button press (intercom call)
- Configurable via `gpio_pin` setting (-1 to disable)
- Writes to `/sys/class/gpio/export` and `/sys/class/gpio/gpio%d`
- Signals: `SIGNAGE_GPIO_SERVICE_CHANGED_SIGNAL`, `SIGNAGE_GPIO_SERVICE_HELP_BUTTON_PRESSED_SIGNAL`

### Intercom

- `signage_api_service_make_intercom_call()` — initiates intercom when help button pressed
- `intercom.yourdomain.com` placeholder URL

### BGM (Background Music)

- Configurable via `is_bgm_enabled`
- GStreamer pipeline for audio playback
- Loops continuously when enabled

### Audio Assets

| File | Purpose |
|---|---|
| `welcome.wav` | Entry welcome |
| `welcome-bak.wav` | Backup welcome |
| `thanks.wav` | Exit thanks |
| `thanks-short.wav` | Short thanks |
| `error.wav` | Error sound |
| `enter.wav` | Entry sound |
| `card-not-registered.wav` | Unregistered card |
| `card-expired.wav` | Expired card |
| `card-expired-3days.wav` | Expiring soon |
| `card-already-entered.wav` | Duplicate entry |
| `jinglebss.mp3` | BSS jingle |

### Config Keys (via Settings UI + MQTT `gate/setting`)

| Key | Description |
|---|---|
| `gate_number` | Gate identifier |
| `text_topic` | MQTT text topic |
| `media_topic` | MQTT media topic |
| `mqtt_host` | MQTT broker address |
| `mqtt_username` | MQTT username |
| `mqtt_password` | MQTT password |
| `volume_audio` | Audio volume (0-100) |
| `volume_media` | Media volume (0-100) |
| `layout` | UI layout style |
| `is_bgm_enabled` | Enable/disable background music |
| `gpio-pin` | GPIO pin number for vehicle detection |

---

## Key Differences

| Feature | `pw-signage` (gate-in) | `pw-signage-gateout` (gate-out) |
|---|---|---|
| Binary size | 524KB | 1.7MB |
| Primary role | Welcome screen + audio | Plate display + API upload |
| MQTT publish | No | Yes (POS, PCLess triggers) |
| HTTP API upload | No | Yes (uploads plate to backend) |
| GPIO | Vehicle detect + help button | Sensor trigger only |
| Intercom | Yes | No |
| BGM | Yes | No |
| Ads management | Yes (download + cache) | Yes (subscribe only) |
| WebServer | No | Port 8090 (serves images) |
| LPR database | No | Yes (`data_lpr` table) |

## MQTT Topic Map (Both Packages)

```
gate/text          ← both subscribe (text overlay)
gate/ads           ← both subscribe (ad playlist)
gate/idle          ← gateout subscribes (idle screen)
gate/setting       ← signage subscribes (dynamic config)
gate/out/{N}/pos   ← gateout publishes (POS trigger response)
```

## Relevance to API-Trafix

1. **GateOut uploads plates to `POST /api/lpr/gateout`** — our API already has `POST /api/lpr/camera/upload` which may be the same endpoint
2. **GateOut publishes `outputCtrl` MQTT responses** — these are the barrier open confirmations we need to handle in the orchestrator
3. **GateIn `gate/setting` topic** — dynamic config update, could be used to update MQTT credentials without restarting
4. **GateOut local SQLite DB** — stores plates pending upload, syncs when backend available
5. **No TCP in either package** — both signage apps use MQTT only, TCP is controller-only
