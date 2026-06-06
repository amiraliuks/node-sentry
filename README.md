# NodeSentry

A distributed embedded Wi-Fi security monitoring platform. NodeSentry deploys WeMos D1 Mini Pro nodes around a space to passively monitor 802.11 traffic and detect common Wi-Fi attacks in real time, aggregating data to a central dashboard.

---

## Behind the Name

**Node** represents the distributed WeMos micro-sensors - each one a small, low-power embedded device deployed independently across a physical space.

**Sentry** represents a passive guard standing at the perimeter, watching for threats without interfering with the environment it monitors.

Together: *a distributed network of digital guards protecting local airspace.*

---

## Architecture

```
 SENSOR LAYER
+-----------------------------------------------------+
|                                                     |
|   [D1 Mini Node 1]      [D1 Mini Node 2]           |
|   - monitor mode        - monitor mode              |
|   - detects deauth      - detects deauth            |
|   - logs probes         - logs probes               |
|   - edge processing     - edge processing           |
|   - local aggregation   - local aggregation         |
|          |                      |                   |
+----------+----------------------+-------------------+
           | MQTT over WiFi       | MQTT over WiFi
           | (JSON payloads)      |
           v                      v
 BROKER LAYER
+-----------------------------------------------------+
|                                                     |
|            Mosquitto MQTT Broker                    |
|            runs on your laptop / homelab            |
|            localhost:1883                           |
|                                                     |
|   topics:                                           |
|   nodes/node1/alerts                                |
|   nodes/node1/stats                                 |
|   nodes/node2/alerts                                |
|   nodes/node2/stats                                 |
|                                                     |
+---------------------+-------------------------------+
                      | subscribed via paho-mqtt
                      v
 BACKEND LAYER
+-----------------------------------------------------+
|                                                     |
|            Python / Flask app                       |
|                                                     |
|   - consumes MQTT messages                          |
|   - stores alerts to SQLite                         |
|   - REST API  GET /api/alerts                       |
|              GET /api/stats                         |
|              GET /api/nodes                         |
|   - pushes live updates via SocketIO                |
|                                                     |
+---------------------+-------------------------------+
                      | WebSocket + REST
                      v
 FRONTEND LAYER
+-----------------------------------------------------+
|                                                     |
|        Flask-served HTML/CSS/JS dashboard           |
|                                                     |
|   - live alert feed                                 |
|   - node status (online/offline)                    |
|   - attack type breakdown (Chart.js)                |
|   - per-node packet stats                           |
|   - MAC vendor resolution                           |
|   - RSSI signal strength indicators                 |
|                                                     |
+-----------------------------------------------------+
```

Each sensor node performs **edge processing and local aggregation** before publishing to the broker. Raw frame counts and threshold comparisons happen on-device, so the central database is not exposed to high-frequency packet bursts during active wireless attacks. Only meaningful events are forwarded upstream.

---

## Detection Capabilities

- **Deauth flood detection** - counts deauthentication frames per source MAC in a sliding time window and flags sustained floods
- **Probe request logging** - logs every device broadcasting saved network names (MAC, SSID, RSSI, timestamp)
- **Evil twin AP detection** - flags new BSSIDs broadcasting a known legitimate SSID
- **Karma attack detection** - flags devices responding to probe requests for SSIDs they have never beaconed
- **Hardware OUI Fingerprinting** - the backend parses the first three octets of each MAC address against an OUI prefix table to identify device manufacturers such as Apple, Samsung, Espressif, and Raspberry Pi. Vendor names are displayed inline in the alert feed for faster threat assessment
- **Node Status and Failure Tracking (LWT)** - each node registers an MQTT Last Will and Testament message on connect. If a node loses power or drops off the network unexpectedly, the broker automatically publishes the LWT payload, and the dashboard flags that node as offline. This distinguishes a clean shutdown from an unexpected failure

---

## Project Structure

