"""Tiny local Markdown fixture for the isolated Language browser runner."""
from pathlib import Path


def seed_language(media: Path) -> None:
    media.mkdir()
    (media / "Welcome.md").write_text("# Local note\n", encoding="utf-8")
