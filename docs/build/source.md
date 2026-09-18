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

Files Add folder and Settings attachment/relocation selection use the native Windows dialog when available, otherwise a shared in-app directory picker. Canceling the native dialog does not open the fallback. The Manage folders picker remains restricted to subfolders of registered roots. Saved keys use Windows DPAPI or Linux Secret Service (setup below). Browser opening and external open/reveal still depend on desktop integration and need separate compatibility work.

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


## Folder-picker browser regression checks (Linux/WSL)

With the frontend built and Node + Playwright/Chromium available externally:

```sh
.venv/bin/python tests/run_directory_picker_browser.py
```

Use `--node /absolute/path/to/node` when Node is not on PATH. If Playwright is
not resolvable normally, set `PLAYWRIGHT_MODULE` to its absolute package
folder; `PLAYWRIGHT_BROWSERS_PATH` can point to an external browser cache.
No Playwright dependency is added to the project. The browser also needs its
usual Linux shared libraries.

The runner creates disposable case-sensitive directories and application data,
starts a loopback server on a free port, and shuts it down afterwards. It checks
actual registration, picker navigation/cancellation/focus, overlapping requests,
attachment drafts, and relocation path forwarding. Native dialog responses and
the relocation mutation are intercepted; the test does not open an OS dialog,
relocate live data, or run Danbooru acquisition. Run on a Linux filesystem that
distinguishes `Upper` and `upper`.

## Saved Danbooru credentials on Linux/WSL

Settings → Danbooru → Account saves API keys through Python keyring's explicit
Secret Service backend. Windows continues to use DPAPI. Linux metadata stores
only the username and an opaque vault reference; the secret stays in the OS
vault. Saving or removing a key preserves the other platform's stored fields.
Credentials remain excluded from backups and are never returned by the API.
Moving metadata between systems does not transfer a usable key; enter it again
on the destination system. Environment variables `DANBOORU_USERNAME` and
`DANBOORU_API_KEY` still override saved values independently.

An unlocked, password-protected Secret Service vault with a default collection
must be available in the same D-Bus session as Keivotos. Many Linux desktops
provide this at login. WSL commonly needs setup. On Ubuntu, install the OS
provider with `sudo apt install gnome-keyring dbus`. Keivotos installs its locked
Python dependency through uv, but does not install or unlock your OS vault.
It never falls back to a plaintext key file or launches unlock prompts from
background jobs. Each vault request has a ten-second timeout.

For a terminal-only WSL session, start a private session shell:

```sh
dbus-run-session -- bash
```

Inside that shell, unlock the keyring, then start Keivotos:

```bash
read -r -s -p 'Keyring password: ' keivotos_vault_password
printf '\n'
printf '%s' "$keivotos_vault_password" | gnome-keyring-daemon --unlock
unset keivotos_vault_password
uv run --locked run.py
```

Use a nonempty keyring password (the existing vault password if one already
exists). The hidden input above avoids putting it in shell history or process
arguments. Repeat the unlock when starting a new session. These steps follow
[keyring's Linux headless guidance](https://keyring.readthedocs.io/en/latest/).

To verify the integration without touching your own vault:

```sh
uv run --locked tests/run_linux_vault_check.py
```

This opt-in test creates its own bus and temporary password-protected keyring,
checks saving, replacement, client and daemon restart, locking, and removal,
then removes only its disposable test files. It makes no Danbooru requests.

The existing disposable browser runner also checks credential Settings with
intercepted responses (it never accesses your OS vault):

```sh
uv run --locked tests/run_directory_picker_browser.py --script credentials
```

It uses the same external Node/Playwright setup described above. It covers
status/save/remove errors, retry, successful input clearing, and confirms that
no connection check is triggered automatically.

## Modularization browser baseline

Before moving frontend ownership, run the timed shell/Settings checks with an
external Node + Playwright + Chromium installation (the same prerequisites as
the folder-picker checks):

```bash
.venv/bin/python tests/run_modularization_browser.py --output /tmp/keivotos-browser-baseline
```

The output directory must not already exist. Supply `--node /absolute/path/to/node`
when needed; `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_BROWSERS_PATH` select an external
Playwright package and browser cache. Missing browser/system dependencies must be
prepared separately; the runner does not install anything.

The runner builds the current frontend into a temporary directory, starts an
isolated loopback backend with a fresh `KEIVOTOS_HOME`, checks that home through
the API, and launches a fresh browser context. It leaves `frontend/dist`, the
live server, and the real library alone. It enables Danbooru only in this scratch
home. Browser requests outside the fixture origin fail the test.

Coverage includes timed drawer entry/exit and dismissal paths; sidebar entry,
closing and rapid reversal without remounting; grip hide/hover/drag/keyboard and
reload persistence; contained scrolling; independent Files/Danbooru size choices;
disabled/enabled Settings sections; search highlight timing; Settings presentation
cleanup; reduced motion; and Browse/Tags/Home sidebar placement. Saved grip
positions retain the existing one-decimal normalization on reload.

The output contains build/server logs, a screenshot, a Playwright trace and
`report.json` with checks, frame samples, API requests and browser errors. The
runner removes its disposable library and stops its own server after each run.
These checks use an empty library: they do not establish image-detail, playback,
Home image-lane, populated grid, native-dialog or native Windows behavior. Run
those affected interactions separately before and after moving their components.
