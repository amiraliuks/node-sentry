/*
 * NodeSentry — WeMos D1 Mini Pro (ESP8266) sensor firmware
 *
 * Passively monitors 802.11 management frames and publishes detected attacks
 * to a Mosquitto broker over MQTT.
 *
 * Topics:
 *   nodes/<NODE_ID>/alerts  → {node,type,mac,rssi,timestamp,[ssid,rogue_bssid,legit_bssid,count]}
 *   nodes/<NODE_ID>/stats   → {node,uptime,packets_seen,alerts_sent,free_heap,rssi_to_broker,timestamp}
 *   nodes/<NODE_ID>/status  → {node,status,timestamp}
 *
 * Detection types: deauth, probe, evil_twin, karma
 *
 * The sniffer callback only parses frames and pushes to a ring buffer.
 * All MQTT/JSON/network work happens in loop() to keep the callback fast.
 * JSON is hand-built (no ArduinoJson) so attacker-controlled SSIDs can't
 * corrupt the payload.
 */

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <time.h>
extern "C" {
  #include "user_interface.h"
}

#include "credentials.h"

// Optional: known-good APs you own. The AP this node associates with is
// auto-added at runtime. Leave empty to rely on auto-seeding alone.
struct LegitConfig { const char* ssid; const char* bssid; };
const LegitConfig LEGIT_APS[] = {
  // {"MyHomeWiFi", "A0:B1:C2:D3:E4:F5"},
};

#define ENABLE_PROBE_LOG  1
#define ENABLE_EVIL_TWIN  1
#define ENABLE_KARMA      1  // heuristic; set 0 if noisy in your area

#define DEAUTH_WINDOW_MS          10000UL  // sliding window for the flood counter
#define DEAUTH_THRESHOLD          5        // frames from one source within window => flood
#define DEAUTH_ALERT_COOLDOWN_MS  5000UL   // min gap between deauth alerts per source
#define ALERT_COOLDOWN_MS         60000UL  // per-BSSID cooldown for evil_twin / karma
#define PROBE_COOLDOWN_MS         30000UL  // per-device cooldown for probe logging
#define KARMA_PROBE_WINDOW_MS     30000UL  // probe-response only counts as karma if probed recently
#define STATS_INTERVAL_MS         30000UL
#define UPLOAD_INTERVAL_MS        45000UL  // sniff offline, then reconnect and flush queued events
#define UPLOAD_WINDOW_MS          15000UL
#define START_CHANNEL             1
#define MAX_CHANNEL               13
#define HOP_MS                    400

#define STATUS_LED  1  // blink LED_BUILTIN on each alert (active-low on D1 mini)

// Fixed table sizes — ESP8266 has ~40 KB usable DRAM
#define Q_SIZE              64  // outgoing alert ring, must be power of 2
#define MAX_DEAUTH_SRC      24
#define MAX_LEGIT           12
#define MAX_KARMA_AP        16
#define KARMA_SSIDS_PER_AP   6
#define MAX_RECENT_PROBES   16
#define MAX_COOLDOWN        32

// 802.11 frame layout: frame begins 12 bytes in, after the RxControl block.
// Byte 0 of the raw buffer is the signed RSSI.
#define RXCTRL_LEN       12
#define MGMT_HDR_LEN     24   // FC(2) + dur(2) + addr1/2/3(6 each) + seq(2)
#define BEACON_FIXED_LEN 12   // timestamp(8) + interval(2) + capability(2)
#define MAX_FRAME        112  // sniffer_buf2 captures the first 112 bytes

#define ST_PROBE_REQ   0x04
#define ST_PROBE_RESP  0x05
#define ST_BEACON      0x08
#define ST_DISASSOC    0x0A
#define ST_DEAUTH      0x0C

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

enum AlertType { A_DEAUTH = 0, A_PROBE, A_EVILTWIN, A_KARMA };

static const char* typeName(uint8_t t) {
  switch (t) {
    case A_DEAUTH:   return "deauth";
    case A_PROBE:    return "probe";
    case A_EVILTWIN: return "evil_twin";
    case A_KARMA:    return "karma";
    default:         return "unknown";
  }
}

