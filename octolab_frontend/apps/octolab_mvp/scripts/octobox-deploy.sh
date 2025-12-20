#!/usr/bin/env bash
# Deploy OctoBox Beta and verify rollout
# Usage: ./scripts/octobox-deploy.sh [--namespace <ns>]

set -euo pipefail

NAMESPACE="${NAMESPACE:-octolab-labs}"

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--namespace <ns>]" >&2
            exit 1
            ;;
    esac
done

echo "[octobox-deploy] Deploying OctoBox Beta to namespace: $NAMESPACE"
echo ""

# Step 1: Apply manifests
echo "[octobox-deploy] Step 1: Applying manifests..."
if kubectl apply -k infra/apps/octobox-beta/; then
    echo "[octobox-deploy]   ✓ Manifests applied"
else
    echo "[octobox-deploy]   ✗ Failed to apply manifests" >&2
    exit 1
fi

# Step 2: Wait for rollout
echo ""
echo "[octobox-deploy] Step 2: Waiting for deployment rollout..."
if kubectl -n "$NAMESPACE" rollout status deployment/octobox-beta --timeout=180s; then
    echo "[octobox-deploy]   ✓ Rollout complete"
else
    echo "[octobox-deploy]   ✗ Rollout failed or timed out" >&2
    echo "[octobox-deploy]   Checking pod status..." >&2
    kubectl -n "$NAMESPACE" get pods -l app=octobox-beta
    exit 1
fi

# Step 3: Verify pod is Ready 2/2
echo ""
echo "[octobox-deploy] Step 3: Verifying pod readiness..."
POD_READY=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta -o jsonpath='{.items[0].status.containerStatuses[*].ready}' 2>/dev/null || echo "")
POD_READY_COUNT=$(echo "$POD_READY" | tr ' ' '\n' | grep -c "true" || echo "0")

if [[ "$POD_READY_COUNT" -eq 2 ]]; then
    POD_NAME=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    echo "[octobox-deploy]   ✓ Pod ready: $POD_NAME (2/2 containers)"
else
    echo "[octobox-deploy]   ✗ Pod not ready (expected 2/2, got $POD_READY_COUNT/2)" >&2
    kubectl -n "$NAMESPACE" get pods -l app=octobox-beta
    exit 1
fi

# Step 4: Verify endpoints populated
echo ""
echo "[octobox-deploy] Step 4: Verifying Service endpoints..."
ENDPOINTS=$(kubectl -n "$NAMESPACE" get endpoints octobox-beta-novnc -o jsonpath='{.subsets[0].addresses[*].ip}' 2>/dev/null || echo "")
if [[ -n "$ENDPOINTS" ]]; then
    echo "[octobox-deploy]   ✓ Endpoints populated: $ENDPOINTS"
else
    echo "[octobox-deploy]   ✗ No endpoints found" >&2
    kubectl -n "$NAMESPACE" get endpoints octobox-beta-novnc
    exit 1
fi

# Step 5: Verify Service does NOT expose port 5900
echo ""
echo "[octobox-deploy] Step 5: Verifying Service security (no port 5900)..."
SVC_YAML=$(kubectl -n "$NAMESPACE" get svc octobox-beta-novnc -o yaml 2>/dev/null || echo "")
if echo "$SVC_YAML" | grep -qiE "5900|port.*5900|targetPort.*5900"; then
    echo "[octobox-deploy]   ✗ SECURITY ERROR: Service exposes port 5900!" >&2
    echo "$SVC_YAML" | grep -i "5900"
    exit 1
else
    echo "[octobox-deploy]   ✓ Service correctly exposes only port 6080"
fi

# Step 6: Summary and access instructions
echo ""
echo "[octobox-deploy] ✓ Deployment successful!"
echo ""
echo "[octobox-deploy] Access instructions:"
echo "  Port-forward: kubectl -n $NAMESPACE port-forward svc/octobox-beta-novnc 6080:6080"
echo "  Then open: http://localhost:6080/"
echo "  Password: octo123"
echo ""
echo "[octobox-deploy] Pod details:"
kubectl -n "$NAMESPACE" get pods -l app=octobox-beta -o wide
echo ""
echo "[octobox-deploy] Service details:"
kubectl -n "$NAMESPACE" get svc octobox-beta-novnc

