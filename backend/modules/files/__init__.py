"""Descriptor for the always-on Files base."""
from __future__ import annotations

from pathlib import Path

from module_descriptor import ModuleDescriptor


def descriptor(suite_home: Path, version: str) -> ModuleDescriptor:
    home = suite_home / "base"
    return ModuleDescriptor(
        slug="files",
        name="Files",
        home=home,
        database=home / "files.sqlite",
        credentials=None,
        api_prefix="/api/files",
        log_prefix="files",
        user_agent=f"Keivotos/{version} (Files)",
        disableable=False,
        is_base=True,
    )
