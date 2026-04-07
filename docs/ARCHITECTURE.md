# Architecture

## Overview

media-transcription is a stateless serverless function that runs on VAST DataEngine. It transcribes audio and video files as they are uploaded to a VAST S3 bucket, writing structured JSON results back to S3.

## Event Flow

```
                    VAST S3 Bucket
                         |
                  [media file uploaded]
                         |
                         v
              DataEngine Element Trigger
         (ElementCreated, suffix: .mp4/.wav/...)
                         |
                    [CloudEvent]
                         |
                         v
            media-transcription container
           +-----------------------------+
           |  init(ctx)                  |
           |    - Create S3 client       |
           |    - Load faster-whisper    |
           |    - Parse config           |
           +-----------------------------+
           |  handler(ctx, event)        |
           |    1. Parse VastEvent       |
           |    2. Extract bucket/key    |
           |    3. Check idempotency     |
           |    4. Resolve media path    |
           |       (mount or S3)         |
           |    5. Extract audio (video) |
           |    6. Transcribe            |
           |    7. Upload JSON result    |
           |    8. Cleanup temp files    |
           +-----------------------------+
                 |              |
                 v              v
           VAST S3         VAST S3
        (download)    (.transcription.json)
```

## Media Access Modes

VAST exposes the same data via S3 **and** NFS/SMB protocols simultaneously. The function supports both:

```
                    ┌─────────────────────────────┐
                    │     VAST Storage Cluster     │
                    │                              │
                    │   ┌───────────────────────┐  │
                    │   │     Media Files        │  │
                    │   └──────┬────────┬────────┘  │
                    │          │        │           │
                    │       S3 API   NFS/SMB        │
                    └──────┬───┘────────┬───────────┘
                           │            │
              ┌────────────┴──┐  ┌──────┴──────────┐
              │  S3 Download  │  │  Mount Path      │
              │  (fallback)   │  │  (preferred)     │
              │               │  │                  │
              │  Downloads to │  │  Direct read     │
              │  temp disk    │  │  Zero copy       │
              │  ~GB of temp  │  │  No temp disk    │
              └───────┬───────┘  └───────┬──────────┘
                      │                  │
                      └────────┬─────────┘
                               │
                        ┌──────┴──────┐
                        │  Transcribe │
                        └─────────────┘
```

| Mode | Env Var | Temp Disk | Bandwidth | Use Case |
|------|---------|-----------|-----------|----------|
| **Mount** | `MEDIA_MOUNT_PATH=/vast/media` | Audio: 0, Video: small WAV only | None (local read) | Production on VAST |
| **S3** | (default) | Full media + WAV | Full file download | Testing, remote S3 |

## Handler Lifecycle

### `init(ctx)` -- Container Startup

Called once when the container starts. Performs three initialization steps:

1. **S3 Client** -- Creates a global `boto3` client from `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` environment variables. Reused for all subsequent requests.

2. **ASR Engine** -- Instantiates the ASR backend (default: faster-whisper) and downloads/loads the model into memory. The model stays resident across invocations.

3. **Configuration** -- Parses `SUPPORTED_EXTENSIONS` and `MAX_FILE_SIZE_MB` into global state.

### `handler(ctx, event)` -- Per-Request Processing

1. **Parse event** -- Receives a `VastEvent` object. For Element triggers, calls `event.as_element_event()` to extract `bucket` and `object_key` from the `elementpath` extension.

2. **Validate extension** -- Checks file suffix against `SUPPORTED_EXTENSIONS`. Non-media files return early with `status: skipped`.

3. **Idempotency check** -- Issues `HEAD` request for `<filename>.transcription.json`. If it already exists, skips processing. Safe for event redelivery.

4. **Resolve media path** -- Checks if `MEDIA_MOUNT_PATH` is configured. If yes and file exists on the filesystem, uses mount access. Otherwise, falls back to S3 download. Validates file size (S3 mode only).

5. **Extract audio** (video files only) -- Runs ffmpeg to convert video to 16kHz mono WAV. Uses `subprocess.run()` with 600s timeout. For mount path access, ffmpeg reads directly from NFS/SMB. For S3 mode, uses the downloaded temp file.

6. **Transcribe** -- Calls `asr_engine.transcribe()` which runs faster-whisper with VAD filtering, beam search, and word-level timestamps. Audio is read from either the mount path or temp disk depending on access mode.

7. **Upload result** -- Writes JSON transcription to S3 as `<original_name>.transcription.json`. Destination bucket and path controlled by `OUTPUT_BUCKET` and `OUTPUT_PREFIX`.

8. **Cleanup** -- `tempfile.TemporaryDirectory()` context manager ensures all temp files are deleted, even on error. For mount path access, this removes only the extracted WAV file (if video). For S3 mode, removes the entire downloaded media file and extracted audio.

## ASR Engine Abstraction

The function uses a pluggable ASR design controlled by the `ASR_ENGINE` environment variable:

```
ASREngine (ABC)
    |
    +-- FasterWhisperEngine (default)
    |       Uses CTranslate2-optimized Whisper
    |       Supports CPU and CUDA
    |       VAD filtering, beam search, word timestamps
    |
    +-- (future: OpenAIWhisperEngine)
    +-- (future: NvidiaNimsEngine)
```

### ASRResult Structure

Every ASR backend returns an `ASRResult` with:

| Field | Type | Description |
|-------|------|-------------|
| `text` | str | Full transcript as single string |
| `segments` | list[dict] | Segment-level data with timestamps |
| `language` | str | Detected ISO 639-1 language code |
| `language_probability` | float | Confidence of language detection |
| `duration` | float | Audio duration in seconds |

Each segment contains:

| Field | Type | Description |
|-------|------|-------------|
| `start` / `end` | float | Timestamps in seconds |
| `text` | str | Segment text |
| `avg_logprob` | float | Average log probability |
| `no_speech_prob` | float | Probability of no speech |
| `words` | list[dict] | Word-level timestamps with probability |

## Transcription Pipelines

The handler selects between two transcription pathways after resolving the media path:

### `_transcribe_from_path()` -- Mount Path Access

When `MEDIA_MOUNT_PATH` is configured and the file exists on the filesystem:

```
Mount Path (NFS/SMB)
    |
    +-- Audio (wav, mp3, etc.)
    |       |
    |       v
    |   Transcribe directly
    |       |
    |       v
    |   Result (zero temp disk)
    |
    +-- Video (mp4, mkv, etc.)
            |
            v
        ffmpeg reads from mount
            |
            v
        Extract to temp WAV
            |
            v
        Transcribe temp audio
            |
            v
        Result (small temp disk)
```

Benefits:
- Audio files: Zero ephemeral disk
- Video files: Only temp disk for extracted WAV, not entire video
- No bandwidth consumed for media download
- Ideal for production on VAST clusters

### `_transcribe_from_s3()` -- S3 Download

When `MEDIA_MOUNT_PATH` is unset or file not found on mount:

```
S3 Bucket
    |
    v
Download to temp disk
    |
    +-- Audio file
    |       |
    |       v
    |   Transcribe temp audio
    |       |
    |       v
    |   Result (full media disk + config)
    |
    +-- Video file
            |
            v
        ffmpeg reads from temp
            |
            v
        Extract to temp WAV
            |
            v
        Transcribe temp audio
            |
            v
        Result (full media disk + WAV)
```

Benefits:
- Works with any S3 backend (AWS, MinIO, VAST)
- Suitable for testing and remote deployments
- No filesystem mount configuration needed

Disk usage (S3 mode):
- Audio file: ~equal to media size
- Video file: Media size + extracted WAV (~10-20MB per hour)

## Audio Extraction

For video files, ffmpeg extracts audio before transcription:

```
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 -y output.wav
```

| Flag | Purpose |
|------|---------|
| `-vn` | No video stream |
| `-acodec pcm_s16le` | 16-bit PCM WAV (lossless) |
| `-ar 16000` | 16kHz sample rate (Whisper optimal) |
| `-ac 1` | Mono channel |
| `-y` | Overwrite output |

The 600-second timeout accommodates large video files.

## Event Model

VAST DataEngine wraps events in `VastEvent` objects:

```python
# Element events (file operations)
if event.type == "Element":
    element_event = event.as_element_event()
    bucket = element_event.bucket          # From elementpath extension
    key = element_event.object_key         # From elementpath extension

# Fallback for generic events
event_data = event.get_data()
bucket = event_data.get("s3_bucket")
key = event_data.get("s3_key")
```

The `elementpath` extension contains the full S3 path (e.g., `media-assets/uploads/interview.mp4`), which the runtime splits into bucket and key.

## Output Format

The function writes a `.transcription.json` file alongside the original:

```
s3://media-assets/uploads/interview.mp4                    # Input
s3://media-assets/uploads/interview.transcription.json     # Output
```

The JSON includes the full transcript, segment-level timestamps, word-level timestamps with probabilities, language detection, and metadata about the ASR engine used.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Mount path preferred** | VAST multi-protocol access means NFS/SMB mount avoids S3 download entirely. Zero temp disk for audio files. |
| **Single main.py** | VAST DataEngine convention. All logic in one handler file. |
| **faster-whisper default** | 4-8x faster than original Whisper on CPU. Open-source, MIT licensed. |
| **S3 sidecar output** | Transcription lives next to source file. No database dependency for v1. |
| **Idempotency via HEAD** | Cheap check prevents duplicate work on event redelivery. |
| **VAD filter enabled** | Skips silence regions for faster processing without accuracy loss. |
| **16kHz mono WAV** | Whisper's native sample rate. Mono reduces data and processing time. |
| **Global S3 client + model** | Created once in `init()`, reused per-request. Matches VAST best practices. |
| **tempfile.TemporaryDirectory** | Context manager ensures cleanup even on error. |
| **containerConcurrency: 1** | ASR is CPU-intensive. Scale horizontally via Knative instead. |
