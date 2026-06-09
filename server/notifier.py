import time
import queue
import threading
import requests
import config

NOTIFY_TYPES = {"evil_twin", "karma", "deauth_flood"}

_cooldowns: dict[str, float] = {}
_deauth_tracker: dict[str, list[float]] = {}
_MAX_DEAUTH_ENTRIES = 256

_notif_queue: queue.Queue = queue.Queue(maxsize=100)

ALERT_COLORS = {
    "deauth_flood": 0xef4444,
    "evil_twin":    0xf59e0b,
    "karma":        0xfb923c,
    "probe":        0x38bdf8,
}

ALERT_ICONS = {
    "deauth_flood": "🔴",
    "evil_twin":    "🟠",
    "karma":        "🟡",
    "probe":        "🔵",
}


def _is_whitelisted(mac: str) -> bool:
    cfg = config.load()
    return mac in cfg.get("whitelist", [])


def _is_on_cooldown(mac: str, cooldown_seconds: int) -> bool:
    last = _cooldowns.get(mac)
    if last is None:
        return False
    return (time.time() - last) < cooldown_seconds


def _set_cooldown(mac: str):
    _cooldowns[mac] = time.time()


def _fmt_rssi(rssi) -> str:
    if rssi is None:
        return "Unknown"
    if rssi >= -55:
        return f"{rssi} dBm (Very Close)"
    if rssi >= -75:
        return f"{rssi} dBm (Medium Range)"
    return f"{rssi} dBm (Distant)"


def _build_telegram_message(alert: dict) -> str:
    alert_type = alert.get("type", "unknown")
    icon       = ALERT_ICONS.get(alert_type, "⚪")
    type_label = alert_type.replace("_", " ").title()
    node       = alert.get("node", "unknown")
    mac        = alert.get("mac", "unknown")
    vendor     = alert.get("vendor")
    ssid       = alert.get("ssid")
    rssi       = alert.get("rssi")
    ts         = alert.get("timestamp", time.time())

    mac_str  = f"{mac} [{vendor}]" if vendor else mac
    time_str = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(ts))

    lines = [
        f"{icon} <b>NodeSentry Alert</b>",
        "",
        f"<b>Type:</b>  {type_label}",
        f"<b>Node:</b>  {node}",
        f"<b>MAC:</b>   <code>{mac_str}</code>",
    ]
    if ssid:
        lines.append(f"<b>SSID:</b>  <code>{ssid}</code>")
    lines.append(f"<b>RSSI:</b>  {_fmt_rssi(rssi)}")
    lines.append(f"<b>Time:</b>  {time_str}")

    return "\n".join(lines)


def _build_discord_embed(alert: dict) -> dict:
    alert_type = alert.get("type", "unknown")
    icon       = ALERT_ICONS.get(alert_type, "⚪")
    type_label = alert_type.replace("_", " ").title()
    node       = alert.get("node", "unknown")
    mac        = alert.get("mac", "unknown")
    vendor     = alert.get("vendor")
    ssid       = alert.get("ssid")
    rssi       = alert.get("rssi")
    ts         = alert.get("timestamp", time.time())

    mac_str = f"{mac} [{vendor}]" if vendor else mac
    color   = ALERT_COLORS.get(alert_type, 0x64748b)

    fields = [
        {"name": "Node",  "value": f"`{node}`",       "inline": True},
        {"name": "Type",  "value": f"`{type_label}`",  "inline": True},
        {"name": "MAC",   "value": f"`{mac_str}`",     "inline": False},
    ]
    if ssid:
        fields.append({"name": "SSID", "value": f"`{ssid}`", "inline": True})
    fields.append({"name": "RSSI", "value": f"`{_fmt_rssi(rssi)}`", "inline": True})

    return {
        "embeds": [{
            "title":     f"{icon} NodeSentry | {type_label} Detected",
            "color":     color,
            "fields":    fields,
            "footer":    {"text": "NodeSentry"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        }]
    }


def _send_telegram(alert: dict, cfg: dict):
    token   = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or not chat_id:
        print("[Notifier] Telegram not configured.")
        return
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    message = _build_telegram_message(alert)
    data    = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=data, timeout=5)
        if resp.status_code == 200:
            print("[Notifier] Telegram alert sent.")
        else:
            print(f"[Notifier] Telegram error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Notifier] Telegram request failed: {e}")


