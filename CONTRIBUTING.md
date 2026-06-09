# Contributing to NodeSentry

Thanks for your interest in contributing. This document covers how to get the project running locally, the structure of the codebase, and how to submit changes.

---

## Getting started

### Prerequisites

- Python 3.11+
- Mosquitto MQTT broker
- A WeMos D1 Mini Pro (for firmware development) or use the mock node for backend work

### Local setup

```bash
git clone https://github.com/amiraliuks/node-sentry
cd node-sentry
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set API_KEY and SECRET_KEY (both required)
# Notification/threshold config is created on first save from the Settings page
# and persists under data/ (config.json.example documents the schema).
```

Start the broker:

```bash
mosquitto -v
```

Start the backend:

```bash
python3 server/main.py
```

Simulate a node (no hardware needed):

```bash
python3 nodes/mock_node.py
```

Open `http://localhost:5000`.

---

## Project structure

```
node-sentry/
├── nodes/
│   ├── firmware/
│   │   └── firmware.ino        # D1 Mini C++ firmware
│   └── mock_node.py            # MQTT simulator for testing
├── server/
│   ├── main.py                 # Flask app, routes, SocketIO, MQTT wiring
│   ├── mqtt_client.py          # MQTTClient class
│   ├── database.py             # SQLite layer - all reads and writes go here
│   ├── notifier.py             # Telegram and Discord notification engine
│   ├── config.py               # config.json reader/writer
│   ├── templates/              # Jinja2 HTML templates
│   └── static/
│       ├── css/style.css
│       └── js/                 # Per-page JavaScript modules
├── mosquitto/
│   └── mosquitto.conf
├── backfille_devices.py        # One-time migration script
├── update_oui.py               # Downloads IEEE OUI database
├── docker-compose.yml
├── Dockerfile
└── config.json.example
```

---

## How the stack fits together

1. A D1 Mini node (or `mock_node.py`) publishes JSON payloads to the MQTT broker on `nodes/<id>/alerts` and `nodes/<id>/stats`
2. `mqtt_client.py` subscribes to `nodes/#` and calls `on_alert` / `on_stats` callbacks in `main.py`
3. `main.py` stores the data, resolves the MAC vendor, scores severity, updates the device tracker, fires notifications if configured, then emits to connected browsers via SocketIO
4. The browser receives events in real time and updates the relevant page JS module

---

## Areas to contribute

- **Firmware** - C++ on ESP8266, channel hopping, LWT support, OTA updates
- **Detection** - new attack signatures, baseline learning, anomaly detection
- **Dashboard** - new visualizations, UX improvements
- **Notifications** - additional channels (Slack, email digest)
- **Docs** - improving this file, inline code comments, the API spec

---

## Submitting changes

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature`
3. Make your changes
4. Test locally with `mock_node.py`
5. Open a pull request with a clear description of what you changed and why

Keep pull requests focused (one feature or fix per PR). If you're unsure whether something is in scope, open an issue first.

---

## Code style

- Python: follow existing patterns, no external formatters required
- JavaScript: vanilla ES2020+, no frameworks, keep files page-scoped
- No `──` decorators or ornamental separators or emojis in comments
- Use clear, descriptive commit messages following the project's convention: `Add karma detection`, `Fix OUI lookup crash`

---

## Legal

By contributing you agree that your contributions will be licensed under the same license as the project. All testing must be done on networks you own or have explicit written authorization to access.