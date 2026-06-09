import json
import os
import copy
from threading import Lock

# config.json lives alongside the DB under data/ (see server/database.py) so the
# non-root container can persist it on a directory-backed volume. Overridable via
# NODESENTRY_DATA_DIR.
DATA_DIR    = os.environ.get("NODESENTRY_DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

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
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)
        except json.JSONDecodeError as e:
            print(f"[Config] config.json is corrupt ({e}); falling back to defaults")
            return copy.deepcopy(DEFAULTS)


def save(config: dict) -> bool:
    with _lock:
        try:
            # Atomic write: a crash mid-write must never leave a truncated file.
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_PATH)
            return True
        except Exception as e:
            print(f"[Config] Failed to save: {e}")
            return False


def _merge(defaults: dict, overrides: dict) -> dict:
    result = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result