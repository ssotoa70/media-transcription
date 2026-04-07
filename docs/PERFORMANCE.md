# Performance Optimization

## Model Selection

The single biggest performance lever is the Whisper model size. Choose based on your accuracy/speed trade-off:

| Model | CPU Speed | GPU Speed | Word Error Rate | Cold Start |
|-------|-----------|-----------|-----------------|------------|
| `tiny` | ~10x realtime | ~30x realtime | ~12% | ~3s |
| `base` | ~7x realtime | ~20x realtime | ~8% | ~5s |
| `small` | ~3x realtime | ~12x realtime | ~6% | ~8s |
| `medium` | ~1x realtime | ~6x realtime | ~5% | ~15s |
| `large-v3` | ~0.5x realtime | ~3x realtime | ~3% | ~25s |

**CPU speeds** measured with `int8` compute type. **GPU speeds** measured with `float16` on A100.

### Recommendations

| Use Case | Model | Device | Compute |
|----------|-------|--------|---------|
| Quick testing | `tiny` | `cpu` | `int8` |
| **General purpose (default)** | **`base`** | **`cpu`** | **`int8`** |
| Better accuracy | `small` | `cpu` | `int8` |
| Production with GPU | `large-v3` | `cuda` | `float16` |
| Maximum accuracy | `large-v3` | `cuda` | `int8_float16` |

## Transcription Speed Factors

### 1. VAD Filter (Enabled by Default)

Voice Activity Detection skips silence regions, significantly speeding up files with gaps:

- **Podcast with pauses**: 2-3x faster with VAD
- **Continuous speech**: ~10% faster with VAD
- **Music with vocals**: May miss quiet passages (disable for music)

### 2. Beam Size

Higher beam size = more accurate but slower:

| Beam Size | Relative Speed | Use Case |
|-----------|---------------|----------|
| 1 | Fastest (greedy) | Quick drafts |
| **5** | **Default** | **Balanced** |
| 10 | Slower | High accuracy |

### 3. Audio Quality

The function converts video to 16kHz mono WAV. For direct audio uploads:

- **16kHz WAV/FLAC**: Best (no conversion needed)
- **44.1kHz MP3**: Good (faster-whisper resamples internally)
- **Low bitrate audio**: May reduce accuracy regardless of model

## Scaling

### Horizontal Scaling (Recommended)

ASR is CPU-intensive. Scale by adding more pods rather than increasing concurrency per pod:

```bash
vast functions update media-transcription \
  --custom-extension autoscaling.knative.dev/minScale=0 \
  --custom-extension autoscaling.knative.dev/maxScale=20 \
  --custom-extension autoscaling.knative.dev/target=1
```

| Setting | Value | Why |
|---------|-------|-----|
| `containerConcurrency` | 1 | One transcription per pod |
| `maxScale` | 10-20 | Based on cluster CPU capacity |
| `minScale` | 0 | Scale to zero when idle |

### Expected Throughput

For `base` model on CPU (per pod):

| Media Duration | Processing Time | Throughput |
|----------------|-----------------|-----------|
| 1 minute | ~8s | ~7 files/min |
| 10 minutes | ~85s | ~0.7 files/min |
| 60 minutes | ~510s | ~0.1 files/min |

With 10 pods: multiply throughput by 10.

### Cold Start Mitigation

The first invocation after scale-up downloads the model (~140MB for `base`). Strategies:

1. **Set `minScale=1`** -- Keep one warm pod at all times
2. **Use `tiny` model** -- Smallest download, fastest load (~3s)
3. **Pre-bake model in image** -- Add model to the container at build time (advanced)

## Media Access Performance

Choosing between mount path (NFS/SMB) and S3 download significantly impacts both performance and resource usage:

| Aspect | Mount Path | S3 Download |
|--------|-----------|------------|
| **Bandwidth** | None (local read) | Full media file + WAV |
| **Temp Disk (2GB video)** | ~200MB (WAV only) | ~2.2GB (media + WAV) |
| **Temp Disk (1 hour audio)** | 0 bytes (direct pass) | ~360MB |
| **Latency** | Immediate | 30-300s (download) |
| **Bandwidth Cost** | $0 | Egress charges (if AWS) |
| **Network Load** | None | High (large files) |

