"""Collect installed dependency license files for a binary distribution."""
from __future__ import annotations

import argparse
import shutil
from importlib import metadata
from pathlib import Path


DISTRIBUTIONS = ("aiosqlite", "fastapi", "gallery-dl", "imageio-ffmpeg", "pillow", "uvicorn")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for name in DISTRIBUTIONS:
        distribution = metadata.distribution(name)
        candidates = [
            Path(distribution.locate_file(item))
            for item in (distribution.files or [])
            if Path(str(item)).name.lower().startswith(("license", "copying", "notice"))
        ]
        files = [path for path in candidates if path.is_file()]
        if not files:
            missing.append(name)
            continue
        target = args.output / f"{name}-{distribution.version}"
        target.mkdir(parents=True, exist_ok=True)
        for source in files:
            shutil.copy2(source, target / source.name)
    if missing:
        raise SystemExit(f"No installed license file found for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
