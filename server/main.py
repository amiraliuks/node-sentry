import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from functools import wraps
import os

from database import init_db, insert_alert, insert_stats, get_alerts, get_counts, get_nodes
from mqtt_client import MQTTClient

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "change-me-in-production")

# CORS (localhost only)
from flask_cors import CORS
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

# Rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

# SocketIO
socketio = SocketIO(app, cors_allowed_origins=[
    "http://localhost:5000",
    "http://127.0.0.1:5000",
])

BROKER  = os.getenv("MQTT_BROKER", "localhost")
PORT    = int(os.getenv("MQTT_PORT", 1883))
API_KEY = os.getenv("API_KEY", "")


# Auth decorator
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            # No key configured — open access (dev mode)
            return f(*args, **kwargs)
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated


# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Rate limit exceeded", "message": str(e.description)}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# MQTT callbacks
def on_alert(payload):
    insert_alert(payload)
    socketio.emit("alert", payload)

def on_stats(payload):
    insert_stats(payload)
    socketio.emit("stats", payload)


# Routes
@app.route("/")
def index():
    return render_template("index.html", api_key=os.getenv("API_KEY", ""))

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
    return jsonify(get_nodes())


# Start
if __name__ == "__main__":
    init_db()

    mqtt = MQTTClient(
        broker=BROKER,
        port=PORT,
        on_alert=on_alert,
        on_stats=on_stats,
    )

    mqtt_thread = threading.Thread(target=mqtt.start, daemon=True)
    mqtt_thread.start()

    print("[*] NodeSentry starting on http://localhost:5000")
    if not API_KEY:
        print("[!] Warning: API_KEY not set in .env — endpoints are open (dev mode)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)