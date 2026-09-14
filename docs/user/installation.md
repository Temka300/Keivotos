# Installation

## Portable Windows build

1. Verify the downloaded ZIP against its adjacent `.sha256` file when one is provided.
2. Extract the entire folder to a normal writable location.
3. Run `Keivotos.exe`.

By default data is kept under `%LOCALAPPDATA%\Keivotos`. To keep the data in portable mode, add an empty `portable.txt` beside `Keivotos.exe` then everrything is written to a `data\` subfolder of the portable folder.

## Source build

See [`../build/source.md`](../build/source.md). Both a Git clone and an extracted source archive can start through `run.bat` when uv and Node.js are available.

## Portable Linux build

Linux artifacts target x86_64 and require a compatible Linux system. Verify
the ZIP with `sha256sum -c <archive>.zip.sha256`, then extract the complete
folder with `unzip <archive>.zip`. Run `./Keivotos` from the extracted folder.
Keep `gallery-dl`, `ffmpeg`, `_internal`, and the bundled notices together.
If your extractor loses execute permissions, run
`chmod +x Keivotos gallery-dl ffmpeg` first.

An empty `portable.txt` beside the application selects a local `data/` folder.
Saving Danbooru credentials requires an unlocked Secret Service vault in your
Linux desktop session; environment overrides remain available. Build scripts
and their platform requirements are described in
[the portable build instructions](../build/windows.md#linux-target-from-powershell-or-bash).
