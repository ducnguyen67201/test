# Kubernetes CronJobs for OctoLab

This directory contains Kubernetes CronJob manifests for periodic maintenance tasks.

## ending-watchdog.yaml

**Purpose**: Detects and processes labs stuck in ENDING status.

### What It Does

The ENDING watchdog CronJob runs the `force_teardown_ending_labs.py` script periodically to:
- Detect labs that have been in ENDING status for longer than a threshold (default: 30 minutes)
- Either force teardown the lab infrastructure (default) or mark them as FAILED
- Use row-level locking (`skip_locked`) to prevent conflicts with concurrent runs

### Prerequisites

1. **Backend Docker image**: You need a Docker image containing the OctoLab backend code
2. **Database access**: The CronJob needs access to the PostgreSQL database
3. **Kubernetes Secret**: Create a Secret containing database credentials and JWT secret

### Installation

1. **Create the Secret** (customize the values):

```bash
kubectl create secret generic octolab-backend-secrets \
  --namespace=octolab-system \
  --from-literal=database_url='postgresql+asyncpg://octolab:password@postgres-service:5432/octolab' \
  --from-literal=secret_key='your-secure-random-secret-key'
```

2. **Customize the CronJob manifest**:

Edit `ending-watchdog.yaml` and update:
- `image`: Replace with your actual backend image name
- `schedule`: Adjust the cron schedule if needed (default: every 10 minutes)
- `args`: Adjust watchdog parameters:
  - `--older-than-minutes=30`: Process labs in ENDING for >30 minutes
  - `--max-labs=20`: Process at most 20 labs per run
  - `--action=force`: Force teardown (or use `fail` to only mark as FAILED)

3. **Apply the CronJob**:

```bash
kubectl apply -f ending-watchdog.yaml
```

### Configuration Options

The watchdog script accepts the following arguments (configured in `spec.jobTemplate.spec.template.spec.containers[0].args`):

| Argument | Default | Description |
|----------|---------|-------------|
| `--older-than-minutes` | 30 | Only process labs in ENDING for longer than this many minutes |
| `--max-labs` | 20 | Maximum number of labs to process in one run |
| `--action` | force | Action to take: `force` (teardown) or `fail` (mark FAILED only) |
| `--dry-run` | false | Preview mode (no changes made) |

### Monitoring

**View CronJob status**:
```bash
kubectl get cronjob -n octolab-system ending-watchdog
```

**View recent jobs**:
```bash
kubectl get jobs -n octolab-system -l app=ending-watchdog
```

**View logs from the latest run**:
```bash
# Get the latest job pod
POD=$(kubectl get pods -n octolab-system -l app=ending-watchdog --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')

# View logs
kubectl logs -n octolab-system $POD
```

**Manually trigger a run** (for testing):
```bash
kubectl create job -n octolab-system \
  --from=cronjob/ending-watchdog \
  manual-watchdog-$(date +%s)
```

### Security

The CronJob is configured with security best practices:
- Runs as non-root user (UID 1000)
- Read-only root filesystem
- No privilege escalation
- All capabilities dropped
- Resource limits enforced
- Concurrency policy set to `Forbid` (prevents overlapping runs)

### Troubleshooting

**No jobs are being created**:
- Check if the CronJob is suspended: `kubectl get cronjob -n octolab-system ending-watchdog -o jsonpath='{.spec.suspend}'`
- Verify the schedule is correct (cron format)
- Check CronJob events: `kubectl describe cronjob -n octolab-system ending-watchdog`

**Jobs are failing**:
- Check pod logs: `kubectl logs -n octolab-system <pod-name>`
- Common issues:
  - Database connection failed (check `DATABASE_URL` in Secret)
  - Image pull failed (check image name and availability)
  - Missing environment variables (check Secret exists and contains required keys)

**Too many labs being processed**:
- Reduce `--max-labs` argument
- Increase `--older-than-minutes` to only process older labs
- Check database for root cause of labs getting stuck in ENDING

**Not enough labs being processed**:
- Check if labs are actually stuck (query database for ENDING labs)
- Verify age threshold is appropriate for your use case
- Consider increasing `--max-labs` if needed
- Check for row-level locks (another process might be holding locks)
