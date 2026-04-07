# Deployment Guide

This guide covers building, deploying, and configuring media-transcription on VAST DataEngine.

## Prerequisites

- **vast CLI** with functions support installed and configured
- **Docker** running locally
- **VAST Cluster** 5.4+ with DataEngine enabled
- **S3 bucket** for media file ingestion

## Step 1: Build the Function Image

```bash
# From the repository root
vast functions build media-transcription
```

The build uses Cloud Native Buildpacks (CNB) to create a container image with:
- Python 3.11+ runtime
- ffmpeg, libsndfile1, libopenblas-dev (via Aptfile)
- boto3, faster-whisper (via requirements.txt)
- VAST runtime SDK

### Verify Build

```bash
docker images | grep media-transcription
```

## Step 2: Configure Environment

### Option A: Mount Path (Recommended for Production)

If you have an NFS/SMB mount to your VAST cluster, configure mount-based access:

```yaml
envs:
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"
  MEDIA_MOUNT_PATH: "/vast/media"  # Path to NFS/SMB mount
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"
```

Mount path resolution:
- If your mount includes the bucket name: `/vast/media/bucket-name` → set `MEDIA_MOUNT_PATH=/vast/media/bucket-name`
- If your mount is generic: `/vast/media` → set `MEDIA_MOUNT_PATH=/vast/media`

The function tries both mappings and falls back to S3 if the file isn't found.

### Option B: S3 Only (Testing, Remote)

For testing or non-VAST deployments:

```yaml
envs:
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"
  # Leave MEDIA_MOUNT_PATH unset - uses S3 download
```

See [Configuration Reference](CONFIGURATION.md) for all variables and [Media Access Modes](ARCHITECTURE.md#media-access-modes) for performance comparison.

## Step 3: Test Locally

```bash
# Terminal 1: Run the function
vast functions localrun media-transcription -c config.yaml -v

# Terminal 2: Send a test event
vast functions invoke -e cloudevent.yaml -u http://localhost:8080
```

You should see log output showing model loading, file download, transcription, and JSON upload.

## Step 4: Deploy to Cluster

### First Deployment

```bash
vast functions create -n media-transcription --from-file config.yaml
```

### Verify

```bash
vast functions get media-transcription
vast functions get media-transcription -r    # With revisions
vast functions get media-transcription -o json | jq '{name, status}'
```

## Step 5: Create Triggers

The function supports three trigger types. Configure one or more as needed:

### Element Trigger (Single File Upload)

In the VMS UI:
1. Navigate to **Manage Elements** -> **Triggers** -> **Create Element Trigger**
2. Set source bucket to your media bucket
3. Event type: `ObjectCreated` (or `ObjectCreated:*`)
4. Suffix filter: `.mp4` (repeat for each format or use wildcard)
5. Link to the `media-transcription` function
6. Deploy trigger

For multiple formats, create separate triggers (one per file type) or use suffix filter `.*` for all files (requires the function to validate extensions).

### Schedule Trigger (Batch Processing)

In the VMS UI:
1. Navigate to **Manage Elements** -> **Triggers** -> **Create Schedule Trigger**
2. Set cron expression (e.g., `0 */6 * * *` for every 6 hours)
3. Link to the `media-transcription` function
4. In function config, set:
   - `SCHEDULE_BUCKET`: S3 bucket to scan
   - `SCHEDULE_PREFIX`: Path prefix (e.g., `pending/`)
5. Deploy trigger

When the cron fires, the function lists `s3://SCHEDULE_BUCKET/SCHEDULE_PREFIX`, finds all files with supported extensions, and transcribes them sequentially within the pod.

### Function Trigger (Function-to-Function)

In your orchestrator function, invoke `media-transcription` with explicit file details:

```python
# Example: from another DataEngine function
result = invoke_function(
    "media-transcription",
    {
        "bucket": "media-assets",
        "key": "uploads/interview.mp4"
    }
)
```

No separate VMS configuration needed. The calling function passes the bucket/key in the CloudEvent data payload.

## Step 5b: Set Up NFS/SMB Mount (Optional, for Mount Path Access)

If you configured `MEDIA_MOUNT_PATH` in Step 2, ensure the mount is available in the function's container environment:

```bash
# Example: Mount configuration in your VAST cluster's container runtime
# Consult your VAST DataEngine documentation for your specific setup
# The mount should be available to all function pods at the same path
```

Verify mount is accessible:
```bash
# In a test pod or function invocation
ls -la /vast/media
# Should show media files, not permission denied
```

## Step 6: Configure Knative Scaling

For ASR workloads, recommended settings:

```bash
vast functions update media-transcription \
  --custom-extension autoscaling.knative.dev/minScale=0 \
  --custom-extension autoscaling.knative.dev/maxScale=10 \
  --custom-extension autoscaling.knative.dev/target=1 \
  --custom-extension serving.knative.dev/timeoutSeconds=900
```

| Setting | Value | Rationale |
|---------|-------|-----------|
| `minScale` | `0` | Scale to zero when idle |
| `maxScale` | `10` | Cap based on cluster capacity |
| `target` (concurrency) | `1` | ASR is CPU-intensive; 1 request per pod |
| `timeoutSeconds` | `900` | 15 minutes for large files |

## Step 8: Test End-to-End

### Test Element Trigger

Upload a media file to the watched bucket:

```bash
aws s3 cp sample.mp4 s3://YOUR_BUCKET/uploads/ \
  --endpoint-url http://YOUR_DATA_VIP
```

Check for the transcription output:

```bash
aws s3 ls s3://YOUR_BUCKET/uploads/sample.transcription.json \
  --endpoint-url http://YOUR_DATA_VIP
```

### Test Schedule Trigger Locally

Use the provided test event:

```bash
# Terminal 1: Run the function locally
vast functions localrun media-transcription -c config.yaml -v

# Terminal 2: Send a Schedule test event
vast functions invoke -e cloudevent-schedule.yaml -u http://localhost:8080
```

You should see the function list objects under `SCHEDULE_BUCKET/SCHEDULE_PREFIX` and transcribe each one.

### Test Function Trigger Locally

Use the provided test event:

```bash
# Terminal 1: Run the function locally
vast functions localrun media-transcription -c config.yaml -v

# Terminal 2: Send a Function test event
vast functions invoke -e cloudevent-function.yaml -u http://localhost:8080
```

You should see the function transcribe the file specified in the event data.

## Updating the Function

After code changes:

```bash
# 1. Rebuild
vast functions build media-transcription

# 2. Update with new config (if changed)
vast functions update media-transcription --from-file config.yaml

# 3. Verify new revision
vast functions get media-transcription -r
```

## Changing the ASR Model

To switch model sizes without code changes:

```bash
# Update just the model size
vast functions update media-transcription \
  --from-file config.yaml
```

Edit `config.yaml` to change `ASR_MODEL_SIZE` before running the update. The new model will be downloaded on the next container cold start.

## Undeploying

```bash
vast functions delete media-transcription
```
