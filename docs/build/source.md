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

For the populated Danbooru baseline:

```bash
.venv/bin/python tests/run_modularization_browser.py --script danbooru --output /tmp/keivotos-danbooru-browser
```

This mode creates 48 synthetic JPEGs and 24 tags inside the disposable home,
then uses the real backend for thumbnails, discovery, image details and favorites.
It checks the nine-second spotlight advance, selection, independent lane motion,
hover/focus pause and return from detail, decoded grid/detail images, zoom/drag,
favorite reconciliation and navigation to Profile, Collections, Challenge and
Tags. It records browser/API errors and blocks requests outside the scratch
server. It does not verify video/GIF playback, populated artist panels, native
dialogs or Windows behavior. No real-library data or external service is used.

Danbooru's 21 complete view/menu/media components live in
`frontend/src/modules/danbooru/components/`, mounted by `DanbooruSurface.svelte`.
Shared controls and the mixed Settings components remain under
`frontend/src/components/`. Moving a component must preserve its logic, markup
and styles; compare everything except import paths and run the applicable timed
checks before and after the move.

To exercise Backup Settings with the same disposable runner:

```bash
.venv/bin/python tests/run_modularization_browser.py --script backup --output /tmp/keivotos-backup-browser
```

This creates, inspects and restores a real scratch bundle and verifies that cancel
sends no restore request and browser preferences stay separate. It also uses
explicit response fixtures for out-of-order estimates, missing/additional owners
and preserved-checkpoint presentation. No real data or external service is used.

## Frontend store contract

Run the store ownership/persistence checks with Node after installing the existing
frontend development dependencies:

```bash
node tests/frontend_stores.mjs
```

This bundles the actual stores with the existing Vite dependency into temporary
files. It checks compatibility-export identity, single initialization, legacy
storage keys, normalization, derived updates, profile migration/failure rollback,
and that importing Files/suite stores does not initialize Danbooru state. It uses
in-memory browser storage and stubbed profile requests, and removes its temporary
bundles. Keep the timed browser checks for actual interaction/motion coverage.

Store owners are `lib/suiteStores.ts`, `lib/filesStores.ts` and
`modules/danbooru/stores.ts`; persistence primitives and common grid choices live
in `lib/persistedStore.ts` and `lib/gridPreferences.ts`. Existing storage keys are
unchanged. New callers should import their owner directly; `lib/stores.ts` remains
an explicit compatibility export. API ownership is a separate boundary.

## Frontend API contract

```bash
node tests/frontend_api.mjs
```

This uses the existing frontend Vite dependency and a stubbed fetch function; it
never contacts a service. `tests/snapshots/frontend_api.json` records requests and
media URLs captured from the client before its ownership split. The test checks
request methods, URL encoding, payloads, cancellation signals, compatibility
method identity, errors and suite-client isolation. Update the capture only for
an intentional request-contract change. Run the store and browser checks too.

New callers use `modules/danbooru/api.ts` and its `apiTypes.ts` for Danbooru,
`lib/suiteDataApi.ts` and `lib/suiteApiTypes.ts` for shared preservation/settings,
and the existing `lib/filesApi.ts` or `lib/suiteApi.ts` for Files or suite registry/
folder operations. `lib/api.ts` and `lib/apiTypes.ts` remain compatibility exports.
The different existing transport behaviors are intentional compatibility seams.

## Frontend module registration

Each installed frontend owner contributes `modules/<slug>/ui.ts` (a default
`ModuleUiDescriptor`) and `modules/<slug>/surface.ts` (a default Svelte component).
The descriptor slug must match the directory name. Shared registries discover
these files through Vite's eager glob imports, preserving synchronous activation.
Keep surface imports out of `ui.ts`: components consume the action registry, so
importing their constructors there would introduce initialization cycles.

Files supplies the base surface and empty action list. Danbooru owns its Home
activation reset and Profile drawer action. Unknown descriptors keep neutral
icons/actions and unknown surfaces fall back to Files. Backend descriptors still
control enabled/disabled visibility; build-time discovery does not enable modules.
This is bundled contribution discovery, not runtime plugin loading. Settings and
compatibility exports still contain module references; complete frontend absence
is not yet established.

```bash
node tests/frontend_registry.mjs
```

The test copies source into disposable directories and runs real Vite discovery
with installed, physically absent and additional module contributions. Component
constructors are stand-ins to isolate registration from the remaining Settings
imports; real rendering/navigation is covered by the browser suites. Assertions
cover surface identity/fallback, activation resets, Profile action behavior,
Files preserving module state and absent-module store initialization.

## Settings contributions

The shared `AppSettingsModal.svelte` owns the frame, section navigation, search
ranking and timed highlighting. `settings/GeneralSettings.svelte` owns suite
controls; `modules/files/Settings.svelte` owns folder/attachment controls;
`modules/danbooru/Settings.svelte` owns Danbooru preferences and operations.
Danbooru's `LibraryImportSettings.svelte` lives with its module components,
including its read-only use of the shared storage API.

An owner contributes a `settings.ts` default `SettingsContribution` beside its
UI registration. Keep group, section and setting IDs globally unique and stable:
search jumps target the existing `setting-<id>` anchors. The registry discovers
installed contributions; backend enablement filters the navigation groups.
The existing installed-owner search catalog and ranking are preserved, including
its pre-existing search entries for disabled owners. This extraction does not
change that search behavior.