```
node-sentry/
├── nodes/
│   ├── firmware/
│   │   └── firmware.ino        # D1 Mini C++ firmware (Arduino)
│   └── mock_node.py            # simulate a node for testing
├── server/
│   ├── main.py                 # Flask app + SocketIO + API
│   ├── mqtt_client.py          # MQTTClient class
│   ├── database.py             # SQLite storage with connection pooling
│   ├── templates/
│   │   └── index.html          # dashboard HTML
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── dashboard.js
├── docs/
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Stack

| Layer | Technology |
|---|---|
| Node firmware | C++ / Arduino framework |
| Message broker | Mosquitto (MQTT) |
| Backend | Python, Flask, Flask-SocketIO, paho-mqtt |
| Database | SQLite with WAL mode |
| Frontend | HTML / CSS / JS, Chart.js |
| Auth | API key via request header |
| Rate limiting | Flask-Limiter |

---

## Docker

The easiest way to run NodeSentry is with Docker Compose.

### Prerequisites
- Docker
- Docker Compose

### Setup

```bash
git clone https://github.com/amiraliuks/node-sentry
cd node-sentry
cp .env.example .env
# Edit .env and set API_KEY and SECRET_KEY
cp config.example.json config.json
```

### Run

```bash
docker compose up -d
```

Open `http://localhost:5000` in your browser.

### Stop

```bash
docker compose down
```

### Logs

```bash
docker compose logs -f app
docker compose logs -f mosquitto
```

---

## Manual Setup

### 1. Install dependencies

```bash
sudo apt install mosquitto mosquitto-clients
git clone https://github.com/amiraliuks/node-sentry
cd node-sentry
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set API_KEY and SECRET_KEY
```

### 2. Start the MQTT broker

```bash
mosquitto -v
```

### 3. Start the backend

```bash
python3 server/main.py
```

### 4. Open the dashboard

```
http://localhost:5000
```

### 5. Flash a node or run the mock

```bash
# Mock node for testing without hardware
python3 nodes/mock_node.py
```

---

## Hardware

- WeMos D1 Mini Pro (ESP8266) + External SMA Antenna
- Arduino framework via PlatformIO or Arduino IDE

The external SMA antenna significantly extends passive monitoring range compared to the onboard PCB antenna, making it practical for monitoring larger spaces with a single node.

---

## API

All endpoints require an `X-API-Key` header.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/alerts` | Paginated alert log. Params: `limit`, `page`, `type`, `node` |
| GET | `/api/stats` | Alert counts by type |
| GET | `/api/nodes` | Latest stats snapshot per node |

---

## Roadmap

- [x] Project architecture and backend pipeline
- [x] Mock node for hardware-free testing
- [x] SQLite persistence with WAL mode and connection pooling
- [x] Paginated REST API with API key auth and rate limiting
- [x] Live dashboard with Chart.js visualizations
- [x] MAC vendor OUI fingerprinting
- [x] RSSI signal strength color coding
- [ ] Physical hardware verification on WeMos D1 Mini Pro
- [ ] C++ firmware - probe logging and deauth detection
- [ ] MQTT Last Will and Testament for node failure tracking
- [ ] Webhook notification engine (Telegram + Discord) with cooldown and severity filtering
- [ ] Whitelist/ignore specific MAC addresses
- [ ] Dynamic client-side node positioning map using RSSI triangulation
- [x] Docker Compose packaging for one-command deployment

---

## Legal Notice

NodeSentry is intended strictly for use on networks you own or have received explicit written authorization to monitor. Passive monitoring of wireless traffic on networks without authorization is illegal in most jurisdictions, including Kosovo's Law No. 06/L-082 on Cybercrime.

This tool operates in passive monitor mode only - it never injects frames, sends deauthentication packets, or actively interferes with any network or device. All development and testing was conducted exclusively on the author's own private network.

The author assumes no responsibility for misuse of this software.

---

## Inspiration

[Satur8](https://github.com/dionmulaj/Satur8)