"""Danbooru configuration defaults and watcher settings.

All filesystem resolution remains in config.py; saved keys stay unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def configuration_defaults(home: Path) -> dict[str, Any]:
    return {
        "data_root": str(home / "library"),
        "metadata_dir": str(home),
        "gallery_dl_dir": str(home / "gallery-dl"),
        "automation_enabled": False,
        "automation_enabled_at": None,
        "automation_interval_minutes": 15,
    }


def get_automation_config() -> dict[str, Any]:
    from config import _cfg, _bounded_int

    return {
        "enabled": bool(_cfg.get("automation_enabled", False)),
        "enabled_at": _cfg.get("automation_enabled_at"),
        "interval_minutes": _bounded_int(_cfg.get("automation_interval_minutes"), 15, 5, 1440),
    }


