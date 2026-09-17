# Data layout

Keivotos separates replaceable application files from writable library state.

```text
%LOCALAPPDATA%/Keivotos/
├── config.json
├── user.sqlite
├── base/
│   └── files.sqlite
├── logs/
├── modules/danbooru/
│   ├── library/
│   ├── danbooru.sqlite
│   ├── danbooru_credentials.json
│   ├── sidecars/
│   ├── thumbnails/
│   ├── artist_profile_archive/
│   ├── local_recovery/
│   └── gallery-dl/
└── backups/
```

- `user.sqlite` is suite-owned and contains irreplaceable local choices such as favorites, collections, user tags, followed artists, the shared folder registry, sidebar visibility, and enabled modules.
- `base/files.sqlite` is Files' disposable type-agnostic index of names, paths, sizes, timestamps, and lazily requested duplicate hashes.
- `modules/danbooru/danbooru.sqlite` is Danbooru's searchable index and can be reconstructed from media and sidecars.
- `sidecars/` stores durable metadata by stable registered-root identity.
- `thumbnails/` is derived cache and can be cleared.
- `gallery-dl/` contains acquisition work files and archives.
- `backups/` is the fixed suite destination for backups you create.
- `logs/keivotos-runtime-YYYY-MM-DD_HH-MM-SS-pPID.log` records startup, mutations, failed reads, background work, warnings, and errors.
- `logs/keivotos-access-YYYY-MM-DD_HH-MM-SS-pPID.log` records every local HTTP method, path, and status.

`%LOCALAPPDATA%` means the machine-local location returned by the Windows Known Folder API.

If you place `portable.txt` next to the executable. `data\` subfolder will be created to store the data instead of `%LOCALAPPDATA%`. Deleting `portable.txt` restores the `%LOCALAPPDATA%` default and uses the data in Local Appdata.

Using one of the `%LOCALAPPDATA%` and `data\` will not interfere each other and use the data which the program will default to.

Manual `backup_<Unix timestamp>.keivotosbk` bundles may contain the selected SQLite databases and sidecar/profile archives.


## Disabling a module

Disabling Danbooru stops its background workers without deleting its index,
metadata, folder assignments, or saved automation settings. Re-enabling it starts
its workers again without restarting Keivotos. If an import, scan, backup, or
restore is busy, let it finish and retry. Disable waits for running background
thread work to finish before confirming the change.

While Danbooru is disabled, its operations and module-specific folder actions
require re-enabling it. Files can still browse the preserved folders and change
their shared names or visibility. Folder release, forget, relocation and Danbooru
rescan require Danbooru to be enabled. A disable request may ask you to retry
while a module request is still in progress.
