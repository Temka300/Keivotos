# Data layout and ownership

Keivotos separates replaceable application files from writable library state.

```text
%LOCALAPPDATA%/Keivotos/
├── config.json
├── logs/
├── modules/danbooru/
│   ├── library/
│   ├── danbooru.sqlite
│   ├── user.sqlite
│   ├── sidecars/
│   ├── thumbnails/
│   ├── artist_profile_archive/
│   ├── local_recovery/
│   └── gallery-dl/
└── backups/danbooru/
```

- `user.sqlite` contains irreplaceable local choices such as favorites, collections, user tags, followed artists, and registered folders.
- `danbooru.sqlite` is the searchable index and can be reconstructed from media and sidecars.
- `sidecars/` stores durable metadata by stable registered-root identity.
- `thumbnails/` is derived cache and can be cleared.
- `gallery-dl/` contains acquisition work files and archives.
- `backups/danbooru/` is the fixed destination for backups you create.
- `logs/danbooru-runtime-YYYY-MM-DD_HH-MM-SS-pPID.log` records startup, mutations, failed reads, background work, warnings, and errors.
- `logs/danbooru-access-YYYY-MM-DD_HH-MM-SS-pPID.log` records every local HTTP method, path, and status. Each stream rolls over at 5 MB with five chunks, and retains its 30 most recent files.

`%LOCALAPPDATA%` means the machine-local location returned by the Windows Known Folder API. Keivotos does not place live SQLite databases in a redirected or roaming Documents folder. Settings shows the exact resolved paths.

On the first normal launch after this layout change, an existing `Documents\Keivotos` tree is copied into a resumable staging directory, every file is verified, and the completed copy is installed under Local AppData. The Documents original is never deleted. Paths inside the copied `config.json` are rebased only when they previously pointed below that legacy suite home.

If `config.json` points at a prior module directory inside `Keivotos\modules`, startup copies and verifies that directory into `modules\danbooru` before rebasing those configured paths. A matching backup directory is copied the same way. The source directories are preserved.

The module directory is itself the default metadata root; there is no extra `metadata/` wrapper. If a legacy test build created that wrapper, startup moves its contents up one level. It never overwrites a different file: a conflict stops startup and leaves both copies for manual review.

External library folders remain in place. Registration stores their path and indexes their content; it does not move the originals. Two roots may have the same final folder name because Keivotos identifies each one with a stable root ID. If a root is moved to another drive, use Settings → Library → Relocate; this updates index/user references while keeping the same sidecar namespace. Keivotos does not move the image files for you.

Manual `backup_<Unix timestamp>.keivotosbk` bundles may contain the selected SQLite databases and sidecar/profile archives. Existing `.whbackup` bundles remain restorable. Neither format contains original media, thumbnails, or the DPAPI credential file.

## Overrides

Settings that need persistence are written to `%LOCALAPPDATA%\Keivotos\config.json`. The repository `config.json` is a default template and is not rewritten at runtime. Developers and CI can set `KEIVOTOS_HOME` to redirect the complete default layout to a temporary location.
