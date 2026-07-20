# Running Keivotos from source

## Requirements

- Windows 10 or later
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 or another version accepted by the locked frontend toolchain
- Git only when using a clone; a source ZIP works too

Python itself can be provisioned by uv.

## One-command launch

From the repository root:

```powershell
.\run.bat
```

`run.bat` synchronizes Python 3.11 from `pyproject.toml` and `uv.lock`. If the committed frontend output is unavailable, it installs from `package-lock.json` and builds it. The launcher window uses the Keivotos icon and the `Keivotos - Danbooru` title while keeping setup, runtime, LAN-address, and error output visible. The browser then opens at <http://localhost:52325/>.

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
