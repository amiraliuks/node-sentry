import threading
import hmac
import re
import copy
import time
from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv
from functools import wraps
import os

from database import init_db, insert_alert, insert_stats, get_alerts, get_counts, get_nodes, get_vendor, upsert_device, get_devices, init_devices_table, get_severity
from mqtt_client import MQTTClient
import config as cfg_module
import notifier

load_dotenv()

app = Flask(__name__)

# SECRET_KEY signs the session cookie. Never fall back to a shipped constant:
# generate an ephemeral key if it is unset (sessions just won't survive a restart).
_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = os.urandom(32).hex()
    print("[!] Warning: SECRET_KEY not set - using an ephemeral key (sessions reset on restart)")
app.config["SECRET_KEY"] = _secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
)

CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins=[
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ],
)

BROKER  = os.getenv("MQTT_BROKER", "localhost")
PORT    = int(os.getenv("MQTT_PORT", 1883))
API_KEY = os.getenv("API_KEY", "")
node_status: dict[str, str] = {}
_status_lock = threading.Lock()

# Fail closed under a production WSGI server (gunicorn imports this module, so the
# __main__ guard below never runs). Refuse to serve open /api endpoints unless an
# explicit non-production dev opt-in is set.
if __name__ != "__main__" and not API_KEY and os.getenv("NODESENTRY_DEV_MODE") != "1":
    raise SystemExit(
        "[FATAL] API_KEY is not set. Refusing to start open /api endpoints under a WSGI server.\n"
        "        Set API_KEY, or set NODESENTRY_DEV_MODE=1 for an explicit (non-production) open run."
    )

# --- Input validation (MQTT payloads and config writes are UNTRUSTED) ---
NODE_RE           = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAC_RE            = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
VALID_ALERT_TYPES = {"deauth", "probe", "evil_twin", "karma"}
MAX_SSID_LEN      = 64
CONFIG_MASK       = "********"
PAGE_ENDPOINTS    = {"index", "alerts", "nodes", "probes", "settings", "devices", "api_docs"}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _valid_node(node):
    return node if isinstance(node, str) and NODE_RE.match(node) else None


def _clean_alert(payload):
    """Validate/normalize an untrusted MQTT alert payload. Returns a clean dict or None."""
    if not isinstance(payload, dict):
        return None
    atype = payload.get("type")
    if atype not in VALID_ALERT_TYPES:
        return None
    node = _valid_node(payload.get("node"))
    if not node:
        return None

    mac  = payload.get("mac")
    mac  = mac.upper() if isinstance(mac, str) and MAC_RE.match(mac) else None
    ssid = payload.get("ssid")
    if ssid is not None:
        ssid = str(ssid)[:MAX_SSID_LEN]

    clean = {
        "node":      node,
        "type":      atype,
        "mac":       mac,
        "ssid":      ssid,
        "rssi":      _as_int(payload.get("rssi"), None),
        "timestamp": int(time.time()),   # server-authoritative; never trust node clocks
    }
    if isinstance(payload.get("count"), (int, float)):
        clean["count"] = int(payload["count"])
    for k in ("rogue_bssid", "legit_bssid"):
        v = payload.get(k)
        if isinstance(v, str) and MAC_RE.match(v):
            clean[k] = v.upper()
    return clean


def _clean_stats(payload):
    """Validate/normalize an untrusted MQTT stats payload. Returns a clean dict or None."""
    if not isinstance(payload, dict):
        return None
    node = _valid_node(payload.get("node"))
    if not node:
        return None
    return {
        "node":           node,
        "uptime":         _as_int(payload.get("uptime")),
        "packets_seen":   _as_int(payload.get("packets_seen")),
        "alerts_sent":    _as_int(payload.get("alerts_sent")),
        "free_heap":      _as_int(payload.get("free_heap")),
        "rssi_to_broker": _as_int(payload.get("rssi_to_broker")),
        "timestamp":      int(time.time()),
    }


def _clamp_int(value, lo, hi, default):
    return max(lo, min(hi, _as_int(value, default)))


