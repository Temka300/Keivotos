# Installation

## Portable Windows build

1. Verify the downloaded ZIP against its adjacent `.sha256` file when one is provided.
2. Extract the entire folder to a normal writable location.
3. Run `Keivotos.exe`.

Keivotos opens the Danbooru interface in your default browser. Keep the console open while using the app; closing it stops the local server. Portable builds are PC-only and do not provide the source launcher's optional LAN mode.

The executable folder is replaceable application code. Writable state is kept under `%LOCALAPPDATA%\Keivotos`, so an upgrade should replace the application folder, not the application-data folder. An older `Documents\Keivotos` layout is copied and verified on first normal launch, with the original preserved. Always keep independent backups of irreplaceable user state and original media.

## Source build

See [`../build/source.md`](../build/source.md). Both a Git clone and an extracted source archive can start through `run.bat` when uv and Node.js are available.
