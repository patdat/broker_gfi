import os
import json
import datetime
import tempfile

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


def _save(state):
    folder = os.path.dirname(STATE_PATH) or '.'
    os.makedirs(folder, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as f:
            temp_path = f.name
            json.dump(state, f, indent=2)
        os.replace(temp_path, STATE_PATH)
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)


def set_cursor(key, dt):
    """Persist `dt` (a naive-local datetime) as the cursor for `key`."""
    state = _load()
    state[key] = dt.replace(microsecond=0).isoformat()
    _save(state)


def get_pending_files(key):
    """Saved reports not yet committed to a validated master."""
    return _load().get(key + '_pending', [])


def set_pending_files(key, files):
    state = _load()
    if files:
        state[key + '_pending'] = sorted(set(files))
    else:
        state.pop(key + '_pending', None)
    _save(state)