def _redacted_config():
    """Config for GET /api/config with secrets masked."""
    cfg = copy.deepcopy(cfg_module.load())
    tg  = cfg.get("notifications", {}).get("telegram", {})
    if tg.get("bot_token"):
        tg["bot_token"] = CONFIG_MASK
    dc = cfg.get("notifications", {}).get("discord", {})
    if dc.get("webhook_url"):
        dc["webhook_url"] = CONFIG_MASK
    return cfg


def _sanitize_config(data):
    """Build a clean config from only known keys/types; a secret sent back as the
    mask sentinel means 'keep the stored value'. Returns a dict or None."""
    if not isinstance(data, dict):
        return None
    current = cfg_module.load()
    out     = copy.deepcopy(cfg_module.DEFAULTS)

    notifs = data.get("notifications") if isinstance(data.get("notifications"), dict) else {}
    tg_in  = notifs.get("telegram") if isinstance(notifs.get("telegram"), dict) else {}
    dc_in  = notifs.get("discord")  if isinstance(notifs.get("discord"), dict)  else {}
    cur_tg = current.get("notifications", {}).get("telegram", {})
    cur_dc = current.get("notifications", {}).get("discord", {})

    token = str(tg_in.get("bot_token", ""))[:200]
    out["notifications"]["telegram"]["enabled"]   = bool(tg_in.get("enabled", False))
    out["notifications"]["telegram"]["bot_token"] = cur_tg.get("bot_token", "") if token == CONFIG_MASK else token
    out["notifications"]["telegram"]["chat_id"]   = str(tg_in.get("chat_id", ""))[:64]

    webhook = str(dc_in.get("webhook_url", ""))[:300]
    out["notifications"]["discord"]["enabled"]     = bool(dc_in.get("enabled", False))
    out["notifications"]["discord"]["webhook_url"] = cur_dc.get("webhook_url", "") if webhook == CONFIG_MASK else webhook

    th = data.get("thresholds") if isinstance(data.get("thresholds"), dict) else {}
    out["thresholds"]["deauth_count"]          = _clamp_int(th.get("deauth_count"), 1, 1000, 5)
    out["thresholds"]["deauth_window_seconds"] = _clamp_int(th.get("deauth_window_seconds"), 1, 3600, 60)
    out["thresholds"]["cooldown_seconds"]      = _clamp_int(th.get("cooldown_seconds"), 1, 86400, 300)

    wl = data.get("whitelist")
    if isinstance(wl, list):
        out["whitelist"] = [str(m)[:32] for m in wl if isinstance(m, str)][:256]
    return out


@app.before_request
def _mark_dashboard_session():
    # Visiting any dashboard page authenticates the browser for same-origin API
    # calls via an HttpOnly cookie, so the API key is never exposed to JS/XSS.
    if request.endpoint in PAGE_ENDPOINTS:
        session["dashboard"] = True


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)            # open/dev mode (bound to localhost at startup)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key and hmac.compare_digest(key, API_KEY):
            return f(*args, **kwargs)             # server-to-server / CLI client
        if session.get("dashboard"):
            return f(*args, **kwargs)             # same-origin browser (HttpOnly cookie)
        return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key"}), 401
    return decorated


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Rate limit exceeded", "message": str(e.description)}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


def on_alert(payload):
    alert = _clean_alert(payload)
    if alert is None:
        print("[MQTT] Dropped malformed alert payload")
        return
    alert["severity"] = get_severity(alert["type"])
    insert_alert(alert)
    alert["vendor"] = get_vendor(alert.get("mac"))
    upsert_device(alert)
    notifier.process(alert)
    socketio.emit("alert", alert)

def on_stats(payload):
    stats = _clean_stats(payload)
    if stats is None:
        print("[MQTT] Dropped malformed stats payload")
        return
    insert_stats(stats)
    socketio.emit("stats", stats)


