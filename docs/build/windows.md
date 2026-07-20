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
