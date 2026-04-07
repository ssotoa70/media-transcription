# Configuration Reference

All configuration is via environment variables, set in `config.yaml` for deployment or the DataEngine pipeline. This reference covers all available options with defaults and usage guidance.

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

## Media Access

| Variable | Description | Default |
|----------|-------------|---------|
| `MEDIA_MOUNT_PATH` | NFS/SMB mount path for direct file access | (empty -- use S3) |

When `MEDIA_MOUNT_PATH` is set, the function reads media files directly from the filesystem mount instead of downloading from S3. This eliminates download time and ephemeral disk usage.

**Path resolution:** The function tries two mappings and uses the first that exists:

| Mount Path | S3 Location | Resolved Path |
|-----------|-------------|---------------|
| `/vast/media` | `s3://assets/uploads/video.mp4` | `/vast/media/assets/uploads/video.mp4` |
| `/vast/media/assets` | `s3://assets/uploads/video.mp4` | `/vast/media/assets/uploads/video.mp4` |

If neither path exists on the filesystem, the function falls back to S3 download automatically.

**Audio files** (wav, mp3, etc.) are passed directly to the ASR engine -- zero temp disk.
**Video files** still need a small temp WAV for the extracted audio track (~16kHz mono, much smaller than the source).

## Processing

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_FILE_SIZE_MB` | Maximum input file size (S3 download mode only) | `2048` |
| `SUPPORTED_EXTENSIONS` | Comma-separated extensions | `.mp4,.mkv,.webm,.mov,.avi,.mxf,.ts,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma` |
| `OUTPUT_BUCKET` | Destination bucket for transcriptions | (same as source) |
| `OUTPUT_PREFIX` | Path prefix for transcription files | (same path as source) |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Batch Processing (Schedule Trigger)

| Variable | Description | Default |
|----------|-------------|---------|
| `SCHEDULE_BUCKET` | S3 bucket to scan on Schedule trigger | (empty -- required for batch mode) |
| `SCHEDULE_PREFIX` | S3 prefix path under SCHEDULE_BUCKET | `pending/` |

When a Schedule trigger fires (cron/timer), the function lists all objects under `s3://SCHEDULE_BUCKET/SCHEDULE_PREFIX` and transcribes any files with supported extensions. Files are processed sequentially within a single pod; with horizontal scaling (multiple pods), multiple batches can run in parallel.

### Output Location Behavior

The output location is controlled by `OUTPUT_BUCKET` and `OUTPUT_PREFIX`:

| `OUTPUT_BUCKET` | `OUTPUT_PREFIX` | Input | Output |
|-----------------|-----------------|-------|--------|
| (empty) | (empty) | `s3://media/uploads/video.mp4` | `s3://media/uploads/video.transcription.json` |
| `transcripts` | (empty) | `s3://media/uploads/video.mp4` | `s3://transcripts/uploads/video.transcription.json` |
| (empty) | `results/2026` | `s3://media/uploads/video.mp4` | `s3://media/results/2026/video.transcription.json` |
| `transcripts` | `results/2026` | `s3://media/uploads/video.mp4` | `s3://transcripts/results/2026/video.transcription.json` |

## config.yaml Format

Minimal configuration (S3 mode):

```yaml
envs:
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
```

Complete configuration (all variables):

```yaml
envs:
  # --- S3 Access ---
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"

  # --- ASR Engine ---
  ASR_ENGINE: "faster-whisper"
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"
  ASR_LANGUAGE: ""
  ASR_BEAM_SIZE: "5"

  # --- Media Access ---
  MEDIA_MOUNT_PATH: ""

  # --- Processing ---
  MAX_FILE_SIZE_MB: "2048"
  SUPPORTED_EXTENSIONS: ".mp4,.mkv,.webm,.mov,.avi,.mxf,.ts,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma"

  # --- Output ---
  OUTPUT_BUCKET: ""
  OUTPUT_PREFIX: ""

  # --- Schedule Trigger (batch processing) ---
  SCHEDULE_BUCKET: ""
  SCHEDULE_PREFIX: "pending/"

  # --- Logging ---
  LOG_LEVEL: "INFO"
```

Use with:

