# FFmpeg source availability

The Windows portable archive contains the FFmpeg 7.1 executable supplied by
the installed `imageio-ffmpeg` 0.6.0 package. The binary identifies itself as
the GPLv3-enabled Gyan.dev essentials build.

- FFmpeg source and release archives: <https://ffmpeg.org/download.html#get-sources>
- Binary build provider and source links: <https://www.gyan.dev/ffmpeg/builds/>
- Build configuration and applicable license text: run `ffmpeg.exe -L`

Keivotos invokes this executable as a separate process solely to extract local
video thumbnail frames. Keivotos source code remains available under Apache-2.0.