struct OutAlert {
  uint8_t  type;
  uint8_t  mac[6];
  int8_t   rssi;
  uint16_t count;
  bool     hasSsid, hasRogue, hasLegit;
  uint8_t  rogue[6], legit[6];
  char     ssid[33];
};

struct DeauthEntry { bool used; uint8_t mac[6]; uint32_t windowStart; uint16_t count; };
struct LegitAP     { bool used; char ssid[33]; uint8_t bssid[6]; };
struct KarmaAP     { bool used; uint8_t bssid[6]; uint8_t n; char ssids[KARMA_SSIDS_PER_AP][33]; uint32_t ts; };
struct RecentProbe { bool used; char ssid[33]; uint32_t ts; };
struct Cooldown    { bool used; uint8_t mac[6]; uint8_t type; uint32_t ts; };

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

static OutAlert          queue[Q_SIZE];
static volatile uint16_t qHead = 0, qTail = 0;

static DeauthEntry  deauthTbl[MAX_DEAUTH_SRC];
static LegitAP      legitTbl[MAX_LEGIT];
static KarmaAP      karmaTbl[MAX_KARMA_AP];
static RecentProbe  recentProbes[MAX_RECENT_PROBES];
static Cooldown     cdTbl[MAX_COOLDOWN];

static volatile uint32_t packetsSeen  = 0;
static uint32_t          alertsSent   = 0;
static uint32_t          lastWifiTry  = 0;
static uint32_t          lastMqttTry  = 0;
static bool              promisc      = false;
static uint8_t           curChannel   = START_CHANNEL;
static uint32_t          lastHop      = 0;
static uint32_t          lastUpload   = 0;
static uint32_t          uploadStart  = 0;
static bool              uploadedStats = false;

enum NetState { NET_MONITOR = 0, NET_CONNECTING, NET_UPLOADING };
static NetState netState = NET_MONITOR;

static WiFiClient   espClient;
static PubSubClient mqtt(espClient);
static char TOPIC_ALERTS[48], TOPIC_STATS[48], TOPIC_STATUS[48];
static char LWT_PAYLOAD[96];

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

static inline bool macEqual(const uint8_t* a, const uint8_t* b) {
  for (int i = 0; i < 6; i++) if (a[i] != b[i]) return false;
  return true;
}

static inline void macCopy(uint8_t* d, const uint8_t* s) {
  for (int i = 0; i < 6; i++) d[i] = s[i];
}

static void formatMac(const uint8_t* m, char* out) {
  static const char* hx = "0123456789ABCDEF";
  int p = 0;
  
  for (int i = 0; i < 6; i++) {
    out[p++] = hx[m[i] >> 4];
    out[p++] = hx[m[i] & 0xF];
    if (i < 5) out[p++] = ':';
  }

  out[p] = 0;
}

static bool parseMacStr(const char* s, uint8_t* out) {
  unsigned v[6];
  if (sscanf(s, "%x:%x:%x:%x:%x:%x", &v[0],&v[1],&v[2],&v[3],&v[4],&v[5]) != 6) return false;
  for (int i = 0; i < 6; i++) out[i] = (uint8_t)v[i];
  return true;
}

static uint32_t nowEpoch() {
  time_t t = time(nullptr);
  return (t > 1600000000UL) ? (uint32_t)t : 0;
}

static void jsonEscape(const char* s, char* out, size_t outSz) {
  static const char* hx = "0123456789abcdef";
  size_t o = 0;
  for (size_t i = 0; s[i] && o + 7 < outSz; i++) {
    unsigned char c = (unsigned char)s[i];
    if      (c == '"' || c == '\\')  { out[o++] = '\\'; out[o++] = c; }
    else if (c == '\n')              { out[o++] = '\\'; out[o++] = 'n'; }
    else if (c == '\r')              { out[o++] = '\\'; out[o++] = 'r'; }
    else if (c == '\t')              { out[o++] = '\\'; out[o++] = 't'; }
    else if (c < 0x20 || c >= 0x7F) {
      out[o++] = '\\'; out[o++] = 'u'; out[o++] = '0'; out[o++] = '0';
      out[o++] = hx[c >> 4]; out[o++] = hx[c & 0xF];
    } else {
      out[o++] = c;
    }
  }

  out[o] = 0;
}

