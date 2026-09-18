# Data layout

Keivotos separates replaceable application files from writable library state.

```text
%LOCALAPPDATA%/Keivotos/
├── config.json
├── user.sqlite
├── base/
│   └── files.sqlite
├── logs/
├── local_recovery/
│   ├── user_database/
│   ├── preserved_user_database/
│   └── restore_*/
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
- `local_recovery/user_database/` holds the five rotating, verified snapshots of the shared user database, even without Danbooru.
- `local_recovery/preserved_user_database/` holds verified copies of legacy checkpoints. These copies and their originals are excluded from rotation. Namespaces keep differing same-name snapshots separate.
- A module's old `local_recovery/` remains preserved history. New restore rollback copies live under the suite's `local_recovery/restore_*/`, named by component.
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

## Module runtime failures

If Danbooru fails during initialization or a background worker crashes, Files
remains available. Existing data and the saved enabled choice are preserved;
Danbooru operations wait until it is running again. Failure details are recorded
in the runtime log.

The backend exposes `GET /api/suite/modules/danbooru/status` and
`POST /api/suite/modules/danbooru/retry`. Retry waits for old worker cleanup and
reinitializes an enabled module without restarting Keivotos. A running module's
retry does nothing. If the first enable attempt failed, enable it again instead.
These APIs do not yet have a new status or retry control in the interface.

## Backup ownership

The shared user database includes suite settings, Files origin notes and module
user metadata. Files contributes attachment bytes. Danbooru contributes its index,
sidecars, sidecar history and archived artist-profile media. Disabled Danbooru data
remains eligible for backup; disabling it does not clear your backup choices.

If selected optional artifacts are unavailable, the backup response and manifest
report their omission and preserve your selection for future backups. Fresh
Files-only backups do not create Danbooru storage. Original media, thumbnails,
credentials and the disposable Files index remain outside these metadata bundles.
Existing bundle component names and archive paths remain compatible.

### Restoring a bundle

Restore uses the components included in the selected bundle, independently of
your current backup selections. It replaces the whole user database when that
component is included. Unavailable module owners are rejected before replacement.
Previous data is copied and verified in suite recovery before installation, even
when module storage is on another drive. If installation fails, Keivotos attempts
to put the previous data back; a rollback failure reports preserved recovery paths.
Keep these copies until you have checked the restored library. Restart Keivotos
after a successful restore.

Attachment backups read both Files storage layouts. Restore preserves existing
attachment files and verifies missing bytes before creating them. The response
reports missing or failed attachment recovery; these failures do not undo the
metadata restore. Missing attachments are recreated in the managed hidden layout,
which Files can resolve regardless of the current storage-mode setting. Original
media remains outside these bundles.

### What the backup screen covers

Each selectable component shows its owner. Disabled modules retain backup
eligibility; unavailable data is omitted and reported after creation. Files origin
notes require the shared user database; preserving their screenshots/clips also
requires the attachment selection. Inspect a bundle to see its actual included
and omitted components before restoring it. Restoring the user database replaces
all suite, Files and module user data together, as stated in the confirmation.

Grid sizes, motion, sidebar position and other browser preferences remain in the
browser and are not backed up or restored. The sanitized configuration copy inside
a bundle is reference-only; restore does not apply it. Original media, thumbnails,
credentials and the disposable Files index remain excluded. Preserved legacy
checkpoint history appears separately from the rotating current checkpoints.
