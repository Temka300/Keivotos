# Third-party notices

Keivotos source code is licensed under Apache-2.0. It depends on open-source Python and JavaScript packages whose copyrights and licenses remain with their respective authors. The Windows build collects installed runtime license files into `licenses/`; `package-lock.json` and `uv.lock` record the resolved package set used by the build.

## Separately invoked tools

The portable folder keeps the following command-line tools separate from `Keivotos.exe` and invokes them as child processes:

- **gallery-dl 1.32.6** - GPL-2.0-only. Source: <https://github.com/mikf/gallery-dl>. The portable build includes its license.
- **FFmpeg 7.1 Gyan.dev essentials build** - configured with GPLv3 components. Source and build-provider information is included in `licenses/FFmpeg-7.1/FFMPEG_SOURCE.md`; `ffmpeg.exe -L` prints the applicable license and build configuration.

Do not remove license or source-availability material when redistributing a portable archive. Dependency licenses can change between versions; inspect the generated distribution rather than treating this file as legal advice.
