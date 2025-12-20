#!/usr/bin/env bash
# Safe reset of OctoBox Beta Kubernetes resources
# Usage: ./scripts/octobox-reset.sh [--namespace <ns>] [--delete-evidence] [--yes]
# Default: preserves evidence PVC, requires explicit --delete-evidence to remove it

set -euo pipefail

NAMESPACE="${NAMESPACE:-octolab-labs}"
DELETE_EVIDENCE=false

# Parse flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --delete-evidence)
            DELETE_EVIDENCE=true
            shift
            ;;
        --yes)
            # For future use if prompts are added
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--namespace <ns>] [--delete-evidence] [--yes]" >&2
            exit 1
            ;;
    esac
done

echo "[octobox-reset] Starting reset of OctoBox Beta resources in namespace: $NAMESPACE"
if [[ "$DELETE_EVIDENCE" == "true" ]]; then
    echo "[octobox-reset] WARNING: --delete-evidence flag set - PVC will be deleted!"
else
    echo "[octobox-reset] Evidence PVC will be preserved (use --delete-evidence to remove)"
fi
echo ""

# Step 1: Scale deployment to 0
echo "[octobox-reset] Step 1: Scaling deployment to 0 replicas..."
if kubectl -n "$NAMESPACE" get deployment octobox-beta &>/dev/null; then
    kubectl -n "$NAMESPACE" scale deployment octobox-beta --replicas=0 || true
    echo "[octobox-reset]   ✓ Deployment scaled to 0"
else
    echo "[octobox-reset]   ℹ Deployment not found (may already be deleted)"
fi

# Step 2: Delete ReplicaSets (cascades to pods) and wait for pods to terminate
echo ""
echo "[octobox-reset] Step 2: Deleting ReplicaSets and waiting for pods to terminate..."

# Delete ReplicaSets first (this will trigger pod deletion)
if kubectl -n "$NAMESPACE" get rs -l app=octobox-beta &>/dev/null; then
    kubectl -n "$NAMESPACE" delete rs -l app=octobox-beta --ignore-not-found=true
    echo "[octobox-reset]   ✓ ReplicaSets deleted"
fi

# Wait for pods to terminate
TIMEOUT=60
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
    POD_LIST=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta --no-headers 2>/dev/null || echo "")
    if [[ -z "$POD_LIST" ]]; then
        echo "[octobox-reset]   ✓ All pods terminated"
        break
    fi
    POD_COUNT=$(echo "$POD_LIST" | grep -v "^$" | wc -l)
    if [[ "$POD_COUNT" == "0" ]]; then
        echo "[octobox-reset]   ✓ All pods terminated"
        break
    fi
    echo "[octobox-reset]   ⏳ Waiting... ($POD_COUNT pod(s) remaining, ${ELAPSED}s/${TIMEOUT}s)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

# If timeout, force delete stuck pods
if [[ $ELAPSED -ge $TIMEOUT ]]; then
    REMAINING_PODS=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta --no-headers -o name 2>/dev/null || echo "")
    if [[ -n "$REMAINING_PODS" ]]; then
        echo "[octobox-reset]   ⚠ Timeout waiting for pods - force deleting stuck pods..."
        echo "$REMAINING_PODS" | while read -r pod; do
            if [[ -n "$pod" ]]; then
                kubectl -n "$NAMESPACE" delete "$pod" --force --grace-period=0 2>/dev/null || true
            fi
        done
        sleep 3
        # Verify they're gone
        FINAL_LIST=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta --no-headers 2>/dev/null || echo "")
        FINAL_COUNT=$(echo "$FINAL_LIST" | grep -v "^$" | wc -l)
        if [[ "$FINAL_COUNT" == "0" ]]; then
            echo "[octobox-reset]   ✓ Stuck pods force-deleted"
        else
            echo "[octobox-reset]   ⚠ Warning: $FINAL_COUNT pod(s) still remain after force delete"
            echo "[octobox-reset]   Remaining pods:" >&2
            echo "$FINAL_LIST" | sed 's/^/    /' >&2
        fi
    fi
fi

# Step 3: Delete resources
echo ""
echo "[octobox-reset] Step 3: Deleting OctoBox resources..."

RESOURCES_DELETED=0

# Delete Deployment (cascades to ReplicaSets and Pods)
if kubectl -n "$NAMESPACE" get deployment octobox-beta &>/dev/null; then
    kubectl -n "$NAMESPACE" delete deployment octobox-beta --ignore-not-found=true
    echo "[octobox-reset]   ✓ Deployment deleted"
    RESOURCES_DELETED=$((RESOURCES_DELETED + 1))
fi

# ReplicaSets should already be deleted in Step 2, but ensure cleanup
if kubectl -n "$NAMESPACE" get rs -l app=octobox-beta &>/dev/null; then
    kubectl -n "$NAMESPACE" delete rs -l app=octobox-beta --ignore-not-found=true
    echo "[octobox-reset]   ✓ ReplicaSets cleaned up"
