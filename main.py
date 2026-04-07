"""
media-transcription: VAST DataEngine serverless function for automatic speech recognition.

Receives CloudEvents when media files (audio/video) are uploaded to VAST S3 storage,
transcribes them using faster-whisper (or pluggable ASR backend), and writes the
transcription JSON back to S3 alongside the original file.

VAST DataEngine function contract:
  - init(ctx): One-time initialization when the container starts
  - handler(ctx, event): Called for each incoming CloudEvent
"""

import os
import json
import tempfile
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Global state (initialized once in init(), reused across invocations)
# ---------------------------------------------------------------------------
s3_client = None
asr_engine = None
supported_extensions: set[str] = set()
max_file_size_bytes: int = 0
output_bucket: Optional[str] = None
output_prefix: Optional[str] = None


# ===========================================================================
# ASR Engine Abstraction
# ===========================================================================

class ASRResult:
    """Structured transcription result."""

    __slots__ = ("text", "segments", "language", "language_probability", "duration")

    def __init__(
        self,
        text: str,
        segments: list[dict],
        language: str,
        language_probability: float,
        duration: float,
    ):
        self.text = text
        self.segments = segments
        self.language = language
        self.language_probability = language_probability
        self.duration = duration

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": round(self.language_probability, 4),
            "duration_seconds": round(self.duration, 2),
            "segment_count": len(self.segments),
            "segments": self.segments,
        }


class ASREngine(ABC):
    """Base class for pluggable ASR backends."""

    @abstractmethod
    def load(self, ctx) -> None:
        """Load the model. Called once during init()."""

    @abstractmethod
    def transcribe(self, audio_path: str, ctx, language: Optional[str] = None) -> ASRResult:
        """Transcribe an audio file and return structured result."""


class FasterWhisperEngine(ASREngine):
    """ASR backend using faster-whisper (CTranslate2-based Whisper)."""

    def __init__(self):
        self.model = None

    def load(self, ctx) -> None:
        from faster_whisper import WhisperModel

        model_size = os.environ.get("ASR_MODEL_SIZE", "base")
        device = os.environ.get("ASR_DEVICE", "cpu")
        compute_type = os.environ.get("ASR_COMPUTE_TYPE", "int8")

        ctx.logger.info(f"Loading faster-whisper model: {model_size} (device={device}, compute={compute_type})")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        ctx.logger.info("faster-whisper model loaded successfully")

    def transcribe(self, audio_path: str, ctx, language: Optional[str] = None) -> ASRResult:
        beam_size = int(os.environ.get("ASR_BEAM_SIZE", "5"))

        kwargs: dict = {
            "beam_size": beam_size,
            "word_timestamps": True,
            "vad_filter": True,           # Skip silence for faster processing
            "condition_on_previous_text": False,  # Reduce hallucination
        }
        if language:
            kwargs["language"] = language

        segments_iter, info = self.model.transcribe(audio_path, **kwargs)

        segments = []
        full_text_parts = []

        for seg in segments_iter:
            segment_data = {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "avg_logprob": round(seg.avg_logprob, 4),
                "no_speech_prob": round(seg.no_speech_prob, 4),
            }

            if seg.words:
                segment_data["words"] = [
                    {
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "word": w.word.strip(),
                        "probability": round(w.probability, 4),
                    }
                    for w in seg.words
                ]

            segments.append(segment_data)
            full_text_parts.append(seg.text.strip())

        return ASRResult(
            text=" ".join(full_text_parts),
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
        )


def create_asr_engine() -> ASREngine:
    """Factory: create ASR engine based on ASR_ENGINE env var."""
    engine_name = os.environ.get("ASR_ENGINE", "faster-whisper")

    if engine_name == "faster-whisper":
        return FasterWhisperEngine()

    raise ValueError(
        f"Unsupported ASR_ENGINE: {engine_name}. "
        f"Supported: faster-whisper"
    )


# ===========================================================================
# Audio Extraction
# ===========================================================================

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".mxf", ".ts"}


