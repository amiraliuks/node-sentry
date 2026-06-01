import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from dotenv import load_dotenv
import os

from database import init_db, insert_alert, insert_stats, get_alerts, get_counts, get_nodes
from mqtt_client import MQTTClient

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nodesentry-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT   = int(os.getenv("MQTT_PORT", 1883))

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
    return render_template("index.html")

@app.route("/api/alerts")
def api_alerts():
    limit      = request.args.get("limit", 200, type=int)
    alert_type = request.args.get("type", None)
    node       = request.args.get("node", None)
    return jsonify(get_alerts(limit=limit, alert_type=alert_type, node=node))

@app.route("/api/stats")
def api_stats():
    return jsonify(get_counts())

@app.route("/api/nodes")
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
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)