from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "client_id": "",
    "authority": "https://login.microsoftonline.com/common",
    "notebook_name": "My Trading Journal 2026",
}


def load_settings(path: Path) -> dict:
    settings = DEFAULTS.copy()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                settings.update({k: v for k, v in stored.items() if k in settings})
        except Exception:
            pass
    return settings


def save_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = DEFAULTS.copy()
    clean.update({k: settings.get(k, clean[k]) for k in clean})
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
