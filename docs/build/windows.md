# Building the Windows portable distribution

Keivotos uses a PyInstaller one-folder build.

## Build

Install uv and Node.js, then run from the repository root:

```powershell
.\scripts\release\build_windows.ps1
```

The version is read from `backend\product.py`. Passing `-Version` is optional and only asserts that it matches.

The script:

1. synchronizes the locked Python environment;
2. installs, checks, and builds the locked frontend;
3. regenerates committed Keivotos brand derivatives;
4. builds `Keivotos.exe` and a separate `gallery-dl.exe`;
5. places a separate `ffmpeg.exe` beside the application;
6. collects project and dependency notices;
7. runs version/resource checks for every executable;
8. starts the staged `Keivotos.exe` with an isolated application-data home and requires a successful loopback HTTP response; and
9. writes a ZIP plus SHA-256 checksum under `artifacts/`.

Build and work directories are cleaned only after the script verifies they are inside this repository. User data under `%LOCALAPPDATA%\Keivotos` is never packaged or used by the build smoke test.

## Redistribution

Keep the complete output folder together, including `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `licenses/`, `gallery-dl.exe`, `ffmpeg.exe`, and the FFmpeg source-availability notice. Review the exact bundled dependency licenses before publishing; this documentation is engineering guidance, not legal advice.

## Linux target from PowerShell or Bash

The existing PowerShell entry point also accepts `-Target linux` or
`-Target both` (default: `windows`). On Windows, Linux builds use the default
WSL distribution, which must have Linux Python 3, uv, Node.js, and npm installed.
PowerShell on Linux supports `-Target linux`; Windows builds require Windows.
Use a separate Windows checkout for Windows or both targets. The script refuses
to replace an existing Linux virtual environment in that checkout.

```powershell
.\scripts\release\build_windows.ps1 -Target linux
.\scripts\release\build_windows.ps1 -Target both
```

On Linux or inside WSL, the equivalent build command is:

```bash
bash scripts/release/build_linux.sh
```

Optional Bash arguments are `--version` and `--output-directory`. The version
must match `backend/product.py`. Output paths must be inside the repository.
Linux builds refuse to overwrite existing archives; choose a new output folder
for another build. Windows retains its existing output replacement behavior.

Linux builds use a temporary source copy and a separate virtual environment,
run the locked frontend checks/build, bundle the app, gallery-dl and FFmpeg,
collect licenses, and require executable checks and an isolated HTTP startup
before writing the ZIP and SHA-256 checksum. Neither host dependencies nor
application data are copied into the build workspace. The ZIP preserves Unix
execute permissions; extract with `unzip` and run `./Keivotos` from its folder.
If an extractor drops permissions, run `chmod +x Keivotos gallery-dl ffmpeg`.

The Linux target is x86_64. Build on the oldest Linux distribution you intend
to support: the executable relies on the host's compatible glibc and desktop
services. Credential saving still needs an unlocked Secret Service vault in
the running user's D-Bus session. WSL build success does not establish support
for every Linux desktop. Native artifact testing is required before release.
