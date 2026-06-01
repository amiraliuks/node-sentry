# node-sentry

A distributed embedded Wi-Fi security monitoring platform. node-sentry deploys WeMos D1 Mini Pro nodes around a space to passively monitor 802.11 traffic and detect common Wi-Fi attacks in real time, aggregating data to a central dashboard.

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
|   - detects evil twin   - detects evil twin         |
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
|                                                     |
+-----------------------------------------------------+
```

---

## Detection Capabilities

- **Deauth flood detection** — counts deauthentication frames per source MAC in a sliding time window
- **Probe request logging** — logs every device hunting for saved networks (MAC, SSID, RSSI, timestamp)
- **Evil twin AP detection** — flags new BSSIDs broadcasting a known SSID
- **Karma attack detection** — flags devices responding to probe requests for SSIDs they never beaconed

---

## Project Structure

```
node-sentry/
├── nodes/
│   ├── firmware/
│   │   └── firmware.ino        # D1 Mini C++ firmware (Arduino)
│   └── mock_node.py            # simulate a node for testing
├── server/
│   ├── main.py                 # Flask app + SocketIO
│   ├── mqtt_client.py          # MQTT broker connection
│   ├── database.py             # SQLite storage
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
| Database | SQLite |
| Frontend | HTML / CSS / JS, Chart.js |

---

## Setup

### 1. Install dependencies

```bash
sudo apt install mosquitto mosquitto-clients
git clone https://github.com/amiraliuks/node-sentry
cd node-sentry
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
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

### 5. Flash a node (or run the mock)

```bash
# Mock node for testing without hardware
python3 nodes/mock_node.py
```

---

## Hardware

- WeMos D1 Mini Pro (ESP8266) + external antenna
- Arduino framework via PlatformIO or Arduino IDE

---

## Roadmap

- [x] Project architecture
- [ ] Phase 1 — single node firmware (probe logging + deauth detection)
- [ ] Phase 2 — Flask backend + MQTT pipeline
- [ ] Phase 3 — live dashboard
- [ ] Phase 4 — multi-node support
- [ ] Phase 5 — OTA firmware updates

---

## Legal Notice

NodeSentry is intended strictly for use on networks you own or have received
explicit written authorization to monitor. Passive monitoring of wireless traffic
on networks without authorization is illegal in most jurisdictions, including
Kosovo's Law No. 06/L-082 on Cybercrime.

This tool operates in passive monitor mode only, it never injects frames,
sends deauthentication packets, or actively interferes with any network or device.
All development and testing was conducted exclusively on the author's own
private network.

The author assumes no responsibility for misuse of this software.

---

## Inspiration

[Satur8](https://github.com/dionmulaj/Satur8) by dionmulaj, a Python-based passive Wi-Fi monitoring framework. node-sentry takes a different approach: distributed embedded nodes on constrained ESP8266 hardware reporting to a central server.