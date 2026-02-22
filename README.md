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

## Legacy Docs
See `README.legacy.md` for upstream details (environment variables, Docker, etc.).