static bool extractSSID(const uint8_t* fr, uint16_t frLen, uint16_t start, char* out, size_t outSz) {
  uint16_t i = start;
  while ((uint16_t)(i + 2) <= frLen) {
    uint8_t tag  = fr[i];
    uint8_t tlen = fr[i + 1];
    if ((uint16_t)(i + 2 + tlen) > frLen) break;

    if (tag == 0) {
      uint8_t n = (tlen < outSz) ? tlen : outSz - 1;
      memcpy(out, fr + i + 2, n);
      out[n] = 0;
      return true;
    }

    i += 2 + tlen;
  }

  return false;
}

// ---------------------------------------------------------------------------
// Ring buffer
// ---------------------------------------------------------------------------

static void enqueue(const OutAlert& a) {
  uint16_t next = (uint16_t)((qHead + 1) & (Q_SIZE - 1));
  if (next == qTail) return;
  queue[qHead] = a;
  qHead = next;
}

// ---------------------------------------------------------------------------
// Cooldown table
// ---------------------------------------------------------------------------

static bool passCooldown(const uint8_t* mac, uint8_t type, uint32_t windowMs) {
  uint32_t now = millis();
  int      freeIdx = -1, oldestIdx = 0;
  uint32_t oldestAge = 0;

  for (int i = 0; i < MAX_COOLDOWN; i++) {
    if (cdTbl[i].used && cdTbl[i].type == type && macEqual(cdTbl[i].mac, mac)) {
      if (now - cdTbl[i].ts < windowMs) return false;
      cdTbl[i].ts = now;
      return true;
    }

    if (!cdTbl[i].used && freeIdx < 0) freeIdx = i;
    if (cdTbl[i].used) {
      uint32_t age = now - cdTbl[i].ts;   // wrap-safe LRU: rank by unsigned age
      if (age >= oldestAge) { oldestAge = age; oldestIdx = i; }
    }
  }

  int idx = (freeIdx >= 0) ? freeIdx : oldestIdx;
  cdTbl[idx].used = true;
  cdTbl[idx].type = type;
  macCopy(cdTbl[idx].mac, mac);
  cdTbl[idx].ts = now;
  return true;
}

// ---------------------------------------------------------------------------
// Known-legit AP table
// ---------------------------------------------------------------------------

static void addLegit(const char* ssid, const uint8_t* bssid) {
  if (!ssid || !ssid[0]) return;

  for (int i = 0; i < MAX_LEGIT; i++)
    if (legitTbl[i].used && macEqual(legitTbl[i].bssid, bssid) && strcmp(legitTbl[i].ssid, ssid) == 0) return;

  for (int i = 0; i < MAX_LEGIT; i++) {
    if (!legitTbl[i].used) {
      legitTbl[i].used = true;
      strncpy(legitTbl[i].ssid, ssid, 32);
      legitTbl[i].ssid[32] = 0;
      macCopy(legitTbl[i].bssid, bssid);
      return;
    }
  }
}

// ---------------------------------------------------------------------------
// Karma AP / probe tracking
// ---------------------------------------------------------------------------

static KarmaAP* findKarmaAP(const uint8_t* bssid, bool create) {
  uint32_t now = millis();
  int      freeIdx = -1, oldestIdx = 0;
  uint32_t oldestAge = 0;

  for (int i = 0; i < MAX_KARMA_AP; i++) {
    if (karmaTbl[i].used && macEqual(karmaTbl[i].bssid, bssid)) return &karmaTbl[i];
    if (!karmaTbl[i].used && freeIdx < 0) freeIdx = i;
    if (karmaTbl[i].used) {
      uint32_t age = now - karmaTbl[i].ts;   // wrap-safe LRU
      if (age >= oldestAge) { oldestAge = age; oldestIdx = i; }
    }
  }

  if (!create) return nullptr;

  int idx = (freeIdx >= 0) ? freeIdx : oldestIdx;
  KarmaAP* ap = &karmaTbl[idx];
  ap->used = true;
  ap->n    = 0;
  macCopy(ap->bssid, bssid);
  ap->ts = millis();
  return ap;
}