**Recommendation:** Use mount path in production on VAST clusters. With a 2GB video, mount path uses ~10x less temp disk. For audio files, mount path eliminates temp disk entirely.

## Resource Sizing

### CPU-Only (Default)

#### S3 Download Mode

| Resource | `tiny` | `base` | `small` | `medium` |
|----------|--------|--------|---------|----------|
| CPU request | 0.5 | 1.0 | 2.0 | 4.0 |
| CPU limit | 1.0 | 2.0 | 4.0 | 8.0 |
| Memory request | 512Mi | 1Gi | 2Gi | 4Gi |
| Memory limit | 1Gi | 2Gi | 4Gi | 8Gi |
| Ephemeral disk | 1Gi | 2Gi | 2Gi | 4Gi |

#### Mount Path Mode (Reduced Disk)

With `MEDIA_MOUNT_PATH` configured, ephemeral disk requirements drop significantly:

| Resource | `tiny` | `base` | `small` | `medium` |
|----------|--------|--------|---------|----------|
| CPU request | 0.5 | 1.0 | 2.0 | 4.0 |
| CPU limit | 1.0 | 2.0 | 4.0 | 8.0 |
| Memory request | 512Mi | 1Gi | 2Gi | 4Gi |
| Memory limit | 1Gi | 2Gi | 4Gi | 8Gi |
| Ephemeral disk | 256Mi | 512Mi | 512Mi | 1Gi |

Mount mode disk is only for extracted WAV audio, not the source file.

### GPU (CUDA)

| Resource | `large-v3` |
|----------|------------|
| GPU | 1x NVIDIA A100/L40S |
| Memory | 8Gi |
| Compute type | `float16` |

## Production Deployment Checklist

### Performance & Resource Optimization

- [ ] Choose the smallest model that meets accuracy needs (`base` recommended)
- [ ] Use `int8` compute type on CPU for fastest inference
- [ ] Keep `containerConcurrency=1` (scale horizontally, not vertically)
- [ ] Set appropriate `timeoutSeconds` for expected file sizes (600-900s for large files)
- [ ] Use suffix filters on triggers (don't invoke for non-media files)
- [ ] Set `maxScale` based on cluster capacity (10-20 typical)
- [ ] Consider `minScale=1` if cold start latency matters
- [ ] Use `LOG_LEVEL=WARNING` in production to reduce log volume
- [ ] Set `ASR_LANGUAGE` if all media is one language (skips detection, ~10% faster)

### Mount Path Setup (Highly Recommended)

- [ ] **Mount path configured** -- Set `MEDIA_MOUNT_PATH=/vast/media` (or appropriate path)
- [ ] **Mount verified accessible** -- Test file access from function pods
- [ ] **Disk resources reduced** -- Ephemeral disk 1/4 to 1/10 of S3 mode
- [ ] **Bandwidth eliminated** -- Media files read locally, not downloaded

### Output Configuration

- [ ] **OUTPUT_BUCKET set** -- Separate bucket for transcriptions (improves organization)
- [ ] **OUTPUT_PREFIX set** -- Organize by date/project (e.g., `2026-04/transcripts`)
- [ ] **Bucket permissions** -- Function has `PutObject` permission on output bucket

### Monitoring & Troubleshooting

- [ ] **Timeout buffer** -- Set `timeoutSeconds` 20-30% higher than typical processing time
- [ ] **Disk monitoring** -- Alert on ephemeral disk usage >80% on mount path nodes
- [ ] **Model download** -- First cold start will download model (~140MB for `base`)
- [ ] **Log aggregation** -- Collect function logs for error tracking

### Cost Optimization (AWS/Cloud)

- [ ] **Data transfer** -- Mount path eliminates egress charges for media files
- [ ] **Storage class** -- Use cheaper storage tier for transcription outputs if not frequently accessed
- [ ] **Scale-to-zero** -- `minScale=0` saves compute during idle periods
- [ ] **Regional endpoints** -- Use VAST data VIP, not public S3 (if available)
