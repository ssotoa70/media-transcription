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

Edit `config.yaml` with your VAST cluster details:

```yaml
envs:
  S3_ENDPOINT: "http://YOUR_DATA_VIP:80"
  S3_ACCESS_KEY: "YOUR_ACCESS_KEY"
  S3_SECRET_KEY: "YOUR_SECRET_KEY"
  ASR_MODEL_SIZE: "base"
  ASR_DEVICE: "cpu"
  ASR_COMPUTE_TYPE: "int8"
```

See [Configuration Reference](CONFIGURATION.md) for all variables.

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

## Step 5: Create the Element Trigger

Configure a trigger to watch for media file uploads. You can create multiple triggers for different file types:

```bash
# Example: watch for MP4 uploads
vast functions update media-transcription \
  --custom-extension autoscaling.knative.dev/minScale=0 \
  --custom-extension autoscaling.knative.dev/maxScale=10
```

In the VMS UI:
1. Navigate to **Manage Elements** -> **Triggers** -> **Create Element Trigger**
2. Set source bucket, event type `ObjectCreated`, suffix filter (e.g., `.mp4`)
3. Link to the `media-transcription` function

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

## Step 7: Test End-to-End

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
