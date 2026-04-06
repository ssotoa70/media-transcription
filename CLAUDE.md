# CLAUDE.md

## Project Overview

**media-transcription** is a VAST DataEngine serverless function that performs automatic speech recognition (ASR) on media files uploaded to VAST S3 storage. It uses faster-whisper as its default transcription engine.

## Architecture

This is a **single-file VAST serverless function** following the standard pattern:
- `main.py` — Contains `init()` and `handler()` entry points, ASR abstraction, and all processing logic
- `config.yaml` — Environment variables for deployment
- `requirements.txt` — Python dependencies
- `Aptfile` — System packages (ffmpeg)
- `customDeps` — Custom Python modules (currently unused)
- `cloudevent.yaml` — Test CloudEvent for local development

## Build & Test Commands

```bash
# Build function container
vast functions build media-transcription

# Run locally
vast functions localrun media-transcription -c config.yaml -v

# Test with CloudEvent
vast functions invoke -e cloudevent.yaml -u http://localhost:8080

# Deploy to cluster
vast functions create -n media-transcription --from-file config.yaml

# Update existing deployment
vast functions update media-transcription --from-file config.yaml

# Check status
vast functions get media-transcription -r
```

## Key Design Decisions

- **Single main.py**: VAST DataEngine functions use a single handler file. All ASR logic, helpers, and abstractions live in main.py.
- **faster-whisper default**: Chosen for being open-source, 4-8x faster than original Whisper via CTranslate2, accurate, and works on CPU without GPU.
- **Pluggable ASR**: `ASREngine` base class allows swapping backends via `ASR_ENGINE` env var. Only faster-whisper is implemented initially.
- **Sidecar output**: Transcription JSON is written alongside the original file in S3 (e.g., `video.mp4` -> `video.transcription.json`).
- **No VAST Database writes**: Initial version writes only to S3. VASTDB integration can be added later.

## VAST DataEngine Specifics

- Events arrive as `VastEvent` objects (CloudEvents 1.0 with VAST extensions)
- Element events provide `bucket` and `object_key` via `elementpath` extension
- S3 credentials come from config.yaml env vars, never from events
- `init()` runs once at container start; `handler()` runs per event
- Container resources managed via Knative custom extensions

## Conventions

- **Python 3.11+**, type hints throughout
- **Logging**: Use `ctx.logger` (provided by VAST runtime)
- **No CI/CD in GitHub**: Build and deploy via `vast functions` CLI
- **Conventional commits**: `feat:`, `fix:`, `docs:`