def extract_audio(input_path: str, output_path: str, ctx) -> None:
    """Extract audio from a video file using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", input_path,
        "-vn",                   # no video
        "-acodec", "pcm_s16le",  # WAV 16-bit PCM
        "-ar", "16000",          # 16kHz (optimal for Whisper)
        "-ac", "1",              # mono
        "-y",                    # overwrite
        output_path,
    ]
    ctx.logger.info(f"Extracting audio: ffmpeg -i {Path(input_path).name} -> {Path(output_path).name}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-500:]}")

    ctx.logger.info("Audio extraction complete")


# ===========================================================================
# VAST DataEngine Function Interface
# ===========================================================================

def init(ctx):
    """One-time initialization when the function container starts."""
    global s3_client, asr_engine, supported_extensions, max_file_size_bytes, output_bucket, output_prefix

    ctx.logger.info("=" * 80)
    ctx.logger.info("INITIALIZING MEDIA-TRANSCRIPTION FUNCTION")
    ctx.logger.info("=" * 80)

    # --- S3 Client ---
    s3_endpoint = os.environ.get("S3_ENDPOINT", "https://s3.amazonaws.com")
    s3_access_key = os.environ.get("S3_ACCESS_KEY", "")
    s3_secret_key = os.environ.get("S3_SECRET_KEY", "")

    ctx.logger.info(f"S3 endpoint: {s3_endpoint}")
    if not s3_access_key or not s3_secret_key:
        ctx.logger.warning("S3 credentials not set - S3 operations will fail")

    s3_client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
    )
    ctx.logger.info("S3 client initialized")

    # --- ASR Engine ---
    asr_engine = create_asr_engine()
    asr_engine.load(ctx)

    # --- Configuration ---
    ext_str = os.environ.get(
        "SUPPORTED_EXTENSIONS",
        ".mp4,.mkv,.webm,.mov,.avi,.wav,.mp3,.flac,.ogg,.m4a,.aac,.wma",
    )
    supported_extensions = {e.strip().lower() for e in ext_str.split(",")}

    max_mb = int(os.environ.get("MAX_FILE_SIZE_MB", "2048"))
    max_file_size_bytes = max_mb * 1024 * 1024

    # --- Output location ---
    output_bucket = os.environ.get("OUTPUT_BUCKET", "") or None
    output_prefix = os.environ.get("OUTPUT_PREFIX", "") or None

    ctx.logger.info(f"Supported extensions: {sorted(supported_extensions)}")
    ctx.logger.info(f"Max file size: {max_mb} MB")
    if output_bucket:
        ctx.logger.info(f"Output bucket: {output_bucket}")
    if output_prefix:
        ctx.logger.info(f"Output prefix: {output_prefix}")
    ctx.logger.info("=" * 80)
    ctx.logger.info("MEDIA-TRANSCRIPTION FUNCTION READY")
    ctx.logger.info("=" * 80)


def handler(ctx, event):
    """
    Process incoming CloudEvent: download media, transcribe, upload result.

    Supports VAST Element events (file upload triggers) and generic events
    with s3_bucket/s3_key in the data payload.

    Returns:
        dict with status, transcription summary, and output location
    """
    ctx.logger.info("-" * 80)
    ctx.logger.info(f"Event ID: {event.id} | Type: {event.type}")

    try:
        # --- Extract file location from event ---
        s3_bucket, s3_key = _get_file_location(ctx, event)
        if not s3_bucket or not s3_key:
            return {"status": "error", "message": "Could not determine file location from event"}

        # --- Check file extension ---
        ext = Path(s3_key).suffix.lower()
        if ext not in supported_extensions:
            ctx.logger.info(f"Skipping unsupported file type: {ext} ({s3_key})")
            return {"status": "skipped", "message": f"Unsupported file type: {ext}"}

        ctx.logger.info(f"Processing: s3://{s3_bucket}/{s3_key}")

        # --- Resolve output location ---
        dest_bucket, output_key = _get_output_location(s3_bucket, s3_key)

        # --- Idempotency: skip if transcription already exists ---
        if _s3_object_exists(ctx, dest_bucket, output_key):
            ctx.logger.info(f"Transcription already exists: s3://{dest_bucket}/{output_key} - skipping")
            return {"status": "skipped", "message": "Transcription already exists", "output_location": f"s3://{dest_bucket}/{output_key}"}

        # --- Download media file ---
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = os.path.join(tmpdir, Path(s3_key).name)
            _download_from_s3(ctx, s3_bucket, s3_key, media_path)

            # --- Extract audio if video ---
            if ext in VIDEO_EXTENSIONS:
                audio_path = os.path.join(tmpdir, "audio.wav")
                extract_audio(media_path, audio_path, ctx)
            else:
                audio_path = media_path

            # --- Transcribe ---
            language = os.environ.get("ASR_LANGUAGE", "") or None
            ctx.logger.info("Starting transcription...")
            result = asr_engine.transcribe(audio_path, ctx, language=language)
            ctx.logger.info(
                f"Transcription complete: {len(result.segments)} segments, "
                f"{result.duration:.1f}s duration, language={result.language}"
            )

        # --- Build output ---
        output = {
            "status": "success",
            "source_file": f"s3://{s3_bucket}/{s3_key}",
            "asr_engine": os.environ.get("ASR_ENGINE", "faster-whisper"),
            "asr_model": os.environ.get("ASR_MODEL_SIZE", "base"),
            "transcription": result.to_dict(),
        }

        # --- Upload result to S3 ---
        _upload_to_s3(ctx, dest_bucket, output_key, json.dumps(output, indent=2, ensure_ascii=False))

        ctx.logger.info(f"Result uploaded: s3://{dest_bucket}/{output_key}")
        ctx.logger.info(
            f"Summary: {result.language} | {len(result.segments)} segments | "
            f"{len(result.text)} chars | {result.duration:.1f}s"
        )

        return {
            "status": "success",
            "output_location": f"s3://{dest_bucket}/{output_key}",
            "language": result.language,
            "duration_seconds": round(result.duration, 2),
            "segment_count": len(result.segments),
            "text_preview": result.text[:200] + ("..." if len(result.text) > 200 else ""),
        }

    except Exception as e:
        ctx.logger.error(f"Error processing event: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# ===========================================================================
# Helpers
# ===========================================================================

def _get_output_location(source_bucket: str, source_key: str) -> tuple[str, str]:
    """Compute output bucket and key based on OUTPUT_BUCKET / OUTPUT_PREFIX env vars.

    Behavior:
      - No env vars set:        same bucket, sidecar key (video.mp4 -> video.transcription.json)
      - OUTPUT_BUCKET only:     different bucket, same key structure
      - OUTPUT_PREFIX only:     same bucket, key under prefix (prefix/video.transcription.json)
      - Both set:               different bucket, key under prefix
    """
    dest_bucket = output_bucket or source_bucket
    filename = Path(source_key).with_suffix(".transcription.json").name

    if output_prefix:
        dest_key = f"{output_prefix.strip('/')}/{filename}"
    else:
        dest_key = str(Path(source_key).with_suffix(".transcription.json"))

    return dest_bucket, dest_key


def _get_file_location(ctx, event) -> tuple[Optional[str], Optional[str]]:
    """Extract S3 bucket and key from a VAST CloudEvent."""
    if event.type == "Element":
        try:
            element_event = event.as_element_event()
            bucket = element_event.bucket
            key = element_event.object_key
            ctx.logger.info(f"Element event: s3://{bucket}/{key}")
            return bucket, key
        except (TypeError, AttributeError) as e:
            ctx.logger.warning(f"Failed to parse Element event, falling back to data payload: {e}")

    event_data = event.get_data()
    bucket = event_data.get("s3_bucket")
    key = event_data.get("s3_key")
    if bucket and key:
        ctx.logger.info(f"Data payload: s3://{bucket}/{key}")
        return bucket, key

    return None, None


def _s3_object_exists(ctx, bucket: str, key: str) -> bool:
    """Check if an S3 object exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def _download_from_s3(ctx, bucket: str, key: str, local_path: str) -> None:
    """Download a file from S3 to local filesystem."""
    ctx.logger.info(f"Downloading s3://{bucket}/{key}...")

    head = s3_client.head_object(Bucket=bucket, Key=key)
    file_size = head.get("ContentLength", 0)

    if file_size > max_file_size_bytes:
        raise ValueError(
            f"File too large: {file_size / (1024*1024):.0f} MB "
            f"(max {max_file_size_bytes / (1024*1024):.0f} MB)"
        )

    ctx.logger.info(f"File size: {file_size / (1024*1024):.1f} MB")
    s3_client.download_file(bucket, key, local_path)
    ctx.logger.info("Download complete")


def _upload_to_s3(ctx, bucket: str, key: str, content: str) -> None:
    """Upload content string to S3."""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )
