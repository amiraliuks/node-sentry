import json
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import os

from database import init_db, insert_alert, insert_stats, get_alerts, get_counts, get_nodes

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nodesentry-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT   = int(os.getenv("MQTT_PORT", 1883))

# ── MQTT ──
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected to broker (rc={rc})")
    client.subscribe("nodes/#")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic   = msg.topic

        if "/alerts" in topic:
            print(f"[ALERT] {payload}")
            insert_alert(payload)
            socketio.emit("alert", payload)

        elif "/stats" in topic:
            print(f"[STATS] {payload}")
            insert_stats(payload)
            socketio.emit("stats", payload)

    except Exception as e:
        print(f"[ERROR] Failed to parse message: {e}")

def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT)
    client.loop_forever()

# ── Routes ──
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

# ── Start ──
if __name__ == "__main__":
    init_db()
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()
    print("[*] NodeSentry starting on http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)