def on_status(payload):
    if not isinstance(payload, dict):
        return
    node   = _valid_node(payload.get("node"))
    status = payload.get("status", "offline")
    if status not in ("online", "offline"):
        status = "offline"
    if node:
        with _status_lock:
            node_status[node] = status
        print(f"[STATUS] {node} is {status}")
        socketio.emit("node_status", {"node": node, "status": status, "timestamp": int(time.time())})


def ctx(**kwargs):
    # The API key is no longer templated into pages; the browser authenticates
    # via the HttpOnly session cookie. Kept as a thin passthrough for routes.
    return kwargs

@app.route("/")
def index():
    return render_template("dashboard.html", active="dashboard", page_title="Dashboard", **ctx())

@app.route("/alerts")
def alerts():
    return render_template("alerts.html", active="alerts", page_title="Alerts", **ctx())

@app.route("/nodes")
def nodes():
    return render_template("nodes.html", active="nodes", page_title="Nodes", **ctx())

@app.route("/probes")
def probes():
    return render_template("probes.html", active="probe", page_title="Probe Log", **ctx())

@app.route("/settings")
def settings():
    return render_template("settings.html", active="settings", page_title="Settings", **ctx())

@app.route("/devices")
def devices():
    return render_template("devices.html", active="devices", page_title="Devices", **ctx())


# --- API Endpoints ---

@app.route("/api/alerts")
@require_api_key
@limiter.limit("60 per minute")
def api_alerts():
    limit      = request.args.get("limit", 50, type=int)
    page       = request.args.get("page", 1, type=int)
    alert_type = request.args.get("type", None)
    node       = request.args.get("node", None)
    return jsonify(get_alerts(limit=limit, page=page, alert_type=alert_type, node=node))

@app.route("/api/stats")
@require_api_key
@limiter.limit("60 per minute")
def api_stats():
    return jsonify(get_counts())

@app.route("/api/nodes")
@require_api_key
@limiter.limit("60 per minute")
def api_nodes():
    nodes = get_nodes()
    with _status_lock:
        snapshot = dict(node_status)
    for n in nodes:
        n["status"] = snapshot.get(n["node"], "unknown")
    return jsonify(nodes)

@app.route("/api/devices")
@require_api_key
@limiter.limit("60 per minute")
def api_devices():
    limit = request.args.get("limit", 200, type=int)
    page  = request.args.get("page", 1, type=int)
    return jsonify(get_devices(limit=limit, page=page))

@app.route("/api/config", methods=["GET"])
@require_api_key
@limiter.limit("30 per minute")
def api_config_get():
    return jsonify(_redacted_config())

@app.route("/api/config", methods=["POST"])
@require_api_key
@limiter.limit("10 per minute")
def api_config_post():
    data = request.get_json(silent=True)
    clean = _sanitize_config(data)
    if clean is None:
        return jsonify({"error": "Invalid config body"}), 400
    ok = cfg_module.save(clean)
    if ok:
        return jsonify({"success": True})
    return jsonify({"error": "Failed to save config"}), 500

@app.route("/api/config/test/telegram", methods=["POST"])
@require_api_key
@limiter.limit("5 per minute")
def api_test_telegram():
    conf = cfg_module.load()
    ok   = notifier.test_telegram(conf["notifications"]["telegram"])
    return jsonify({"success": ok})

@app.route("/api/config/test/discord", methods=["POST"])
@require_api_key
@limiter.limit("5 per minute")
def api_test_discord():
    conf = cfg_module.load()
    ok   = notifier.test_discord(conf["notifications"]["discord"])
    return jsonify({"success": ok})


# --- OpenAPI Documentation Endpoints ---

@app.route("/api/docs")
def api_docs():
    return render_template("api_docs.html")

