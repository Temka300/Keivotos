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
        "danbooru_host": "danbooru",
    }


HOST_URLS = {
    "danbooru": "https://danbooru.donmai.us",
    "betabooru": "https://betabooru.donmai.us",
}


def get_api_host() -> str:
    from config import _cfg

    value = _cfg.get("danbooru_host")
    return value if isinstance(value, str) and value in HOST_URLS else "danbooru"


def get_api_base_url() -> str:
    return HOST_URLS[get_api_host()]


def set_api_host(host: str) -> str:
    from config import save_config

    if host not in HOST_URLS:
        raise ValueError("Unknown Danbooru host")
    save_config({"danbooru_host": host})
    return host


def get_automation_config() -> dict[str, Any]:
    from config import _cfg, _bounded_int

    return {
        "enabled": bool(_cfg.get("automation_enabled", False)),
        "enabled_at": _cfg.get("automation_enabled_at"),
        "interval_minutes": _bounded_int(_cfg.get("automation_interval_minutes"), 15, 5, 1440),
    }