```bash
# Deploy
vast functions create -n media-transcription --from-file config.yaml

# Update existing function
vast functions update media-transcription --from-file config.yaml

# Local test
vast functions localrun media-transcription -c config.yaml -v
```

## Recommended Production Configuration

For a production VAST DataEngine deployment with optimal performance and reliability:

```yaml
envs:
  # --- S3 Access (VAST Data VIP) ---
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"

  # --- Media Access (Use NFS/SMB mount for zero-copy) ---
  MEDIA_MOUNT_PATH: "/vast/media"

  # --- ASR Engine (Balance speed and accuracy) ---
  ASR_ENGINE: "faster-whisper"
  ASR_MODEL_SIZE: "base"         # Fast on CPU, good accuracy
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"       # Fastest CPU precision
  ASR_LANGUAGE: ""               # Auto-detect (or set to "en" if known)
  ASR_BEAM_SIZE: "5"

  # --- Processing ---
  MAX_FILE_SIZE_MB: "4096"       # Accommodate large videos
  SUPPORTED_EXTENSIONS: ".mp4,.mkv,.webm,.mov,.avi,.mxf,.ts,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma"

  # --- Output (Separate bucket for transcriptions) ---
  OUTPUT_BUCKET: "transcriptions"
  OUTPUT_PREFIX: "2026-04"       # Organize by date

  # --- Schedule Trigger (batch processing via cron) ---
  SCHEDULE_BUCKET: "media-ingest"
  SCHEDULE_PREFIX: "pending/"    # Files here get transcribed on schedule

  # --- Logging ---
  LOG_LEVEL: "WARNING"           # Reduce log volume in production
```

Key decisions:
- `MEDIA_MOUNT_PATH` configured: Eliminates S3 download for media files, ~100x reduction in disk I/O
- `base` model: 7x realtime on CPU with good accuracy (8% WER)
- `int8` compute: Fastest CPU inference
- Separate `OUTPUT_BUCKET`: Organizes transcriptions away from media files
- `SCHEDULE_BUCKET`/`SCHEDULE_PREFIX`: Enables cron-based batch processing
- `LOG_LEVEL: WARNING`: Reduces log storage and improves performance

See [Deployment Guide](DEPLOYMENT.md) for mount path configuration and trigger setup on your cluster.

## Trigger Configuration

The function supports three trigger types in DataEngine:

### Element Trigger (Single File Upload)

Watches for new media file uploads to S3. Create per file type:

| Setting | Value |
|---------|-------|
| **Trigger Type** | Element |
| **Event Type** | ElementCreated (ObjectCreated:*) |
| **Source Type** | S3 |
| **Source Bucket** | Your media S3 bucket |
| **Suffix Filter** | `.mp4` (or multiple triggers for each format) |

### Schedule Trigger (Batch Processing)

Runs on a cron schedule to batch-process files. Set `SCHEDULE_BUCKET` and `SCHEDULE_PREFIX`:

| Setting | Value |
|---------|-------|
| **Trigger Type** | Schedule |
| **Event Type** | Schedule.TimerElapsed |
| **Cron Expression** | e.g., `0 */6 * * *` (every 6 hours) |
| **Function Parameter** | `SCHEDULE_BUCKET` (e.g., `media-ingest`) |
| **Function Parameter** | `SCHEDULE_PREFIX` (e.g., `pending/`) |

When triggered, the function lists `s3://SCHEDULE_BUCKET/SCHEDULE_PREFIX` and processes all files with supported extensions.

### Function Trigger (Direct Invocation)

Another function calls this one with explicit file details:

| Setting | Value |
|---------|-------|
| **Trigger Type** | Function |
| **Function Target** | media-transcription |
| **Data Payload** | JSON with `bucket` and `key` fields |

Example calling this function from another DataEngine function:
```python
invoke_result = invoke_function(
    "media-transcription",
    {"bucket": "media-assets", "key": "uploads/interview.mp4"}
)
```

## Credentials Security

- Credentials are loaded **once** during `init()`, never per-request
- Events **never** contain credentials, only file locations
- Credentials in `config.yaml` are encrypted at rest by VAST when deployed
- Use separate read/write credentials in production if possible

