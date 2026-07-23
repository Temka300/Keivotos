# Installation

## Portable Windows build

1. Verify the downloaded ZIP against its adjacent `.sha256` file when one is provided.
2. Extract the entire folder to a normal writable location.
3. Run `Keivotos.exe`.

By default data is kept under `%LOCALAPPDATA%\Keivotos`. To keep the data in portable mode, add an empty `portable.txt` beside `Keivotos.exe` then everrything is written to a `data\` subfolder of the portable folder.

## Source build

See [`../build/source.md`](../build/source.md). Both a Git clone and an extracted source archive can start through `run.bat` when uv and Node.js are available.
