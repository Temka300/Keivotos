"""Build Linux, Windows (through WSL), or both in isolated workspaces."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def run(*args, cwd, env=None):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def copy_sources(root: Path, destination: Path) -> None:
    # Copy only build inputs. In particular never copy config overrides, .venv,
    # node_modules, databases, media, archives, or Git internals.
    for name in ("app.py", "config.json", "pyproject.toml", "uv.lock", "README.md",
                 "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, destination / name)
    for name in ("backend", "scripts", "packaging", "assets", "docs/user", "frontend/src", "frontend/public"):
        shutil.copytree(root / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "build", "dist"))
    for item in (root / "frontend").iterdir():
        if item.is_file() and item.suffix in (".json", ".js", ".ts", ".html"):
            shutil.copy2(item, destination / "frontend" / item.name)
    shutil.copy2(root / ".github/SECURITY.md", destination / "SECURITY.md")
    (destination / ".github").mkdir()
    shutil.copy2(root / ".github/SECURITY.md", destination / ".github/SECURITY.md")


def smoke(stage: Path, home: Path) -> None:
    env = os.environ.copy()
    env["KEIVOTOS_HOME"] = str(home)
    for key in ("DANBOORU_USERNAME", "DANBOORU_API_KEY", "KEIVOTOS_MIGRATE_LEGACY_HOME",
                "KEIVOTOS_DEVELOPER_LAN", "KEIVOTOS_LAN_HOST"):
        env.pop(key, None)
    for tool, flag in (("Keivotos", "--version"), ("Keivotos", "--portable-check"),
                       ("gallery-dl", "--version"), ("ffmpeg", "-version")):
        run(stage / tool, flag, cwd=stage, env=env)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    home.mkdir(parents=True, exist_ok=True)
    with (home / "server.log").open("w+") as log:
        process = subprocess.Popen([str(stage / "Keivotos"), "--no-browser", "--port", str(port)],
                                   cwd=stage, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(f"Portable server exited: {log.read()}")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)
            raise RuntimeError("Portable server did not become ready within 45 seconds")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def archive(stage: Path, destination: Path) -> None:
    # ZipInfo.from_file preserves Unix execute bits for unzip on Linux.
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as output:
        for item in sorted(stage.rglob("*")):
            output.write(item, Path(stage.name) / item.relative_to(stage))


def windows_tools() -> tuple[str, str]:
    converter = shutil.which("wslpath")
    powershell = shutil.which("powershell.exe")
    fallback = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if not powershell and fallback.is_file():
        powershell = str(fallback)
    if not converter or not powershell:
        raise RuntimeError("Windows builds require WSL with Windows PowerShell access; use --target linux on native Linux")
    return converter, powershell


def build_windows(version: str, output: Path, tools: tuple[str, str]) -> None:
    converter, powershell = tools
    def windows_path(path: Path) -> str:
        return subprocess.check_output([converter, "-w", str(path)], text=True).strip()

    # Only selected source inputs cross into Windows; never pass a Linux venv
    # to uv on Windows. JSON keeps paths/version out of PowerShell source code.
    with tempfile.TemporaryDirectory(prefix="keivotos-windows-input-") as temporary:
        work = Path(temporary)
        source = work / "source"
        source.mkdir()
        copy_sources(ROOT, source)
        request = work / "request.json"
        request.write_text(json.dumps({"source": windows_path(source),
                                       "output": windows_path(output), "version": version}))
        run(powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            windows_path(source / "scripts/release/build_windows_from_wsl.ps1"),
            "-RequestFile", windows_path(request), cwd=ROOT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("linux", "windows", "both"), default="linux")
    parser.add_argument("--version", default="")
    parser.add_argument("--output-directory", default="artifacts")
    args = parser.parse_args(argv)
    if sys.platform != "linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        parser.error("Build the Linux x64 artifact on Linux x86_64 (or x64 WSL)")
    version = re.search(r'^VERSION = "([^"]+)"$', (ROOT / "backend/product.py").read_text(), re.M).group(1)
    if args.version and args.version != version:
        parser.error("Requested artifact version does not match product.py version")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}[A-Za-z0-9._-]*", version):
        parser.error("Unsafe product version")
    output = (ROOT / args.output_directory).resolve()
    if output == ROOT or not output.is_relative_to(ROOT):
        parser.error("Output directory must be inside the repository")
    native_tools = None
    if args.target in ("windows", "both"):
        try:
            native_tools = windows_tools()
        except RuntimeError as error:
            parser.error(str(error))
        windows_name = f"Keivotos-V{version}-windows-x64.zip"
        if any((output / name).exists() for name in (windows_name, windows_name + ".sha256")):
            parser.error("Windows artifact already exists; choose another --output-directory")
    if args.target == "windows":
        output.mkdir(parents=True, exist_ok=True)
        build_windows(version, output, native_tools)
        return 0
    for tool in ("uv", "npm", "node"):
        if not shutil.which(tool):
            parser.error(f"Install Linux {tool} and put it on PATH first")
        if Path(shutil.which(tool)).suffix.lower() in (".exe", ".cmd"):
            parser.error(f"Use Linux {tool}, not the Windows installation")
    name = f"Keivotos-V{version}-linux-x64"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{name}.zip"
    checksum = output / f"{name}.zip.sha256"
    if destination.exists() or checksum.exists():
        parser.error("Artifact already exists; choose another --output-directory")
    with tempfile.TemporaryDirectory(prefix="keivotos-linux-build-") as temporary:
        work = Path(temporary)
        source = work / "repo"
        source.mkdir()
        copy_sources(ROOT, source)
        build_env = os.environ.copy()
        build_env.pop("VIRTUAL_ENV", None)
        build_env["UV_PROJECT_ENVIRONMENT"] = str(source / ".venv")
        run("uv", "sync", "--locked", "--python", "3.11", "--group", "build", cwd=source, env=build_env)
        python = source / ".venv/bin/python"
        for command in (("npm", "ci"), ("npm", "run", "check"), ("npm", "run", "build")):
            run(*command, cwd=source / "frontend")
        run(python, "scripts/release/generate_brand_assets.py", cwd=source)
        dist, build = work / "dist", work / "build"
        run(python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", dist,
            "--workpath", build, "packaging/linux/Keivotos.spec", cwd=source)
        run(python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
            "--name", "gallery-dl", "--distpath", dist, "--workpath", build / "gallery-dl",
            "--specpath", work, "packaging/windows/gallery_dl_entry.py", cwd=source)
        stage = work / name
        shutil.copytree(dist / "Keivotos", stage, symlinks=False)
        shutil.copy2(dist / "gallery-dl", stage / "gallery-dl")
        ffmpeg = subprocess.check_output([str(python), "-c",
                    "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"], cwd=source, text=True).strip()
        shutil.copy2(ffmpeg, stage / "ffmpeg")
        for file in ("README.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"):
            shutil.copy2(source / file, stage / file)
        shutil.copytree(source / "docs/user", stage / "docs/user")
        run(python, "scripts/release/collect_licenses.py", stage / "licenses", "--all-installed", cwd=source)
        ffmpeg_licenses = stage / "licenses/FFmpeg"
        ffmpeg_licenses.mkdir()
        result = subprocess.run([str(stage / "ffmpeg"), "-L"], check=True, capture_output=True, text=True)
        (ffmpeg_licenses / "LICENSE.txt").write_text(result.stdout + result.stderr)
        shutil.copy2(source / "packaging/linux/FFMPEG_SOURCE.md", ffmpeg_licenses)
        smoke(stage, work / "smoke-home")
        archive(stage, destination)
        with destination.open("rb") as stream:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        checksum.write_text(f"{digest}  {destination.name}\n")
    print(f"Portable archive: {destination}")
    if args.target == "both":
        build_windows(version, output, native_tools)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