static bool bssidBeacons(const uint8_t* bssid, const char* ssid) {
  KarmaAP* ap = findKarmaAP(bssid, false);
  if (!ap) return false;
  for (int i = 0; i < ap->n; i++) if (strcmp(ap->ssids[i], ssid) == 0) return true;
  return false;
}

static void learnBeacon(const uint8_t* bssid, const char* ssid) {
  if (!ssid || !ssid[0]) return;

  KarmaAP* ap = findKarmaAP(bssid, true);
  ap->ts = millis();

  for (int i = 0; i < ap->n; i++) if (strcmp(ap->ssids[i], ssid) == 0) return;

  if (ap->n < KARMA_SSIDS_PER_AP) {
    strncpy(ap->ssids[ap->n], ssid, 32);
    ap->ssids[ap->n][32] = 0;
    ap->n++;
  }
}

static void recordProbe(const char* ssid) {
  if (!ssid || !ssid[0]) return;

  uint32_t now = millis();
  int      idx = 0;
  uint32_t oldestAge = 0;
  for (int i = 0; i < MAX_RECENT_PROBES; i++) {
    if (!recentProbes[i].used) { idx = i; break; }
    uint32_t age = now - recentProbes[i].ts;   // wrap-safe LRU
    if (age >= oldestAge) { oldestAge = age; idx = i; }
  }

  recentProbes[idx].used = true;
  strncpy(recentProbes[idx].ssid, ssid, 32);
  recentProbes[idx].ssid[32] = 0;
  recentProbes[idx].ts = millis();
}

static bool ssidRecentlyProbed(const char* ssid) {
  uint32_t now = millis();
  for (int i = 0; i < MAX_RECENT_PROBES; i++) {
    if (recentProbes[i].used
        && now - recentProbes[i].ts < KARMA_PROBE_WINDOW_MS
        && strcmp(recentProbes[i].ssid, ssid) == 0) return true;
  }

  return false;
}

// ---------------------------------------------------------------------------
// Detection handlers
// ---------------------------------------------------------------------------

static void handleDeauth(const uint8_t* src, int8_t rssi) {
  uint32_t     now       = millis();
  DeauthEntry* e         = nullptr;
  int          freeIdx   = -1, oldestIdx = 0;
  uint32_t     oldestAge = 0;

  for (int i = 0; i < MAX_DEAUTH_SRC; i++) {
    if (deauthTbl[i].used && macEqual(deauthTbl[i].mac, src)) { e = &deauthTbl[i]; break; }
    if (!deauthTbl[i].used && freeIdx < 0) freeIdx = i;
    if (deauthTbl[i].used) {
      uint32_t age = now - deauthTbl[i].windowStart;   // wrap-safe LRU
      if (age >= oldestAge) { oldestAge = age; oldestIdx = i; }
    }
  }

  if (!e) {
    int idx = (freeIdx >= 0) ? freeIdx : oldestIdx;
    e = &deauthTbl[idx];
    e->used        = true;
    e->windowStart = now;
    e->count       = 0;
    macCopy(e->mac, src);
  }

  if (now - e->windowStart > DEAUTH_WINDOW_MS) {
    e->windowStart = now;
    e->count       = 0;
  }

  e->count++;

  if (e->count >= DEAUTH_THRESHOLD && passCooldown(src, A_DEAUTH, DEAUTH_ALERT_COOLDOWN_MS)) {
    OutAlert a = {};
    a.type  = A_DEAUTH;
    a.rssi  = rssi;
    a.count = e->count;
    macCopy(a.mac, src);
    enqueue(a);  // sustained floods re-fire each cooldown period
  }
}

static void handleProbe(const uint8_t* src, const char* ssid, int8_t rssi) {
  if (!ssid || !ssid[0]) return;
  recordProbe(ssid);

#if ENABLE_PROBE_LOG
  if (!passCooldown(src, A_PROBE, PROBE_COOLDOWN_MS)) return;

  OutAlert a = {};
  a.type   = A_PROBE;
  a.rssi   = rssi;
  a.hasSsid = true;
  macCopy(a.mac, src);
  strncpy(a.ssid, ssid, 32);
  a.ssid[32] = 0;
  enqueue(a);
#endif
}

