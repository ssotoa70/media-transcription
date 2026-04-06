# Troubleshooting Guide

## Build Issues

### Error: "ffmpeg not found" during local testing

**Symptom**: `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**Cause**: ffmpeg not installed on the local machine. The `Aptfile` only installs it in the container.

**Solution**:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Verify
ffmpeg -version
```

---

### Error: Build fails with "pip install faster-whisper"

**Symptom**: Container build fails resolving faster-whisper dependencies.

**Cause**: CTranslate2 requires specific system libraries.

**Solution**: Ensure `Aptfile` includes all required packages:
```
ffmpeg
libsndfile1
libopenblas-dev
```

If the build still fails, try pinning a specific version in `requirements.txt`:
```
faster-whisper==1.1.0
```

---

## Runtime Errors

### Error: "Could not determine file location from event"

**Symptom**: Handler returns `status: error` with this message.

**Cause**: The CloudEvent doesn't contain a valid file location. Either the `elementpath` extension is missing (Element events) or the data payload lacks `s3_bucket`/`s3_key`.

**Solutions**:

1. **Verify event format** -- Check your `cloudevent.yaml`:
   ```yaml
   # Element events MUST have these fields:
   type: "vastdata.com:Element.ObjectCreated"
   source: "vastdata.com:trigger1.UUID-HERE"
   subject: "vastdata.com:kafka-view.default-topic"
   elementpath: "bucket-name/path/to/file.mp4"
   ```

2. **Verify event ID is UUID** -- Non-hex IDs cause parsing errors:
   ```yaml
   id: "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"  # Correct
   id: "test-event-001"                              # Wrong
   ```

3. **Use `--generate-event` for quick tests**:
   ```bash
   vast functions invoke --generate-event --url http://localhost:8080
   ```

---

### Error: "S3 ClientError (403): Access Denied"

**Symptom**: File download or upload fails with 403.

**Cause**: S3 credentials are invalid or lack permissions.

**Solutions**:

1. **Check credentials in config.yaml** -- Ensure `S3_ACCESS_KEY` and `S3_SECRET_KEY` are correct.

2. **Verify endpoint** -- The `S3_ENDPOINT` must point to your VAST S3 data VIP:
   ```yaml
   S3_ENDPOINT: "http://172.200.212.1:80"  # Correct (VAST data VIP)
   S3_ENDPOINT: "https://s3.amazonaws.com"  # Wrong (default)
   ```

3. **Check bucket permissions** -- The credentials need `GetObject`, `HeadObject`, and `PutObject` on the bucket.

4. **Check init logs** -- Look for warnings:
   ```
   S3 credentials not set - S3 operations will fail
   ```

---

### Error: "S3 ClientError (404): Not Found"

**Symptom**: File download fails with 404.

**Cause**: The file referenced in the event doesn't exist in the bucket.

**Solutions**:

1. **Check the elementpath** -- Verify the bucket and key are correct:
   ```
   elementpath: "media-assets/uploads/interview.mp4"
   ```
   Parsed as: bucket=`media-assets`, key=`uploads/interview.mp4`

2. **File may have been deleted** -- If there's a delay between upload and processing, the file may have been removed.

3. **Test with aws CLI**:
   ```bash
   aws s3 ls s3://media-assets/uploads/interview.mp4 \
     --endpoint-url http://YOUR_DATA_VIP
   ```

---

### Error: "File too large: X MB (max Y MB)"

**Symptom**: Handler rejects the file before downloading.

**Cause**: File exceeds `MAX_FILE_SIZE_MB` (default: 2048MB).

**Solutions**:

1. **Increase the limit** in `config.yaml`:
   ```yaml
   MAX_FILE_SIZE_MB: "4096"
   ```

2. **Ensure ephemeral disk** is sized appropriately -- The container needs enough temp space for the media file plus the extracted WAV audio.

---

### Error: "ffmpeg failed (exit 1): ..."

**Symptom**: Audio extraction from video fails.

**Cause**: The video file is corrupted, uses an unsupported codec, or has no audio track.

**Solutions**:

1. **Check if the file has audio**:
   ```bash
   ffprobe -i input.mp4 -show_streams -select_streams a
   # If empty output, there's no audio track
   ```

