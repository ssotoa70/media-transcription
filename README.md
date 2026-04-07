# media-transcription

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ssotoa70/media-transcription/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/downloads/)
[![VAST DataEngine](https://img.shields.io/badge/VAST-DataEngine-blue.svg)](https://www.vastdata.com/)
[![ASR](https://img.shields.io/badge/ASR-faster--whisper-orange.svg)](https://github.com/SYSTRAN/faster-whisper)

**Serverless media transcription for VAST DataEngine.**

media-transcription is a VAST DataEngine function that automatically transcribes audio and video files as they are uploaded to a VAST S3 bucket. It uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2-based OpenAI Whisper) for fast, accurate speech recognition and writes structured JSON transcriptions back to S3 alongside the original files.

---

## How It Works

```
Media file uploaded to S3 bucket
  --> VAST DataEngine ElementCreated trigger (suffix filter)
    --> media-transcription function container
      --> Resolve media path (mount or S3 download)
      --> Extracts audio from video (ffmpeg, 16kHz mono WAV)
      --> Transcribes with faster-whisper (VAD + beam search)
      --> Writes .transcription.json sidecar to S3
      --> Returns structured result with language, segments, timestamps
```

**Idempotency:** Before processing, the function checks if a `.transcription.json` file already exists for the input. If it does, the event is skipped. Safe for event redelivery.

## Media Access Modes

The function supports two ways to access media files, controlled by the `MEDIA_MOUNT_PATH` environment variable:

| Mode | Configuration | Performance | Use Case |
|------|---------------|-------------|----------|
| **Mount (NFS/SMB)** | Set `MEDIA_MOUNT_PATH=/vast/media` | ~0 temp disk (audio) or small WAV (video), zero download latency | Production on VAST clusters |
| **S3 Download** | Leave `MEDIA_MOUNT_PATH` unset | Full file temp disk, network latency | Testing, remote S3, non-VAST systems |

When both are available, the function prefers the mount path. If the mount path is configured but the file isn't found, it automatically falls back to S3 download.

See [Architecture](docs/ARCHITECTURE.md) for the full data flow diagram and [Configuration](docs/CONFIGURATION.md) for mount path resolution details.

## What It Extracts

| Scope | Fields |
|-------|--------|
| **Full text** | Complete transcription as a single string |
| **Segments** | Start/end timestamps, text, avg log probability, no-speech probability |
| **Words** | Per-word start/end timestamps with confidence probability |
| **Language** | Auto-detected ISO 639-1 code with detection probability |
| **Metadata** | Duration, segment count, ASR engine and model used |

## Project Structure

```
main.py              # DataEngine handler (init + handler + ASR abstraction)
config.yaml          # Environment variables for deployment
requirements.txt     # Python dependencies (boto3, faster-whisper)
Aptfile              # System packages (ffmpeg, libsndfile1, libopenblas-dev)
customDeps           # Custom Python modules (currently unused)
cloudevent.yaml      # Test CloudEvent for local development
docs/
  ARCHITECTURE.md    # Handler flow, event model, ASR design
  CONFIGURATION.md   # Environment variables reference
  DEPLOYMENT.md      # Build, deploy, and configure guide
  PERFORMANCE.md     # Model selection, tuning, scaling
  TROUBLESHOOTING.md # Common issues and solutions
```

## Quick Start

```bash
# Clone
git clone https://github.com/ssotoa70/media-transcription.git
cd media-transcription

# Build function container
vast functions build media-transcription

# Run locally
vast functions localrun media-transcription -c config.yaml -v

# Test with CloudEvent (in another terminal)
vast functions invoke -e cloudevent.yaml -u http://localhost:8080

# Deploy to cluster
vast functions create -n media-transcription --from-file config.yaml

# See docs/DEPLOYMENT.md for full deployment guide
```

## Supported Formats

| Type | Extensions |
|------|-----------|
| **Audio** | `.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`, `.aac`, `.wma` |
| **Video** | `.mp4`, `.mkv`, `.webm`, `.mov`, `.avi`, `.mxf`, `.ts` |

Video files are automatically converted to 16kHz mono WAV via ffmpeg before transcription.

## Key Configuration Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `S3_ENDPOINT` | VAST S3 endpoint URL | `https://s3.amazonaws.com` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | S3 credentials | (empty) |
| `MEDIA_MOUNT_PATH` | NFS/SMB mount for direct file access | (empty, use S3) |
| `OUTPUT_BUCKET` | Destination bucket for transcriptions | (same as source) |
| `OUTPUT_PREFIX` | Path prefix for output files | (same path as source) |
| `ASR_MODEL_SIZE` | Whisper model: tiny/base/small/medium/large-v3 | `base` |
| `ASR_DEVICE` | Compute device: cpu/cuda | `cpu` |
| `MAX_FILE_SIZE_MB` | Maximum file size to process | `2048` |

See [Configuration Reference](docs/CONFIGURATION.md) for complete details on all environment variables.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | Event flow, handler design, ASR abstraction |
| [Configuration](docs/CONFIGURATION.md) | Environment variables and secrets reference |
| [Deployment Guide](docs/DEPLOYMENT.md) | Build, push, create function, configure trigger |
| [Performance](docs/PERFORMANCE.md) | Model selection, scaling, optimization |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and solutions |

## Requirements

- **VAST Cluster** 5.4+ with DataEngine enabled
- **vast CLI** with functions support
- **Docker** for building container images
- **Python** 3.11+ (container runtime)
- **S3 bucket** with DataEngine element trigger configured

## License

[MIT](LICENSE)
