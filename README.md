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
      --> Downloads media file from S3
      --> Extracts audio from video (ffmpeg, 16kHz mono WAV)
      --> Transcribes with faster-whisper (VAD + beam search)
      --> Writes .transcription.json sidecar to S3
      --> Returns structured result with language, segments, timestamps
```

**Idempotency:** Before processing, the function checks if a `.transcription.json` file already exists for the input. If it does, the event is skipped. Safe for event redelivery.

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
