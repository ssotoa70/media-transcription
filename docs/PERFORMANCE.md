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

## Resource Sizing

### CPU-Only (Default)

| Resource | `tiny` | `base` | `small` | `medium` |
|----------|--------|--------|---------|----------|
| CPU request | 0.5 | 1.0 | 2.0 | 4.0 |
| CPU limit | 1.0 | 2.0 | 4.0 | 8.0 |
| Memory request | 512Mi | 1Gi | 2Gi | 4Gi |
| Memory limit | 1Gi | 2Gi | 4Gi | 8Gi |
| Ephemeral disk | 1Gi | 2Gi | 2Gi | 4Gi |

### GPU (CUDA)

| Resource | `large-v3` |
|----------|------------|
| GPU | 1x NVIDIA A100/L40S |
| Memory | 8Gi |
| Compute type | `float16` |

## Optimization Checklist

- [ ] Choose the smallest model that meets accuracy needs
- [ ] Use `int8` compute type on CPU
- [ ] Keep `containerConcurrency=1` (scale horizontally)
- [ ] Set appropriate `timeoutSeconds` for expected file sizes
- [ ] Use suffix filters on triggers (don't invoke for non-media files)
- [ ] Set `maxScale` based on cluster capacity
- [ ] Consider `minScale=1` if cold start latency matters
- [ ] Use `LOG_LEVEL=WARNING` in production to reduce log volume
- [ ] Set `ASR_LANGUAGE` if all media is one language (skips detection)
