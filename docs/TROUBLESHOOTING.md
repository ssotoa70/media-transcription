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

## Mount Path Issues

### Error: "Mount path configured but file not found ... Falling back to S3"

**Symptom**: Handler logs warning about mount path, then falls back to S3 download.

**Cause**: The configured `MEDIA_MOUNT_PATH` exists, but the media file isn't at the expected location.

**Solutions**:

1. **Verify mount is accessible**:
   ```bash
   ls -la /vast/media
   # Should show directories/files, not "permission denied" or "no such file"
   ```

2. **Check path resolution** -- The function tries two patterns:
   ```
   Try 1: /vast/media/bucket-name/object-key
   Try 2: /vast/media/object-key
   ```
   Verify your file matches one of these patterns:
   ```bash
   # For s3://media-assets/uploads/video.mp4
   ls -la /vast/media/media-assets/uploads/video.mp4     # Pattern 1
   ls -la /vast/media/uploads/video.mp4                  # Pattern 2
   ```

3. **Check if MEDIA_MOUNT_PATH includes bucket** -- If your mount is already scoped to a bucket:
   ```yaml
   MEDIA_MOUNT_PATH: "/vast/media/media-assets"  # Mount includes bucket
   # Try: /vast/media/media-assets/uploads/video.mp4
   ```

4. **Verify element event bucket/key** -- Check that your event's `elementpath` is correct:
   ```bash
   # logs should show:
   # Processing: s3://media-assets/uploads/video.mp4
   ```

5. **Verify file permissions**:
   ```bash
   # Check if the function container's user can read the file
   stat /vast/media/path/to/file.mp4
   # Should show readable permissions
   ```

**Fallback behavior**: If mount fails, the function automatically downloads from S3 (slower but works). Check S3 credentials if download also fails.

---

### Error: "Permission denied" on mount path

**Symptom**: `PermissionError: [Errno 13] Permission denied: '/vast/media/...'`

**Cause**: The function container user doesn't have read permission on the mount.

**Solutions**:

1. **Check file permissions**:
   ```bash
   ls -l /vast/media/path/to/file.mp4
   # Should have read permission (r) for owner/group/other
   ```

2. **Check mount permissions**:
   ```bash
   ls -ld /vast/media
   # Should have x (execute) permission to traverse
   ```

3. **Verify container user** -- By default, function containers run as non-root. Ensure the mount is readable by all users or the specific container UID.

4. **NFS/SMB mount options** -- Check cluster mount configuration:
   ```bash
   # Verify mount is not read-only or with restrictive permissions
   mount | grep vast
   ```

---

### Error: "Stale NFS file handle"

**Symptom**: `OSError: [Errno 116] Stale NFS file handle`

**Cause**: The NFS mount became stale (server disconnect, network issue).

**Solutions**:

1. **Remount the filesystem** -- Cluster administrator action:
   ```bash
   # On nodes where functions run
   umount /vast/media
   mount /vast/media
   ```

2. **Enable NFS soft mounts** -- Modify mount options for better recovery:
   ```
   soft,timeo=30,retrans=3
   ```

3. **Check NFS server health** -- Verify VAST cluster network connectivity and NFS service status.

4. **Fallback in code** -- The function catches this error and automatically falls back to S3 download. Check logs for the fallback message.

---

## Output Location Issues

### Error: "S3 ClientError (403): Access Denied" on upload

**Symptom**: Handler fails uploading transcription JSON with 403 error.

**Cause**: S3 credentials lack write permission on the output bucket.

**Solutions**:

1. **Check OUTPUT_BUCKET permissions** -- Verify S3 credentials have `PutObject` permission:
   ```bash
   # Test with aws CLI
   aws s3 cp test.json s3://output-bucket/test.json \
     --endpoint-url http://YOUR_DATA_VIP
   ```

2. **If OUTPUT_BUCKET is unset** -- Transcription writes to the source bucket:
   ```yaml
   OUTPUT_BUCKET: ""  # Writes to same bucket as source file
   ```
   Ensure credentials have write permission on the source bucket.

3. **Verify credential scope** -- If using role-based access (VAST IAM):
   ```bash
   # Check that the read key also has write permission
   # Or use a separate write key for OUTPUT_BUCKET
   ```

---

### Wrong output location

**Symptom**: Transcription appears in unexpected bucket/path.

**Cause**: `OUTPUT_BUCKET` and `OUTPUT_PREFIX` configuration.

**Verify actual behavior** using this matrix:

| Config | Source | Output |
|--------|--------|--------|
| `OUTPUT_BUCKET=""` | `s3://media/uploads/video.mp4` | `s3://media/uploads/video.transcription.json` |
| `OUTPUT_BUCKET="results"` | `s3://media/uploads/video.mp4` | `s3://results/uploads/video.transcription.json` |
| `OUTPUT_PREFIX="2026"` | `s3://media/uploads/video.mp4` | `s3://media/2026/video.transcription.json` |
| Both set | `s3://media/uploads/video.mp4` | `s3://results/2026/video.transcription.json` |

Check your `config.yaml` against this table. See [Configuration Reference](CONFIGURATION.md#output-location-behavior) for more details.

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
