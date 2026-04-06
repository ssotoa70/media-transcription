# Configuration Reference

All configuration is via environment variables, set in `config.yaml` for deployment or the DataEngine pipeline.

## S3 Access

| Variable | Description | Default |
|----------|-------------|---------|
| `S3_ENDPOINT` | VAST S3-compatible endpoint URL | `https://s3.amazonaws.com` |
| `S3_ACCESS_KEY` | S3 access key | (empty) |
| `S3_SECRET_KEY` | S3 secret key | (empty) |

These credentials are used to download media files and upload transcription results. The S3 client is created once in `init()` and reused for all requests.

## ASR Engine

| Variable | Description | Default |
|----------|-------------|---------|
| `ASR_ENGINE` | ASR backend to use | `faster-whisper` |
| `ASR_MODEL_SIZE` | Whisper model size | `base` |
| `ASR_DEVICE` | Compute device | `cpu` |
| `ASR_COMPUTE_TYPE` | Numeric precision | `int8` |
| `ASR_LANGUAGE` | Force language (ISO 639-1) | (auto-detect) |
| `ASR_BEAM_SIZE` | Beam search width | `5` |

### Model Size Options

| Model | Parameters | Disk | Memory | CPU Speed | Accuracy |
|-------|-----------|------|--------|-----------|----------|
| `tiny` | 39M | ~75MB | ~600MB | ~10x realtime | Good |
| `base` | 74M | ~140MB | ~1.2GB | ~7x realtime | **Better (default)** |
| `small` | 244M | ~460MB | ~2GB | ~3x realtime | Good |
| `medium` | 769M | ~1.5GB | ~4GB | ~1x realtime | Very good |
| `large-v3` | 1.5B | ~3GB | ~6GB | ~0.5x realtime | Best |

### Compute Type Options

| Type | Device | Description |
|------|--------|-------------|
| `int8` | CPU | Fastest on CPU (default) |
| `float32` | CPU | Most compatible, slower |
| `float16` | CUDA | Standard GPU precision |
| `int8_float16` | CUDA | Fastest on GPU |

## Processing

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_FILE_SIZE_MB` | Maximum input file size | `2048` |
| `SUPPORTED_EXTENSIONS` | Comma-separated extensions | `.mp4,.mkv,.webm,.mov,.avi,.mxf,.ts,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma` |
| `OUTPUT_MODE` | Output strategy | `s3_sidecar` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## config.yaml Format

```yaml
envs:
  S3_ENDPOINT: "http://172.200.212.1:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"
  ASR_ENGINE: "faster-whisper"
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"
  ASR_LANGUAGE: ""
  ASR_BEAM_SIZE: "5"
  MAX_FILE_SIZE_MB: "2048"
  SUPPORTED_EXTENSIONS: ".mp4,.mkv,.webm,.mov,.avi,.mxf,.ts,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma"
  LOG_LEVEL: "INFO"
```

Use with:

```bash
# Deploy
vast functions create -n media-transcription --from-file config.yaml

# Local test
vast functions localrun media-transcription -c config.yaml -v
```

## Trigger Configuration

The element trigger watches for new media files:

| Setting | Value |
|---------|-------|
| **Trigger Type** | Element |
| **Event Type** | ElementCreated (ObjectCreated:*) |
| **Source Type** | S3 |
| **Source Bucket** | Your media S3 bucket |
| **Suffix Filter** | `.mp4` (or multiple triggers for each format) |

## Credentials Security

- Credentials are loaded **once** during `init()`, never per-request
- Events **never** contain credentials, only file locations
- Credentials in `config.yaml` are encrypted at rest by VAST when deployed
- Use separate read/write credentials in production if possible
