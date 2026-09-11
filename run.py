"""Shared source launcher: uv run --locked run.py [app arguments]."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    frontend = ROOT / "frontend"
    if not (frontend / "dist" / "index.html").is_file():
        npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
        if npm is None:
            print("[ERROR] The frontend is not built and Node.js is unavailable. "
                  "Install Node.js 24, then run the launcher again.", file=sys.stderr)
            return 1
        for command, description in (("ci", "Installing locked frontend dependencies"),
                                     ("run build", "Building the frontend")):
            print(f"[SETUP] {description}...", flush=True)
            try:
                result = subprocess.run([npm, *command.split()], cwd=frontend)
            except OSError as exc:
                print(f"[ERROR] {description} failed: {exc}", file=sys.stderr)
                return 1
            if result.returncode:
                print(f"[ERROR] {description} failed (exit {result.returncode}).", file=sys.stderr)
                return result.returncode

    print("[RUN] Starting Keivotos - Danbooru...", flush=True)
    # Run in this process so Ctrl+C and uvicorn's reload retain their normal
    # behavior, without an extra Python parent waiting on the server.
    previous_argv = sys.argv
    previous_directory = Path.cwd()
    try:
        os.chdir(ROOT)
        sys.argv = [str(ROOT / "app.py"), *arguments]
        runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
    finally:
        sys.argv = previous_argv
        os.chdir(previous_directory)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
