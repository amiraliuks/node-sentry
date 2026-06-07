import threading
from flask import Flask, render_template, jsonify, request
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
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "change-me-in-production")

CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

socketio = SocketIO(app, cors_allowed_origins=[
    "http://localhost:5000",
    "http://127.0.0.1:5000",
])

BROKER  = os.getenv("MQTT_BROKER", "localhost")
PORT    = int(os.getenv("MQTT_PORT", 1883))
API_KEY = os.getenv("API_KEY", "")
node_status: dict[str, str] = {}


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
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
    payload["severity"] = get_severity(payload.get("type", ""))
    insert_alert(payload)
    payload["vendor"] = get_vendor(payload.get("mac"))
    upsert_device(payload)
    notifier.process(payload)
    socketio.emit("alert", payload)

def on_stats(payload):
    insert_stats(payload)
    socketio.emit("stats", payload)


def on_status(payload):
    node      = payload.get("node")
    status    = payload.get("status", "offline")
    timestamp = payload.get("timestamp", 0)
    if node:
        node_status[node] = status
        print(f"[STATUS] {node} is {status}")
        socketio.emit("node_status", {"node": node, "status": status, "timestamp": timestamp})


def ctx(**kwargs):
    kwargs.setdefault("api_key", os.getenv("API_KEY", ""))
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
    for n in nodes:
        n["status"] = node_status.get(n["node"], "unknown")
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
    return jsonify(cfg_module.load())

@app.route("/api/config", methods=["POST"])
@require_api_key
@limiter.limit("10 per minute")
def api_config_post():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400
    ok = cfg_module.save(data)
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
    return render_template("api_docs.html", api_key=os.getenv("API_KEY", ""))

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
                        {"name": "type",  "in": "query", "schema": {"type": "string", "enum": ["deauth", "deauth_flood", "evil_twin", "karma", "probe"]}, "description": "Filter by alert type"},
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
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 200}},
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

if __name__ == "__main__":
    init_db()
    init_devices_table()

    mqtt = MQTTClient(
        broker=BROKER,
        port=PORT,
        on_alert=on_alert,
        on_stats=on_stats,
        on_status=on_status,
    )

    mqtt_thread = threading.Thread(target=mqtt.start, daemon=True)
    mqtt_thread.start()

    print("[*] NodeSentry starting on http://localhost:5000")
    if not API_KEY:
        print("[!] Warning: API_KEY not set in .env - endpoints are open (dev mode)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)