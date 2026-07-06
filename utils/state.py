import os
import json
import datetime

STATE_PATH = './data/state.json'


def _load():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get_cursor(key):
    """Return the last-processed ReceivedTime for `key` as a naive-local
    datetime, or None if not set."""
    raw = _load().get(key)
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


def set_cursor(key, dt):
    """Persist `dt` (a naive-local datetime) as the cursor for `key`."""
    state = _load()
    state[key] = dt.replace(microsecond=0).isoformat()
    os.makedirs(os.path.dirname(STATE_PATH) or '.', exist_ok=True)
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)