@app.route("/api/openapi.json")
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "NodeSentry API",
            "version": "1.0.0",
            "description": "REST API for the NodeSentry distributed Wi-Fi security monitoring platform."
        },
        "servers": [{"url": "http://localhost:5000"}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key"
                }
            }
        },
        "security": [{"ApiKeyAuth": []}],
        "paths": {
            "/api/alerts": {
                "get": {
                    "summary": "List alerts",
                    "description": "Returns paginated alert log with optional filtering.",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 500}, "description": "Results per page"},
                        {"name": "page",  "in": "query", "schema": {"type": "integer", "default": 1}, "description": "Page number"},
                        {"name": "type",  "in": "query", "schema": {"type": "string", "enum": ["deauth", "evil_twin", "karma", "probe"]}, "description": "Filter by alert type"},
                        {"name": "node",  "in": "query", "schema": {"type": "string"}, "description": "Filter by node ID"},
                    ],
                    "responses": {
                        "200": {"description": "Paginated alert list"},
                        "401": {"description": "Invalid or missing API key"},
                        "429": {"description": "Rate limit exceeded"}
                    }
                }
            },
            "/api/stats": {
                "get": {
                    "summary": "Alert counts by type",
                    "description": "Returns total alert count broken down by type.",
                    "responses": {
                        "200": {"description": "Alert counts"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/api/nodes": {
                "get": {
                    "summary": "Node status",
                    "description": "Returns latest stats snapshot for each connected node.",
                    "responses": {
                        "200": {"description": "Node list"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/api/devices": {
                "get": {
                    "summary": "Tracked devices",
                    "description": "Returns all devices tracked by MAC address with first/last seen, alert counts and SSID history.",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 200, "maximum": 500}},
                        {"name": "page",  "in": "query", "schema": {"type": "integer", "default": 1}},
                    ],
                    "responses": {
                        "200": {"description": "Device list"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/api/config": {
                "get": {
                    "summary": "Get configuration",
                    "description": "Returns current NodeSentry configuration including notification settings and thresholds.",
                    "responses": {
                        "200": {"description": "Configuration object"},
                        "401": {"description": "Unauthorized"}
                    }
                },
                "post": {
                    "summary": "Update configuration",
                    "description": "Saves updated configuration to config.json.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    },
                    "responses": {
                        "200": {"description": "Success"},
                        "400": {"description": "Invalid JSON"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/api/config/test/telegram": {
                "post": {
                    "summary": "Test Telegram notification",
                    "description": "Sends a test message to verify Telegram bot configuration.",
                    "responses": {
                        "200": {"description": "Result"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            },
            "/api/config/test/discord": {
                "post": {
                    "summary": "Test Discord notification",
                    "description": "Sends a test embed to verify Discord webhook configuration.",
                    "responses": {
                        "200": {"description": "Result"},
                        "401": {"description": "Unauthorized"}
                    }
                }
            }
        }
    }
    return jsonify(spec)

def _startup():
    """Initialize the DB and start the MQTT consumer. Runs once at import so it
    works under both `python main.py` (dev) and `gunicorn main:app` (production,
    single worker). With >1 gunicorn worker this would start duplicate MQTT
    consumers, so the deployment must keep --workers 1."""
    init_db()
    init_devices_table()
    mqtt = MQTTClient(
        broker=BROKER,
        port=PORT,
        on_alert=on_alert,
        on_stats=on_stats,
        on_status=on_status,
    )
    threading.Thread(target=mqtt.start, daemon=True, name="mqtt-consumer").start()


_startup()


if __name__ == "__main__":
    # Development server only. Production runs gunicorn (see Dockerfile), which
    # imports `app` above and never executes this block.
    host = "0.0.0.0"
    if not API_KEY:
        if os.getenv("NODESENTRY_DEV_MODE") != "1":
            raise SystemExit(
                "[FATAL] API_KEY is not set. Refusing to start with open /api endpoints.\n"
                "        Set API_KEY in .env, or set NODESENTRY_DEV_MODE=1 to run open on localhost only."
            )
        host = "127.0.0.1"
        print("[!] DEV MODE: API auth disabled, binding to 127.0.0.1 only")
    print(f"[*] NodeSentry starting on http://{host}:5000")
    socketio.run(app, host=host, port=5000, debug=False, allow_unsafe_werkzeug=True)