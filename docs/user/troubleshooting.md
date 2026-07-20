# Troubleshooting

## The browser did not open

Open <http://localhost:52325/> manually. If it does not load, read the console for the first error. Another process may already own port 52325; source users can run `python app.py --port 52326` and open that port instead.

Browser preferences and Daily Challenge progress are stored per browser origin. The move from `http://127.0.0.1:8000` to `http://localhost:52325` therefore starts fresh browser-only UI state. It does not move, reset, or delete either SQLite database, sidecars, favorites, collections, registered roots, or images.

## A phone or other device cannot open LAN mode

LAN access exists only in a maintainer checkout through its ignored local launcher:

```powershell
.\run-lan.local.bat
```

Open the private IPv4 URL printed by Keivotos, not `localhost`, on the other device. Confirm both devices are on the same private network and allow Python through Windows Firewall for **Private networks** if Windows prompts. Guest Wi-Fi and access-point isolation can prevent devices from reaching each other. Packaged `Keivotos.exe` builds intentionally remain PC-only.

## A source ZIP does not start

Confirm `uv --version`, `node --version`, and `npm.cmd --version` work in a new terminal, then run `run.bat` from the extracted repository root. Do not run from inside the ZIP viewer.

## Keivotos reports invalid config JSON

Open the exact `config.json` path in the error, correct the reported line and column (trailing commas are not valid JSON), then start Keivotos again. The same diagnostic is written to the dated `%LOCALAPPDATA%\Keivotos\logs\danbooru-runtime-YYYY-MM-DD_HH-MM-SS-pPID.log` even when the normal logger could not start. Keivotos does not overwrite or discard a malformed user configuration automatically because it may contain the only pointers to a custom metadata or library location.

## The UI looks stale after a source update

Rebuild the frontend:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run build
```

Restart the backend and hard-refresh the browser once.

## Portable acquisition or video thumbnails fail

Keep `gallery-dl.exe` and `ffmpeg.exe` beside `Keivotos.exe`. These are separate tools invoked by the application; partial copying of the portable folder breaks those features.

## Where is my data?

Open the exact location shown in Settings → Library. Keivotos asks the Windows Known Folder API for machine-local application data, normally
`C:\Users\<name>\AppData\Local\Keivotos`. See [`data-layout.md`](data-layout.md) before moving, restoring, or backing up any files. Never delete `user.sqlite` as a cache.

## A registered image folder moved or its drive letter changed

Reconnect the drive, then use Settings → Library → the root's menu → **Relocate…** and choose its new folder. Keivotos preserves the stable root ID and sidecars, updates indexed/user references, and runs an incremental scan. It does not move original images.

## Report a problem

Include the Keivotos version, Windows version, exact action, first relevant console error, and whether the issue occurs with an isolated `KEIVOTOS_HOME`. The exact dated runtime and HTTP access log paths are shown in Settings → Library. Use the runtime file for startup, background work, mutations, warnings, and errors; use the access file for request methods, paths, and status codes. Remove personal paths, credentials, API keys, and media before attaching logs.