#if ENABLE_EVIL_TWIN
static void checkEvilTwin(const uint8_t* bssid, const char* ssid, int8_t rssi) {
  if (!ssid || !ssid[0]) return;

  bool            ssidIsLegit = false, bssidIsKnown = false;
  const uint8_t*  legitBssid  = nullptr;

  for (int i = 0; i < MAX_LEGIT; i++) {
    if (legitTbl[i].used && strcmp(legitTbl[i].ssid, ssid) == 0) {
      ssidIsLegit = true;
      if (!legitBssid) legitBssid = legitTbl[i].bssid;
      if (macEqual(legitTbl[i].bssid, bssid)) { bssidIsKnown = true; break; }
    }
  }

  if (ssidIsLegit && !bssidIsKnown && passCooldown(bssid, A_EVILTWIN, ALERT_COOLDOWN_MS)) {
    OutAlert a = {};
    a.type    = A_EVILTWIN;
    a.rssi    = rssi;
    a.hasSsid = true;
    a.hasRogue = true;
    macCopy(a.mac,  bssid);
    macCopy(a.rogue, bssid);
    strncpy(a.ssid, ssid, 32);
    a.ssid[32] = 0;

    if (legitBssid) {
      a.hasLegit = true;
      macCopy(a.legit, legitBssid);
    }

    enqueue(a);
  }
}
#endif

#if ENABLE_KARMA
static void checkKarma(const uint8_t* bssid, const char* ssid, int8_t rssi) {
  // Flag probe-responses for SSIDs the AP never beaconed — likely a karma/MANA attack.
  if (!ssid || !ssid[0]) return;
  if (bssidBeacons(bssid, ssid)) return;
  if (!ssidRecentlyProbed(ssid)) return;
  if (!passCooldown(bssid, A_KARMA, ALERT_COOLDOWN_MS)) return;

  OutAlert a = {};
  a.type     = A_KARMA;
  a.rssi     = rssi;
  a.hasSsid  = true;
  a.hasRogue = true;
  macCopy(a.mac,   bssid);
  macCopy(a.rogue, bssid);
  strncpy(a.ssid, ssid, 32);
  a.ssid[32] = 0;
  enqueue(a);
}
#endif

// ---------------------------------------------------------------------------
// Sniffer callback
// ---------------------------------------------------------------------------

