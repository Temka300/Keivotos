"""Set the product version in every tracked location with one command.

Usage:  .venv\Scripts\python.exe scripts\release\set_version.py 1.0.0
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def rewrite(path: Path, pattern: str, replacement: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    updated, replaced = re.subn(pattern, replacement, text, count=count, flags=re.MULTILINE)
    if replaced != count:
        raise SystemExit(f"Expected {count} version location(s) in {path}, found {replaced}")
    path.write_text(updated, encoding="utf-8")


def resolve_uv() -> Path:
    candidates: list[str | Path | None] = [shutil.which("uv")]
    candidates.extend(
        (
            Path.home() / ".local" / "bin" / "uv.exe",
            Path.home() / ".cargo" / "bin" / "uv.exe",
        )
    )
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "uv" / "uv.exe")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit("uv was not found on PATH or in the standard per-user install locations")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    version = sys.argv[1].strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)[0-9A-Za-z.+-]*", version)
    if not match:
        print(f"Version must start with X.Y.Z: {version}", file=sys.stderr)
        return 2
    major, minor, patch = (int(part) for part in match.groups())
    uv = resolve_uv()

    # Runtime identity: --version, logs, User-Agent, FastAPI/OpenAPI.
    rewrite(
        ROOT / "backend" / "product.py",
        r'^VERSION = ".*"$',
        f'VERSION = "{version}"',
    )

    # Package metadata must stay PEP 440-valid.
    rewrite(
        ROOT / "pyproject.toml",
        r'^version = ".*"$',
        f'version = "{version}"',
    )

    # Frontend package + lockfile (npm ci verifies they agree; the first two
    # "version" fields in the lock are the root package entries).
    rewrite(
        ROOT / "frontend" / "package.json",
        r'"version": "[^"]*"',
        f'"version": "{version}"',
    )
    rewrite(
        ROOT / "frontend" / "package-lock.json",
        r'"version": "[^"]*"',
        f'"version": "{version}"',
        count=2,
    )

    # Windows executable Properties dialog.
    version_info = ROOT / "packaging" / "windows" / "version_info.txt"
    rewrite(
        version_info,
        r"filevers=\(\d+, \d+, \d+, \d+\)",
        f"filevers=({major}, {minor}, {patch}, 0)",
    )
    rewrite(
        version_info,
        r"prodvers=\(\d+, \d+, \d+, \d+\)",
        f"prodvers=({major}, {minor}, {patch}, 0)",
    )
    rewrite(
        version_info,
        r'StringStruct\("FileVersion", "[^"]*"\)',
        f'StringStruct("FileVersion", "{version}")',
    )
    rewrite(
        version_info,
        r'StringStruct\("ProductVersion", "[^"]*"\)',
        f'StringStruct("ProductVersion", "{version}")',
    )

    # uv sync --locked powers source and release builds, so the Python lock
    # must agree with pyproject.toml before this command can succeed.
    subprocess.run(
        [str(uv), "lock", "--project", str(ROOT)],
        check=True,
    )

    # The committed OpenAPI contract embeds info.version.
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "openapi_snapshot.py")],
        check=True,
    )

    print(
        f"Version set to {version} across product.py, pyproject.toml, "
        "uv.lock, package.json, package-lock.json, version_info.txt, and the OpenAPI snapshot."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
