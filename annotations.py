from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime


def _load_all(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_annotations(path: Path, trade_id: str) -> list[dict]:
    return list(_load_all(path).get(trade_id, []))


def save_annotations(path: Path, trade_id: str, items: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_all(path)
    if items:
        data[trade_id] = items
    else:
        data.pop(trade_id, None)
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), "items": data}
    # Backward/simple structure: store actual trade mapping at top level, with metadata separately.
    data["__meta__"] = payload["updated_at"]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def annotation_count(path: Path, trade_id: str) -> int:
    return len(load_annotations(path, trade_id))
