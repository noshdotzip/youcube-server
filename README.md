# YouCube Server/API

Python server for downloading/converting media, plus WaveStream and API specs.

## Contents
- `src/` YouCube server (WebSocket + download/convert pipeline)
- `services/wavestream/` WaveStream service (audio/image streaming)
- `api/` AsyncAPI documentation

## Quick Start
1. Install FFmpeg 5.1+ and sanjuuni.
2. Install Python dependencies: `pip install -r src/requirements.txt`.
3. Run the server: `python src/youcube.py`.

## Features
- yt-dlp with HLS fallbacks and ffmpeg downloader.
- Optional cookies/proxy support.
- Server-side FPS downsample (requested by client).
- Optional parallel sanjuuni chunking.

## Env Vars
- `YTDLP_COOKIES` path to a cookies file for yt-dlp.
- `YTDLP_PROXY` proxy URL for yt-dlp.
- `SANJUUNI_CHUNK_SECONDS` enable chunking (e.g. `6`).
- `SANJUUNI_WORKERS` concurrent sanjuuni processes.
- `SANJUUNI_AUTO_SCALE` auto-select chunk/workers based on duration.
- `SANJUUNI_MIN_WORKERS` minimum workers when auto-scale is enabled.
- `SANJUUNI_MAX_WORKERS` maximum workers when auto-scale is enabled.
- `SANJUUNI_TARGET_CHUNKS` target chunk count when auto-scale is enabled.
- `SANJUUNI_MIN_CHUNK_SECONDS` minimum chunk size when auto-scale is enabled.
- `SANJUUNI_MAX_CHUNK_SECONDS` maximum chunk size when auto-scale is enabled.
- `SANJUUNI_CHUNK_FPS` force constant FPS when chunking (optional).
- `SANJUUNI_MERGE_SKIP_FIRST_FRAME` drop first frame of each chunk to reduce stutter.
- `DISABLE_OPENCL` set to `true` to disable GPU acceleration.

## Client Docs
https://github.com/noshdotzip/youcube-client#readme

## Legacy Docs
See `README.legacy.md` for upstream details (environment variables, Docker, etc.).