fi

# Delete Service
if kubectl -n "$NAMESPACE" get service octobox-beta-novnc &>/dev/null; then
    kubectl -n "$NAMESPACE" delete service octobox-beta-novnc --ignore-not-found=true
    echo "[octobox-reset]   ✓ Service deleted"
    RESOURCES_DELETED=$((RESOURCES_DELETED + 1))
fi

# Delete Ingress
if kubectl -n "$NAMESPACE" get ingress octobox-beta-novnc &>/dev/null; then
    kubectl -n "$NAMESPACE" delete ingress octobox-beta-novnc --ignore-not-found=true
    echo "[octobox-reset]   ✓ Ingress deleted"
    RESOURCES_DELETED=$((RESOURCES_DELETED + 1))
fi

# Delete Secret
if kubectl -n "$NAMESPACE" get secret octobox-beta-novnc-secret &>/dev/null; then
    kubectl -n "$NAMESPACE" delete secret octobox-beta-novnc-secret --ignore-not-found=true
    echo "[octobox-reset]   ✓ Secret deleted"
    RESOURCES_DELETED=$((RESOURCES_DELETED + 1))
fi

# Step 4: Handle PVC
echo ""
if [[ "$DELETE_EVIDENCE" == "true" ]]; then
    echo "[octobox-reset] Step 4: Deleting evidence PVC (--delete-evidence flag set)..."
    if kubectl -n "$NAMESPACE" get pvc octobox-beta-evidence &>/dev/null; then
        kubectl -n "$NAMESPACE" delete pvc octobox-beta-evidence --ignore-not-found=true
        echo "[octobox-reset]   ✓ Evidence PVC deleted"
    else
        echo "[octobox-reset]   ℹ Evidence PVC not found (may already be deleted)"
    fi
else
    echo "[octobox-reset] Step 4: Preserving evidence PVC (use --delete-evidence to remove)"
    if kubectl -n "$NAMESPACE" get pvc octobox-beta-evidence &>/dev/null; then
        echo "[octobox-reset]   ✓ Evidence PVC preserved"
    else
        echo "[octobox-reset]   ℹ Evidence PVC not found"
    fi
fi

# Step 5: Post-check summary
echo ""
echo "[octobox-reset] Step 5: Verification summary..."
echo ""

# Check remaining resources (strip whitespace/newlines and convert to integer)
REMAINING_PODS=$(kubectl -n "$NAMESPACE" get pods -l app=octobox-beta --no-headers 2>/dev/null | grep -v "^$" | wc -l | tr -d '[:space:]' || echo "0")
REMAINING_PODS=$((REMAINING_PODS + 0))  # Convert to integer, strips whitespace
REMAINING_RS=$(kubectl -n "$NAMESPACE" get rs -l app=octobox-beta --no-headers 2>/dev/null | grep -v "^$" | wc -l | tr -d '[:space:]' || echo "0")
REMAINING_RS=$((REMAINING_RS + 0))
REMAINING_SVC=$(kubectl -n "$NAMESPACE" get svc -l app=octobox-beta --no-headers 2>/dev/null | grep -v "^$" | wc -l | tr -d '[:space:]' || echo "0")
REMAINING_SVC=$((REMAINING_SVC + 0))
REMAINING_ING=$(kubectl -n "$NAMESPACE" get ingress -l app=octobox-beta --no-headers 2>/dev/null | grep -v "^$" | wc -l | tr -d '[:space:]' || echo "0")
REMAINING_ING=$((REMAINING_ING + 0))

echo "[octobox-reset] Remaining resources with label app=octobox-beta:"
echo "  - Pods: $REMAINING_PODS"
echo "  - ReplicaSets: $REMAINING_RS"
echo "  - Services: $REMAINING_SVC"
echo "  - Ingresses: $REMAINING_ING"

# Check PVC status
if kubectl -n "$NAMESPACE" get pvc octobox-beta-evidence &>/dev/null; then
    PVC_STATUS=$(kubectl -n "$NAMESPACE" get pvc octobox-beta-evidence -o jsonpath='{.status.phase}' 2>/dev/null || echo "unknown")
    echo "  - Evidence PVC: PRESERVED (status: $PVC_STATUS)"
else
    echo "  - Evidence PVC: DELETED or NOT FOUND"
fi

echo ""
# Use arithmetic comparison to ensure integer comparison (handles whitespace)
if [[ $((REMAINING_PODS + REMAINING_RS + REMAINING_SVC + REMAINING_ING)) -eq 0 ]]; then
    echo "[octobox-reset] ✓ Reset complete! All OctoBox resources removed."
    exit 0
else
    echo "[octobox-reset] ⚠ Warning: Some resources remain. Check above for details." >&2
    exit 1
fi

