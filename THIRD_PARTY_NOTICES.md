# Third-party notices

Keivotos source code is licensed under Apache-2.0. It depends on open-source Python and JavaScript packages whose copyrights and licenses remain with their respective authors. The Windows build collects installed runtime license files into `licenses/`; `package-lock.json` and `uv.lock` record the resolved package set used by the build.

Every *imported* Python library is permissively licensed so it can be linked into the Apache-2.0 application; GPL tools are used only as separately-invoked subprocesses (below), never imported. Notable imported libraries include Pillow (HPND), FastAPI (MIT), uvicorn (BSD), and **tinytag 2.3.0 (MIT)** — added for embedded audio cover-art extraction. `mutagen` was deliberately not adopted for that purpose because it is GPL-2.0-or-later.

## Linux credential storage

Linux source runs additionally use **keyring 25.7.0 (MIT)** with its explicit
Secret Service backend, **SecretStorage (BSD-3-Clause)**, and **Jeepney (MIT)**.
Their cryptography dependency is dual Apache-2.0/BSD-3-Clause. Exact transitive
versions are recorded in `uv.lock`; these dependencies are Linux-only.
Sources: [keyring](https://github.com/jaraco/keyring),
[SecretStorage](https://github.com/mitya57/secretstorage),
[Jeepney](https://gitlab.com/takluyver/jeepney).
The operating-system Secret Service provider (for example GNOME Keyring) is
installed separately by the user and is not bundled or imported by Keivotos.

## Separately invoked tools

The portable folder keeps the following command-line tools separate from `Keivotos.exe` and invokes them as child processes:

- **gallery-dl 1.32.6** - GPL-2.0-only. Source: <https://github.com/mikf/gallery-dl>. The portable build includes its license.
- **FFmpeg 7.1 Gyan.dev essentials build** - configured with GPLv3 components. Source and build-provider information is included in `licenses/FFmpeg-7.1/FFMPEG_SOURCE.md`; `ffmpeg.exe -L` prints the applicable license and build configuration.

Do not remove license or source-availability material when redistributing a portable archive. Dependency licenses can change between versions; inspect the generated distribution rather than treating this file as legal advice.
