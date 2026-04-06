# media-transcription

VAST DataEngine serverless function for automatic speech recognition (ASR). Transcribes audio and video files uploaded to VAST S3 storage using [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## How It Works

1. A media file (audio or video) is uploaded to VAST S3 storage
2. VAST DataEngine fires an Element CloudEvent to this function
3. The function downloads the media file, extracts audio if needed (via ffmpeg)
4. Transcribes using faster-whisper (CTranslate2-based OpenAI Whisper)
5. Uploads a `.transcription.json` file alongside the original in S3

## Supported Formats

**Audio**: wav, mp3, flac, ogg, m4a, aac, wma
**Video**: mp4, mkv, webm, mov, avi

## Quick Start

### Build

```bash
vast functions build media-transcription
```

### Local Test

```bash
# Run locally
vast functions localrun media-transcription -c config.yaml -v

# Invoke with test event
vast functions invoke -e cloudevent.yaml -u http://localhost:8080
```

### Deploy to VAST DataEngine

```bash
# First deployment
vast functions create -n media-transcription --from-file config.yaml

# Update
vast functions update media-transcription --from-file config.yaml
```

## Configuration

All configuration is via environment variables in `config.yaml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENDPOINT` | - | VAST S3 endpoint URL |
| `S3_ACCESS_KEY` | - | S3 access key |
| `S3_SECRET_KEY` | - | S3 secret key |
| `ASR_ENGINE` | `faster-whisper` | ASR backend |
| `ASR_MODEL_SIZE` | `base` | Whisper model: tiny, base, small, medium, large-v3 |
| `ASR_DEVICE` | `cpu` | Device: cpu or cuda |
| `ASR_COMPUTE_TYPE` | `int8` | Compute: int8 (CPU), float16 (GPU) |
| `ASR_LANGUAGE` | (auto-detect) | ISO 639-1 language code |
| `ASR_BEAM_SIZE` | `5` | Beam search width |
| `MAX_FILE_SIZE_MB` | `2048` | Max input file size |
| `SUPPORTED_EXTENSIONS` | (all audio/video) | Comma-separated extensions |

### Model Size Guide

| Model | Parameters | CPU Speed | Accuracy | Use Case |
|-------|-----------|-----------|----------|----------|
| `tiny` | 39M | ~10x realtime | Good | Quick testing |
| `base` | 74M | ~7x realtime | Better | **Default - balanced** |
| `small` | 244M | ~3x realtime | Good | Better accuracy |
| `medium` | 769M | ~1x realtime | Very good | High accuracy |
| `large-v3` | 1.5B | ~0.5x realtime | Best | Maximum accuracy |

## Output Format

The transcription JSON includes full text, segment-level timestamps, word-level timestamps with probabilities, language detection, and duration.

```json
{
  "status": "success",
  "source_file": "s3://media-assets/uploads/interview.mp4",
  "asr_engine": "faster-whisper",
  "asr_model": "base",
  "transcription": {
    "text": "Full transcription text...",
    "language": "en",
    "language_probability": 0.98,
    "duration_seconds": 120.5,
    "segment_count": 15,
    "segments": [
      {
        "start": 0.0,
        "end": 4.5,
        "text": "Hello and welcome...",
        "avg_logprob": -0.25,
        "no_speech_prob": 0.01,
        "words": [
          {"start": 0.0, "end": 0.5, "word": "Hello", "probability": 0.99}
        ]
      }
    ]
  }
}
```

## Architecture

```
VAST S3 (media upload)
    |
    v
CloudEvent (Element.ObjectCreated)
    |
    v
media-transcription function
    |-- Download media from S3
    |-- Extract audio (ffmpeg, video only)
    |-- Transcribe (faster-whisper)
    |-- Upload .transcription.json to S3
    v
VAST S3 (transcription result)
```

## Adding ASR Backends

The function supports pluggable ASR engines via the `ASR_ENGINE` env var. To add a new backend:

1. Subclass `ASREngine` in `main.py`
2. Implement `load()` and `transcribe()` methods
3. Register in `create_asr_engine()` factory
4. Add dependencies to `requirements.txt`
