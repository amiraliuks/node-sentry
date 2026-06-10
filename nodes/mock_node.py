import paho.mqtt.client as mqtt
import json
import time
import random

BROKER  = "localhost"
PORT    = 1883
NODE_ID = "node1"

ALERT_TYPES = ["deauth", "probe", "evil_twin", "karma"]

SAMPLE_MACS = [
    "AC:BC:32:11:22:33",  # Apple
    "24:0A:C4:44:55:66",  # Espressif
    "B8:27:EB:77:88:99",  # Raspberry Pi
    "F4:7B:5E:AA:BB:CC",  # Samsung
    "28:6E:D4:DD:EE:FF",  # Intel
    "00:50:56:11:22:33",  # VMware
]

SAMPLE_SSIDS = [
    "VALA_4G_WiFi",
    "IPKO_Fiber_Secure",
    "ONE_Albania_Business",
    "Albtelecom_Home_99",
    "Kafe_Net_E_Re",
    "Hotel_Prishtina_Guest",
    "TEB_Bank_Client_WiFi",
    "Aeroporti_Tirana_Free"
]

# LWT payload — broker publishes this automatically if node disconnects unexpectedly
LWT_TOPIC   = f"nodes/{NODE_ID}/status"
LWT_PAYLOAD = json.dumps({"node": NODE_ID, "status": "offline", "timestamp": 0})

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)

# Register LWT before connecting
client.will_set(LWT_TOPIC, LWT_PAYLOAD, qos=1, retain=True)
client.connect(BROKER, PORT)
client.loop_start()

# Publish online status on connect
online_payload = json.dumps({
    "node":      NODE_ID,
    "status":    "online",
    "timestamp": int(time.time()),
})
client.publish(LWT_TOPIC, online_payload, qos=1, retain=True)
print(f"[*] Mock node '{NODE_ID}' started, publishing to {BROKER}:{PORT}")
print(f"[*] LWT registered on {LWT_TOPIC}")

try:
    while True:
        alert_type = random.choice(ALERT_TYPES)
        mac        = random.choice(SAMPLE_MACS)
        rssi       = random.randint(-85, -30)

        payload = {
            "node":      NODE_ID,
            "type":      alert_type,
            "mac":       mac,
            "rssi":      rssi,
            "timestamp": int(time.time()),
        }

        if alert_type == "deauth":
            payload["count"] = random.randint(1, 12)

        if alert_type == "probe":
            payload["ssid"] = random.choice(SAMPLE_SSIDS)

        if alert_type == "evil_twin":
            payload["ssid"]        = random.choice(SAMPLE_SSIDS)
            payload["rogue_bssid"] = mac
            payload["legit_bssid"] = random.choice(SAMPLE_MACS)

        if alert_type == "karma":
            payload["ssid"]        = random.choice(SAMPLE_SSIDS)
            payload["rogue_bssid"] = mac

        topic = f"nodes/{NODE_ID}/alerts"
        client.publish(topic, json.dumps(payload))
        print(f"[+] Published to {topic}: {payload}")

        if random.randint(1, 5) == 1:
            stats = {
                "node":            NODE_ID,
                "uptime":          random.randint(100, 10000),
                "packets_seen":    random.randint(500, 5000),
                "alerts_sent":     random.randint(10, 100),
                "free_heap":       random.randint(20000, 40000),
                "rssi_to_broker":  random.randint(-70, -30),
                "timestamp":       int(time.time()),
            }
            stats_topic = f"nodes/{NODE_ID}/stats"
            client.publish(stats_topic, json.dumps(stats))
            print(f"[*] Published stats to {stats_topic}")

        time.sleep(2)

except KeyboardInterrupt:
    # Publish offline status cleanly on Ctrl+C
    offline_payload = json.dumps({
        "node":      NODE_ID,
        "status":    "offline",
        "timestamp": int(time.time()),
    })
    client.publish(LWT_TOPIC, offline_payload, qos=1, retain=True)
    print(f"\n[*] Published offline status to {LWT_TOPIC}")
    print("[!] Stopped.")
    client.loop_stop()
    client.disconnect()