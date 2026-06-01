import json
import os
from threading import Lock

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")

_lock = Lock()

DEFAULTS = {
    "notifications": {
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": ""
        },
        "discord": {
            "enabled": False,
            "webhook_url": ""
        }
    },
    "thresholds": {
        "deauth_count": 5,
        "deauth_window_seconds": 60,
        "cooldown_seconds": 300
    },
    "whitelist": []
}


def load() -> dict:
    with _lock:
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            # Merge with defaults so missing keys are always present
            return _merge(DEFAULTS, data)
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULTS.copy()


def save(config: dict) -> bool:
    with _lock:
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"[Config] Failed to save: {e}")
            return False


def _merge(defaults: dict, overrides: dict) -> dict:
    result = defaults.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result