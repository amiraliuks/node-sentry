# NodeSentry Firmware (WeMos D1 Mini Pro / ESP8266)

Passive 802.11 monitor for a WeMos D1 Mini Pro. It sniffs management frames,
detects common Wi-Fi attacks at the edge, and publishes only meaningful events
to your Mosquitto broker using the **exact MQTT topics and JSON shape** the
NodeSentry backend already consumes \u2014 so it is a drop-in replacement for
`nodes/mock_node.py` on real hardware.

## What it detects

| `type`       | How |
|--------------|-----|
| `deauth`     | Deauth/disassoc **flood**: per-source sliding-window frame count. Edge-aggregated \u2014 it emits one alert when a source crosses the threshold (with a `count` field), not one per frame, so the broker isn't buried during an attack. |
| `probe`      | A device probing for a specific saved SSID (MAC + SSID + RSSI). Wildcard/broadcast probes are ignored. |
| `evil_twin`  | A **legit SSID advertised from an unexpected BSSID**. The AP this node associates with is trusted automatically; add more in `LEGIT_APS[]`. |
| `karma`      | An AP answering a probe-response for an SSID it never beacons, that a client just probed for. Heuristic / best-effort \u2014 toggle with `ENABLE_KARMA`. |

## Published messages

```
nodes/<NODE_ID>/alerts   {"node","type","mac","rssi","timestamp",[ "ssid","rogue_bssid","legit_bssid","count" ]}
nodes/<NODE_ID>/stats    {"node","uptime","packets_seen","alerts_sent","free_heap","rssi_to_broker","timestamp"}
nodes/<NODE_ID>/status   {"node","status","timestamp"}   (retained "online" on connect; retained "offline" LWT on unexpected drop)
```

Timestamps are real UTC epoch seconds via NTP (`0` until the first sync). `count`
on deauth alerts lands in the server's `extra` JSON column.

## Hardware

- **WeMos D1 Mini Pro** (ESP8266EX) + external SMA/u.FL antenna for range.
- USB cable for flashing.

## Configure

Copy the credentials template and fill it in (`credentials.h` is git-ignored):

```bash
cp credentials.h.example credentials.h
```

```cpp
#define WIFI_SSID    "YOUR_WIFI_SSID"
#define WIFI_PASS    "YOUR_WIFI_PASSWORD"
#define MQTT_BROKER  "192.168.1.100"   // host running Mosquitto
#define MQTT_PORT    1883
#define NODE_ID      "node1"           // unique per node
```

Optionally list networks you own in `LEGIT_APS[]` (SSID + real BSSID) in
[`firmware.ino`](firmware.ino) to widen evil-twin coverage beyond the AP this
node connects to.

## Build & flash

**PlatformIO**
```bash
cd nodes/firmware
pio run -t upload
pio device monitor      # 115200 baud
```

**Arduino IDE**
1. Add the ESP8266 boards URL and install the **ESP8266** package.
2. Install **PubSubClient** (Library Manager).
3. Board: *LOLIN(WEMOS) D1 mini Pro*. Open `firmware.ino`, set config, Upload.

No ArduinoJson needed \u2014 JSON is hand-built and SSIDs are escaped so a hostile
SSID can't corrupt the JSON payload. (This protects payload *integrity* only;
the dashboard separately HTML-escapes these fields when rendering them.)

## Design notes & limitations (read this)

- **Multi-channel, store-and-forward.** The ESP8266 has one radio, so it can't
  sniff and stay connected to the broker at the same time. This firmware sniffs
  in promiscuous mode with WiFi disconnected, hopping channels 1-13, and buffers
  detections in a small in-RAM ring queue. Every ~45 s (`UPLOAD_INTERVAL_MS`) it
  reconnects WiFi+MQTT for a short window (~15 s, `UPLOAD_WINDOW_MS`) to flush the
  queued alerts plus a stats sample, then drops back to sniffing. Trade-offs to
  know:
    - **Alerts are delayed**, not real-time: an event can wait up to one
      sniff/upload cycle (~45 s + connect time) before it reaches the dashboard.
    - **There is a periodic blind window** (~15 s per cycle) while the radio is
      reconnecting and uploading; management frames during that window are missed.
    - Channel dwell is ~400 ms (`HOP_MS`), so a very slow deauth flood on a single
      channel can slip under the per-window threshold.
  Tune `UPLOAD_INTERVAL_MS`, `UPLOAD_WINDOW_MS`, `HOP_MS`, and the channel range
  in `firmware.ino` for your environment.

- **Node online/offline is best-effort.** The retained `online` status is
  republished each upload cycle and the broker publishes the retained `offline`
  LWT only on an *ungraceful* drop. Because the node disconnects gracefully every
  cycle to go sniff, a node that dies during the (longer) sniff phase keeps a
  stale `online` status until you notice it stopped reporting stats.

- **The promiscuous callback stays minimal.** It only parses frames and pushes
  compact records into a lock-free ring buffer; all MQTT/JSON/network work runs
  in `loop()`. Don't add `publish()` or `String` work to the callback.

- **Detection state is in-memory and bounded** (fixed-size tables, oldest entry
  evicted when full). It resets on reboot. Tune table sizes / thresholds in the
  config block for your environment.

- **`evil_twin`/`karma` are heuristics**, not ground truth. Karma especially can
  false-positive in busy RF environments \u2014 set `ENABLE_KARMA 0` if so.

## How it maps to the server

`server/mqtt_client.py` subscribes `nodes/#` and routes by topic substring to
`on_alert` / `on_stats` / `on_status`. This firmware speaks that protocol
directly. One thing to know about the deauth path: the node already aggregates
floods, so it forwards `deauth` events (re-firing per cooldown during a sustained
flood). The server's `notifier.py` then applies its own
`deauth` \u2192 `deauth_flood` escalation. If you'd rather the node label confirmed
floods as `deauth_flood` itself, that's a one-line change in `handleDeauth()` \u2014
tell me and I'll wire it up.

> **Legal:** passive monitor only \u2014 it never transmits deauth/management frames.
> Use exclusively on networks you own or are authorized to monitor.
