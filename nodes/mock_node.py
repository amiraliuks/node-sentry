import paho.mqtt.client as mqtt
import json
import time
import random

# Config
BROKER = "localhost"
PORT = 1883
NODE_ID = "node1"

ALERT_TYPES = ["deauth", "probe", "evil_twin", "karma"]

SAMPLE_MACS = [
    "AA:BB:CC:DD:EE:FF",
    "11:22:33:44:55:66",
    "DE:AD:BE:EF:00:01",
    "CA:FE:BA:BE:00:02",
]

SAMPLE_SSIDS = [
    "HomeNetwork",
    "Telekom_12345",
    "FreeWifi",
    "iPhone of Amir",
    "KSAL_Net",
]

client = mqtt.Client()
client.connect(BROKER, PORT)
client.loop_start()

print(f"[*] Mock node '{NODE_ID}' started, publishing to {BROKER}:{PORT}")

try:
    while True:
        alert_type = random.choice(ALERT_TYPES)
        mac = random.choice(SAMPLE_MACS)
        rssi = random.randint(-85, -30)

        # Build payload based on alert type
        payload = {
            "node": NODE_ID,
            "type": alert_type,
            "mac": mac,
            "rssi": rssi,
            "timestamp": int(time.time()),
        }

        if alert_type == "probe":
            payload["ssid"] = random.choice(SAMPLE_SSIDS)

        if alert_type == "evil_twin":
            payload["ssid"] = random.choice(SAMPLE_SSIDS)
            payload["rogue_bssid"] = mac
            payload["legit_bssid"] = random.choice(SAMPLE_MACS)

        if alert_type == "karma":
            payload["ssid"] = random.choice(SAMPLE_SSIDS)
            payload["rogue_bssid"] = mac

        # Publish alert
        topic = f"nodes/{NODE_ID}/alerts"
        client.publish(topic, json.dumps(payload))
        print(f"[+] Published to {topic}: {payload}")

        # Publish stats every 5 alerts
        if random.randint(1, 5) == 1:
            stats = {
                "node": NODE_ID,
                "uptime": random.randint(100, 10000),
                "packets_seen": random.randint(500, 5000),
                "alerts_sent": random.randint(10, 100),
                "free_heap": random.randint(20000, 40000),
                "rssi_to_broker": random.randint(-70, -30),
            }
            stats_topic = f"nodes/{NODE_ID}/stats"
            client.publish(stats_topic, json.dumps(stats))
            print(f"[*] Published stats to {stats_topic}")

        time.sleep(2)

except KeyboardInterrupt:
    print("\n[!] Stopped.")
    client.loop_stop()
    client.disconnect()