Each open dialog has a `settingsSession` for cross-owner folder refreshes, tool
polling dispatch, busy-state aggregation, overlay dismissal and media restoration.
Keep provider instances mounted across section/search switches so drafts and
polling survive. Nested dialogs use the session portal to retain their former
parent outside the contained scroll pane. The session preserves the final media
resume decision during child teardown and is discarded with the dialog.
Startup choices use enabled backend modules; normalization accepts installed
frontend owner slugs, preserving Files/Danbooru/last and the existing storage key.

```bash
node tests/frontend_settings.mjs
node tests/frontend_registry.mjs
.venv/bin/python tests/run_modularization_browser.py --script settings --output /tmp/keivotos-settings-browser
```

The catalog snapshot captures the 11 sections and 31 search entries before
extraction. Files' folder description now says “a module” instead of hardcoding
Danbooru. Runtime checks cover isolated dialog coordination, installed/absent/
additional contributions and startup normalization. Browser checks cover owner
visibility/order, lazy credential loading and unsaved drafts, preference keys,
search highlighting, folder overlays, task progress across sections, shared busy
controls, Escape and presentation cleanup. Credentials/task/removal-preview
responses and video methods are explicit test fixtures; no vault, real maintenance
job, deletion or actual media playback is exercised by those fixtures.

## Danbooru pipeline ownership

The implementation is `backend/modules/danbooru/pipeline.py`. Keep invoking
`scripts/danbooru_gallery_dl.py` with the existing arguments: that filename is
still the CLI and packaged-helper entry point. Both historical Python imports
(`danbooru_gallery_dl` and `scripts.danbooru_gallery_dl`) resolve to the owner
module itself, preserving function identity, mutable globals and patch seams.
New Python callers should import `modules.danbooru.pipeline` directly.

Source defaults still resolve against the project root, independent of the
current working directory. Frozen defaults resolve against the bundle resource
root. The Windows/Linux freezer specs explicitly include the owner because the
compatibility script is shipped as a data file rather than analyzed as an entry
module. This inclusion is not evidence that a fresh packaged executable ran.

```bash
.venv/bin/python -m pytest tests/test_pipeline_ownership.py tests/test_import_phases.py tests/test_acquisition.py
```

`tests/snapshots/pipeline_cli.json` captures help for all ten commands plus the
root help and two parser errors before the move. Tests compare output/statuses
from another working directory, check helper dispatch and frozen defaults, and
run discover/enrich/finalize against synthetic media and repeat finalization. Existing metadata
lookup tests use fixtures; no live download/backfill is required for this check.

## Danbooru credentials and process helpers

The credential implementation lives in `backend/modules/danbooru/credentials.py`;
`backend/credentials.py` remains an import-compatible alias to the same owner.
Existing saved credential locations, OS vault formats and environment overrides
are unchanged. The module's `helpers.py` owns `--credential-worker` and
`--pipeline`, registered through `backend/module_registry.py`. The launcher keeps
the shared folder-picker helper. Registration itself does not load credentials
or contact the vault; helper invocations preserve their historical arguments
and exit status. These explicit process entry points remain independent of UI
enablement. When the module is absent, its flags are unrecognized.

Run isolated credential and dispatch coverage without using a real vault:

```sh
.venv/bin/python -m pytest tests/test_credential_ownership.py tests/test_credentials.py tests/test_linux_release.py tests/test_pipeline_ownership.py
```

Native DPAPI/Secret Service and fresh frozen-build verification remain separate
platform checks; mocked credential tests do not establish OS vault availability.

## Module delivery requirements

`backend/delivery.py` combines suite requirements with module contributions from
`backend/module_registry.py`. Danbooru declares its pipeline helper, gallery-dl
executable and Linux vault packaging requirements in its own `delivery.py`.
Installed-but-disabled modules remain packaged. Physically absent modules do
not contribute helpers or tool requirements. FFmpeg and the folder picker remain
suite requirements.

The Windows/Linux build specifications and release builders consume this plan.
`app.py --portable-check` verifies declared helpers and, in frozen builds, tool
executables. With Danbooru installed it now also detects a missing pipeline
wrapper. Saved paths and existing command-line interfaces are unchanged.

These checks exercise specifications and simulated frozen layouts without
building or publishing artifacts:

```sh
.venv/bin/python -m pytest tests/test_delivery.py tests/test_source_launcher.py tests/test_linux_release.py tests/test_release_layout.py
```

Passing these checks does not establish a working native packaged artifact or
complete frontend operation with a module physically removed. Native build/smoke
verification remains required before distributing a release.

## Module boundary and Files-only checks

Run the static import boundaries with:

```sh
.venv/bin/python -m pytest tests/test_module_boundaries.py
node tests/frontend_boundaries.mjs
```

The frontend boundary check also runs in the tests workflow. Historical
compatibility barrels are retained for installed-module callers; the application
must use owner APIs directly or the explicit module registration boundaries.

For real application checks with both Danbooru source folders physically absent:

```sh
.venv/bin/python tests/run_modularization_browser.py --script absence --output /tmp/keivotos-absence-check
```

Use a new output directory and the existing runner's Node/Playwright setup.
`PLAYWRIGHT_CHANNEL` can select an installed browser supported by Playwright.
The runner copies sources into scratch space, omits Danbooru there, links existing
frontend dependencies and builds the Files-only UI without changing tracked dist.
It checks real folder registration/scanning, browse/search/reload, stale module
preferences, Settings, missing module endpoints and clean browser/server logs.
After shutdown it verifies absent module storage/tables and preserved fixture
media. It never removes source folders from the checkout or uses the live library.
This is application build/runtime verification, not a native frozen-release check
or type-checking unused compatibility barrels without their owner present.

## Final modularization verification

See [the verification matrix](modularization-verification.md) for the final source
checks, repeatable commands, browser coverage and remaining platform limits.
