import re
import json
import paho.mqtt.client as mqtt

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _log_safe(value, limit=300):
    """Strip control chars and truncate untrusted payloads/topics before logging
    so an attacker can't forge log lines via embedded newlines/ANSI escapes."""
    s = _CTRL_RE.sub(" ", str(value))
    return s[:limit] + ("…" if len(s) > limit else "")


class MQTTClient:
    def __init__(self, broker: str, port: int, on_alert, on_stats, on_status=None):
        """
        broker    - MQTT broker host
        port      - MQTT broker port
        on_alert  - callback(payload: dict) called when an alert message arrives
        on_stats  - callback(payload: dict) called when a stats message arrives
        on_status - callback(payload: dict) called when a node status message arrives (LWT)
        """
        self.broker    = broker
        self.port      = port
        self.on_alert  = on_alert
        self.on_stats  = on_stats
        self.on_status = on_status

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"[MQTT] Connected to {self.broker}:{self.port}")
            client.subscribe("nodes/#")
        else:
            print(f"[MQTT] Connection failed (rc={rc})")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print(f"[MQTT] Unexpected disconnect (rc={rc}), will auto-reconnect...")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic   = msg.topic

            if "/alerts" in topic:
                print(f"[MQTT] Alert  → {_log_safe(payload)}")
                self.on_alert(payload)

            elif "/stats" in topic:
                print(f"[MQTT] Stats  → {_log_safe(payload)}")
                self.on_stats(payload)

            elif "/status" in topic:
                print(f"[MQTT] Status → {_log_safe(payload)}")
                if self.on_status:
                    self.on_status(payload)

            else:
                print(f"[MQTT] Unknown topic: {_log_safe(topic)}")

        except json.JSONDecodeError:
            print(f"[MQTT] Bad JSON on topic {_log_safe(msg.topic)}")
        except Exception as e:
            print(f"[MQTT] Error handling message: {e}")

    def connect(self):
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
        except ConnectionRefusedError:
            print(f"[MQTT] Could not connect to broker at {self.broker}:{self.port} - is Mosquitto running?")
            raise
        except Exception as e:
            print(f"[MQTT] Connection error: {e}")
            raise

    def start(self):
        """Connect and start the blocking loop (run in a thread)."""
        self.connect()
        self._client.loop_forever(retry_first_connection=True)

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()
        print("[MQTT] Disconnected.")