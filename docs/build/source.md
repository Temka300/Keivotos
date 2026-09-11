# Running Keivotos from source

## Requirements

- Windows 10 or later, or Linux/WSL (see platform limitations below)
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 or another version accepted by the locked frontend toolchain, only when building the frontend
- Git only when using a clone; a source ZIP works too

Python itself can be provisioned by uv.

## One-command launch

From the repository root:

```text
uv run --locked run.py
```

The same command works in Windows and Linux/WSL terminals. uv prepares Python 3.11 from `pyproject.toml` and the existing `uv.lock`; `--locked` refuses an outdated lockfile instead of changing it. `run.py` installs frontend dependencies from `package-lock.json` and builds only when `frontend/dist/index.html` is missing, then runs the existing `app.py` in the same process. Setup failures stop startup; Ctrl+C stops the server.

Convenience shortcuts call this same launcher:

- Windows: double-click `run.bat`, or run `.\run.bat` in a terminal. Errors remain visible before the window closes; the exit code is preserved. Windows console branding is retained.
- Linux/WSL: run `sh run.sh` (or `./run.sh` when executable).

Arguments pass through unchanged, for example `uv run --locked run.py --no-browser --port 52326` or `sh run.sh --dev`. The default browser address is <http://localhost:52325/>.

## Windows and WSL environments

Use a separate checkout and dependency environment for each operating system. A Windows `.venv` or `frontend/node_modules` must not be reused by Linux, or vice versa. In WSL, install and run Linux uv and Node tools inside the distribution. Keep the WSL checkout in its Linux filesystem; run the Windows shortcut from a Windows checkout.

Startup support does not yet mean complete Linux feature parity: Danbooru's native folder dialog and saved-key encryption remain Windows-specific. Files has an in-app folder-picker fallback. Linux Danbooru credentials can come from environment variables; browser opening and external open/reveal depend on desktop integration. These need separate compatibility work.

Do not point a new WSL run at the Windows application-data directory as a migration shortcut. Existing Windows library paths and sidecar identities need a separately verified migration. A fresh Linux run uses its own application-data defaults.

## Trusted devices on the same network

Source runs can explicitly allow phones, tablets, and other computers on the same private network. The flag is double opt-in: it only exists when the `KEIVOTOS_DEVELOPER_LAN` environment variable is set:

```powershell
$env:KEIVOTOS_DEVELOPER_LAN = "1"
.\run.bat --lan
```

Keivotos continues to open `http://localhost:52325/` on the PC and prints a second address such as `http://192.168.1.25:52325/` for the other devices. Combine it with a custom port when needed:

```powershell
.\run.bat --lan --port 52326
```

The PC and other device must be on the same private network. Windows Firewall may ask whether Python can accept Private-network connections. LAN mode has no login or device-level permission boundary, so every device that can reach the displayed address can use the current Keivotos controls; enable it only on a trusted network and close the process when finished.

`--lan` is source-only. It is absent from packaged `Keivotos.exe` launchers, which remain loopback-only.

## Manual development setup

```powershell
uv sync --locked --python 3.11

Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..

uv run python app.py
```

For separate live-reload processes:

```powershell
uv run python app.py --dev --no-browser
```

```powershell
Set-Location frontend
npm.cmd run dev
```

The backend remains on port 52325. Vite reports its own development URL.

## Checks

```powershell
uv run python -m compileall -q .\backend .\scripts .\app.py
uv run python -m unittest discover -s tests -v

Set-Location frontend
npm.cmd run check
npm.cmd run build
```

Set `KEIVOTOS_HOME` to an empty temporary directory for isolated runtime or CI checks. This redirects all default writable paths without editing `config.json`.