static void snifferCb(uint8_t* buf, uint16_t len) {
  packetsSeen++;
  if (len < RXCTRL_LEN + MGMT_HDR_LEN) return;

  int8_t          rssi  = (int8_t)buf[0];
  const uint8_t*  fr    = buf + RXCTRL_LEN;
  uint16_t        frLen = len - RXCTRL_LEN;
  if (frLen > MAX_FRAME) frLen = MAX_FRAME;

  uint8_t fc      = fr[0];
  uint8_t ftype   = (fc >> 2) & 0x03;
  if (ftype != 0) return;  // management frames only
  uint8_t subtype = (fc >> 4) & 0x0F;

  const uint8_t* addr2 = fr + 10;  // transmitter
  const uint8_t* addr3 = fr + 16;  // BSSID

  switch (subtype) {
    case ST_DEAUTH:
    case ST_DISASSOC:
      handleDeauth(addr2, rssi);
      break;

    case ST_PROBE_REQ: {
      char ssid[33];
      if (extractSSID(fr, frLen, MGMT_HDR_LEN, ssid, sizeof(ssid)))
        handleProbe(addr2, ssid, rssi);
      break;
    }

    case ST_BEACON: {
      char ssid[33];
      if (extractSSID(fr, frLen, MGMT_HDR_LEN + BEACON_FIXED_LEN, ssid, sizeof(ssid))) {
        learnBeacon(addr3, ssid);
#if ENABLE_EVIL_TWIN
        checkEvilTwin(addr3, ssid, rssi);
#endif
      }
      break;
    }

    case ST_PROBE_RESP: {
      char ssid[33];
      if (extractSSID(fr, frLen, MGMT_HDR_LEN + BEACON_FIXED_LEN, ssid, sizeof(ssid))) {
#if ENABLE_EVIL_TWIN
        checkEvilTwin(addr3, ssid, rssi);
#endif
#if ENABLE_KARMA
        checkKarma(addr3, ssid, rssi);
#endif
      }
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// MQTT publish
// ---------------------------------------------------------------------------

static void publishAlert(const OutAlert& a) {
  char mac[18];
  formatMac(a.mac, mac);

  char body[512];
  int n = snprintf(body, sizeof(body),
    "{\"node\":\"%s\",\"type\":\"%s\",\"mac\":\"%s\",\"rssi\":%d,\"timestamp\":%lu",
    NODE_ID, typeName(a.type), mac, (int)a.rssi, (unsigned long)nowEpoch());
  if (n < 0 || n >= (int)sizeof(body)) return;

  // After every accumulation, bail if the buffer is full: otherwise the next
  // `sizeof(body) - n` would underflow to a huge size_t and snprintf could
  // write out of bounds.
  if (a.hasSsid) {
    char esc[200];
    jsonEscape(a.ssid, esc, sizeof(esc));
    n += snprintf(body + n, sizeof(body) - n, ",\"ssid\":\"%s\"", esc);
    if (n < 0 || n >= (int)sizeof(body)) return;
  }

  if (a.hasRogue) {
    char r[18];
    formatMac(a.rogue, r);
    n += snprintf(body + n, sizeof(body) - n, ",\"rogue_bssid\":\"%s\"", r);
    if (n < 0 || n >= (int)sizeof(body)) return;
  }

  if (a.hasLegit) {
    char l[18];
    formatMac(a.legit, l);
    n += snprintf(body + n, sizeof(body) - n, ",\"legit_bssid\":\"%s\"", l);
    if (n < 0 || n >= (int)sizeof(body)) return;
  }

  if (a.type == A_DEAUTH) {
    n += snprintf(body + n, sizeof(body) - n, ",\"count\":%u", a.count);
  }

  if (n < 0 || n >= (int)sizeof(body) - 2) return;

  body[n++] = '}';
  body[n]   = 0;

  if (mqtt.publish(TOPIC_ALERTS, body)) {
    alertsSent++;
#if STATUS_LED
    digitalWrite(LED_BUILTIN, LOW);
    delay(2);
    digitalWrite(LED_BUILTIN, HIGH);
#endif
    Serial.printf("[ALERT] %s\n", body);
  }
}

static void drainQueue() {
  while (qTail != qHead) {
    if (!mqtt.connected()) return;
    publishAlert(queue[qTail]);
    qTail = (uint16_t)((qTail + 1) & (Q_SIZE - 1));
  }
}

static void publishStats() {
  if (!mqtt.connected()) return;

  char body[256];
  snprintf(body, sizeof(body),
    "{\"node\":\"%s\",\"uptime\":%lu,\"packets_seen\":%lu,\"alerts_sent\":%lu,"
    "\"free_heap\":%lu,\"rssi_to_broker\":%d,\"timestamp\":%lu}",
    NODE_ID,
    (unsigned long)(millis() / 1000),
    (unsigned long)packetsSeen,
    (unsigned long)alertsSent,
    (unsigned long)ESP.getFreeHeap(),
    (int)WiFi.RSSI(),
    (unsigned long)nowEpoch());

  mqtt.publish(TOPIC_STATS, body);
}

// ---------------------------------------------------------------------------
// Network state machine
// ---------------------------------------------------------------------------

static void enableMonitorMode() {
  wifi_promiscuous_enable(0);
  wifi_set_channel(curChannel);
  wifi_set_promiscuous_rx_cb(snifferCb);
  wifi_promiscuous_enable(1);
  promisc = true;
  Serial.printf("[MONITOR] sniffing on channel %d\n", wifi_get_channel());
}

static void seedApLegit() {
  if (WiFi.status() != WL_CONNECTED) return;
  uint8_t* b = WiFi.BSSID();
  if (b) addLegit(WiFi.SSID().c_str(), b);
}

static bool connectMqtt() {
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  String cid = String("nodesentry-") + NODE_ID;
  bool ok = mqtt.connect(cid.c_str(), TOPIC_STATUS, 1, true, LWT_PAYLOAD);

  if (ok) {
    char online[96];
    snprintf(online, sizeof(online),
      "{\"node\":\"%s\",\"status\":\"online\",\"timestamp\":%lu}",
      NODE_ID, (unsigned long)nowEpoch());

    mqtt.publish(TOPIC_STATUS, online, true);
    Serial.println("[MQTT] connected, status=online");
  } else {
    Serial.printf("[MQTT] connect failed, state=%d\n", mqtt.state());
  }

  return ok;
}

static void startMonitor() {
  mqtt.disconnect();
  WiFi.disconnect();
  WiFi.mode(WIFI_STA);
  netState      = NET_MONITOR;
  uploadedStats = false;
  lastUpload    = millis();
  enableMonitorMode();
}

static void beginUpload() {
  if (promisc) {
    wifi_promiscuous_enable(0);
    promisc = false;
  }

  mqtt.disconnect();
  WiFi.disconnect();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uploadStart   = millis();
  lastWifiTry   = uploadStart;
  lastMqttTry   = 0;
  uploadedStats = false;
  netState      = NET_CONNECTING;
  Serial.println("[UPLOAD] connecting WiFi/MQTT...");
}

static void finishUpload() {
  if (mqtt.connected()) mqtt.disconnect();
  Serial.println("[UPLOAD] done, back to sniffing");
  startMonitor();
}

static void hopChannelIfNeeded() {
  uint32_t now = millis();
  if (now - lastHop > HOP_MS) {
    lastHop    = now;
    curChannel = (curChannel % MAX_CHANNEL) + 1;
    wifi_set_channel(curChannel);
  }
}

static void serviceRadio() {
  uint32_t now = millis();

  if (netState == NET_MONITOR) {
    if (!promisc) enableMonitorMode();
    hopChannelIfNeeded();
    if (now - lastUpload > UPLOAD_INTERVAL_MS) beginUpload();
    return;
  }

  if (now - uploadStart > UPLOAD_WINDOW_MS) {
    finishUpload();
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWifiTry > 3000) {
      lastWifiTry = now;
      Serial.println("[WiFi] connecting...");
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }

    return;
  }

  if (!mqtt.connected()) {
    if (now - lastMqttTry > 1000) {
      lastMqttTry = now;

      if (connectMqtt()) {
        seedApLegit();
        netState = NET_UPLOADING;
      }
    }

    return;
  }

  mqtt.loop();
  drainQueue();

  if (!uploadedStats) {
    publishStats();
    uploadedStats = true;
  }

  if (qTail == qHead) finishUpload();
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  Serial.println("\n[*] NodeSentry firmware starting...");

#if STATUS_LED
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // active-low on D1 mini
#endif

  snprintf(TOPIC_ALERTS, sizeof(TOPIC_ALERTS), "nodes/%s/alerts", NODE_ID);
  snprintf(TOPIC_STATS,  sizeof(TOPIC_STATS),  "nodes/%s/stats",  NODE_ID);
  snprintf(TOPIC_STATUS, sizeof(TOPIC_STATUS), "nodes/%s/status", NODE_ID);
  snprintf(LWT_PAYLOAD,  sizeof(LWT_PAYLOAD),
           "{\"node\":\"%s\",\"status\":\"offline\",\"timestamp\":0}", NODE_ID);

  for (unsigned i = 0; i < sizeof(LEGIT_APS) / sizeof(LEGIT_APS[0]); i++) {
    uint8_t b[6];
    if (LEGIT_APS[i].bssid && parseMacStr(LEGIT_APS[i].bssid, b))
      addLegit(LEGIT_APS[i].ssid, b);
  }

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);

  Serial.printf("[*] node=%s broker=%s:%d\n", NODE_ID, MQTT_BROKER, MQTT_PORT);
  startMonitor();
}

void loop() {
  serviceRadio();
  yield();  // feeds the ESP8266 WiFi/TCP stack
}