2. **Test locally**:
   ```bash
   ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 -y test.wav
   ```

3. **Check codec support** -- The container's ffmpeg should support all common codecs. If a rare codec is missing, check the Aptfile.

---

### Error: "Transcription already exists ... skipping"

**Symptom**: Handler returns `status: skipped` even though you want to re-transcribe.

**Cause**: The idempotency check found an existing `.transcription.json` file.

**Solution**: Delete the existing transcription to force re-processing:
```bash
aws s3 rm s3://bucket/path/file.transcription.json \
  --endpoint-url http://YOUR_DATA_VIP
```

Then re-trigger the event.

---

## Model Issues

### Error: "Unable to download model" on cold start

**Symptom**: `init()` fails trying to download the Whisper model.

**Cause**: The container can't reach Hugging Face Hub to download the model.

**Solutions**:

1. **Check network access** -- Containers need outbound HTTPS access to `huggingface.co` on first run.

2. **Use a smaller model** -- `tiny` (75MB) downloads much faster than `large-v3` (3GB).

3. **Pre-bake the model** -- Download the model at build time by adding a custom build step:
   ```bash
   # Download model locally
   python -c "from faster_whisper import WhisperModel; WhisperModel('base')"
   # Include ~/.cache/huggingface in the container image
   ```

---

### Problem: Poor transcription accuracy

**Symptom**: Transcription has many errors or hallucinations.

**Solutions**:

1. **Use a larger model**: `small` or `medium` significantly improves accuracy.

2. **Set the language explicitly** if known:
   ```yaml
   ASR_LANGUAGE: "en"
   ```
   Auto-detection can fail on short clips or noisy audio.

3. **Increase beam size**:
   ```yaml
   ASR_BEAM_SIZE: "10"
   ```

4. **Check audio quality** -- Low bitrate, heavy background noise, or multiple overlapping speakers reduce accuracy regardless of model.

---

### Problem: Transcription is slow

**Symptom**: Processing takes much longer than expected.

**Solutions**:

1. **Check model size** -- `medium` and `large-v3` are slow on CPU. Use `base` for CPU deployments.

2. **Verify compute type** -- `int8` is fastest on CPU:
   ```yaml
   ASR_COMPUTE_TYPE: "int8"
   ```

3. **Check for excessive silence** -- VAD filter (`vad_filter=True`) should skip silence. If disabled, re-enable it.

4. **Use GPU** -- For production with large files, CUDA provides 3-10x speedup:
   ```yaml
   ASR_DEVICE: "cuda"
   ASR_COMPUTE_TYPE: "float16"
   ```

---

## Timeout Issues

### Error: Function times out

**Symptom**: Knative kills the container before transcription completes.

**Cause**: Default timeout (300s) is too short for large files.

**Solutions**:

1. **Increase timeout**:
   ```bash
   vast functions update media-transcription \
     --custom-extension serving.knative.dev/timeoutSeconds=900
   ```

2. **Estimate processing time**:
   - `base` model on CPU: ~8 seconds per minute of audio
   - 60-minute file: ~480 seconds → set timeout to 600+
   - Add buffer for download and audio extraction

3. **Use a faster model** (`tiny`) for very large files.

---

## Debugging

### Enable Verbose Logging

Set `LOG_LEVEL=DEBUG` in config.yaml for detailed output.

### Test Locally with curl

```bash
# Start function
vast functions localrun media-transcription -c config.yaml -v

# Send a test event
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "specversion": "1.0",
    "type": "vastdata.com:Function",
    "source": "vastdata.com:test",
    "id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
    "datacontenttype": "application/json",
    "data": {
      "s3_bucket": "your-bucket",
      "s3_key": "path/to/file.mp4"
    }
  }'
```

### Check Container Logs

```bash
# Recent logs
vast functions get media-transcription -o json | jq '.status'

# If using pipeline
vastde logs get YOUR_PIPELINE --since 5m
```

### Verify S3 Output

```bash
# List transcription files
aws s3 ls s3://your-bucket/ --recursive --endpoint-url http://YOUR_VIP \
  | grep transcription.json
```
