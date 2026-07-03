import json
import os

LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.json")


def _read_all():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write_all(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def append_entry(entry):
    entries = _read_all()
    entries.append(entry)
    _write_all(entries)


def get_log(limit=None):
    entries = _read_all()
    if limit is not None:
        return entries[-limit:]
    return entries


def find_by_content_id(content_id):
    for entry in _read_all():
        if entry.get("content_id") == content_id:
            return entry
    return None


def update_status(content_id, status):
    entries = _read_all()
    updated = False
    for entry in entries:
        if entry.get("content_id") == content_id and "appeal_reasoning" not in entry:
            entry["status"] = status
            updated = True
    if updated:
        _write_all(entries)
    return updated