def _send_discord(alert: dict, cfg: dict):
    webhook_url = cfg.get("webhook_url", "")
    if not webhook_url:
        print("[Notifier] Discord not configured.")
        return
    data = _build_discord_embed(alert)
    try:
        resp = requests.post(webhook_url, json=data, timeout=5)
        if resp.status_code in (200, 204):
            print("[Notifier] Discord alert sent.")
        else:
            print(f"[Notifier] Discord error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Notifier] Discord request failed: {e}")


def _notifier_worker():
    while True:
        item = _notif_queue.get()
        if item is None:
            break
        alert, tg, dis = item
        if tg.get("enabled"):
            _send_telegram(alert, tg)
        if dis.get("enabled"):
            _send_discord(alert, dis)
        _notif_queue.task_done()


_worker_thread = threading.Thread(target=_notifier_worker, daemon=True, name="notifier-worker")
_worker_thread.start()


def track_deauth(alert: dict) -> bool:
    cfg    = config.load()
    mac    = alert.get("mac")
    now    = time.time()
    window = cfg["thresholds"]["deauth_window_seconds"]
    limit  = cfg["thresholds"]["deauth_count"]

    if mac not in _deauth_tracker:
        if len(_deauth_tracker) >= _MAX_DEAUTH_ENTRIES:
            oldest = min(_deauth_tracker, key=lambda m: _deauth_tracker[m][-1] if _deauth_tracker[m] else 0)
            del _deauth_tracker[oldest]
        _deauth_tracker[mac] = []

    _deauth_tracker[mac] = [t for t in _deauth_tracker[mac] if now - t < window]
    _deauth_tracker[mac].append(now)

    return len(_deauth_tracker[mac]) >= limit


def process(alert: dict):
    cfg        = config.load()
    alert_type = alert.get("type")
    mac        = alert.get("mac", "")

    if _is_whitelisted(mac):
        return

    notify_type   = alert_type
    should_notify = False

    if alert_type == "deauth":
        if track_deauth(alert):
            notify_type   = "deauth_flood"
            should_notify = True
    elif alert_type in ("evil_twin", "karma"):
        should_notify = True

    if not should_notify:
        return

    cooldown = cfg["thresholds"]["cooldown_seconds"]
    if _is_on_cooldown(mac, cooldown):
        print(f"[Notifier] Skipping {alert_type} for {mac} - on cooldown.")
        return

    _set_cooldown(mac)

    notif_alert = {**alert, "type": notify_type}

    tg  = cfg["notifications"]["telegram"]
    dis = cfg["notifications"]["discord"]

    try:
        _notif_queue.put_nowait((notif_alert, tg, dis))
    except queue.Full:
        print(f"[Notifier] Queue full, dropping notification for {mac}.")


def test_telegram(cfg: dict) -> bool:
    try:
        token   = cfg.get("bot_token", "")
        chat_id = cfg.get("chat_id", "")
        if not token or not chat_id:
            return False
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id":    chat_id,
            "text":       "<b>NodeSentry</b> | Telegram notifications are working.",
            "parse_mode": "HTML"
        }
        resp = requests.post(url, json=data, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def test_discord(cfg: dict) -> bool:
    try:
        webhook_url = cfg.get("webhook_url", "")
        if not webhook_url:
            return False
        data = {
            "embeds": [{
                "title":  "NodeSentry | Discord notifications are working.",
                "color":  0x22c55e,
                "footer": {"text": "NodeSentry"},
            }]
        }
        resp = requests.post(webhook_url, json=data, timeout=5)
        return resp.status_code in (200, 204)
    except Exception:
        return False
