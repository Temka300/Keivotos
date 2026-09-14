# Keivotos

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Keivotos is a local-first library that indexes the files you already own. Instead of opening unrelated folders and applications to find images, videos, music, documents, social-media archives, manga, anime, and other saved content, Keivotos brings them into one searchable interface. Your original files remain in their existing folders and are indexed in place.

## Supported platforms

| Platform | Status |
|---|---|
| Windows | ✅ |
| Linux / macOS | untested, source may run |

## Getting started

### Portable build (Windows)

1. Extract the whole release folder. Don't run the exe from inside the ZIP.
2. Start `Keivotos.exe`.
3. Your browser opens at <http://localhost:52325/>.

If you downloaded a release with a `.sha256` file next to it, you can use it to verify the ZIP.

### From source

Install [uv](https://docs.astral.sh/uv/). Node.js 24 is needed only if the frontend must be built. From the repository root on Windows or Linux/WSL:

```text
uv run --locked run.py
```

Windows also supports double-clicking `run.bat`; Linux/WSL can use `sh run.sh`. The shared launcher sets up the locked Python environment through uv, builds the frontend only when missing, and starts the server. Linux/WSL uses an in-app picker for adding folders, choosing attachment storage, and relocating module folders. Saved keys use Windows DPAPI or an unlocked Linux Secret Service vault; see the setup notes below. Desktop integration still has platform limitations. Manual commands and dev mode are in [docs/build/source.md](docs/build/source.md).

## Features

- [x] Files base: browse/search folders in place, rescan, find duplicates, and assign folder roles
- [x] Danbooru
- [ ] Add 3D model viewer
- [ ] Add Images, pdf other filetypes related formats
- [ ] Add android photos
- [ ] Add Iphone photos
- [ ] Add Midis player
- [ ] Add manga reading
- [ ] Add anime/video playback
- [ ] Add EPUB novel reader
- [ ] Add PDF reader
- [ ] Add Web archive
- [ ] Add Youtube Videos
- [ ] Add Pixiv
- [ ] Add Reddit
- [ ] Add Twitter
- [ ] Add OST, music player


## Where your data lives

By default everything Keivotos writes goes to `%LOCALAPPDATA%\Keivotos`.

To run **portable** — keeping all data next to the executable so the whole
folder can be moved or copied between machines — put an empty file named
`portable.txt` beside `Keivotos.exe`. Data then lives in a `data\` subfolder of
the release folder. Delete `portable.txt` to return to `%LOCALAPPDATA%\Keivotos`
(your existing `data\` folder is left untouched, just unused). A `portable.txt`
that contains a folder path uses that path instead of `data\`.

## Troubleshooting

See [docs/user/troubleshooting.md](docs/user/troubleshooting.md) and [docs/user/installation.md](docs/user/installation.md). Logs are in `%LOCALAPPDATA%\Keivotos\logs`.

## Building and testing

```powershell
uv sync --locked --python 3.11
uv run python -m unittest discover -s tests -v

cd frontend
npm.cmd ci
npm.cmd run check
npm.cmd run build
```

Windows packaging is documented in [docs/build/windows.md](docs/build/windows.md).

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md). Security reports:
[SECURITY.md](.github/SECURITY.md). Questions and support:
[SUPPORT.md](.github/SUPPORT.md).

## License

Apache-2.0 - see [LICENSE](LICENSE). Portable builds bundle gallery-dl and FFmpeg as separate GPL-licensed executables; their license texts ship in the `licenses/` folder of each release, with details in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
