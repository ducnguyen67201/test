#!/usr/bin/env bash
# Smoke test for k3d cluster
#
# Verifies that the cluster is running and healthy

set -euo pipefail

CLUSTER_NAME="octolab-dev"
CONTEXT="k3d-${CLUSTER_NAME}"

echo "==> k3d cluster smoke test"
echo ""

# Track failures
FAILED=0

# Helper function for checks
check() {
    local description="$1"
    shift
    echo -n "  ✓ ${description}... "
    if "$@" &> /dev/null; then
        echo "OK"
        return 0
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# Helper function for info checks (non-fatal)
info_check() {
    local description="$1"
    shift
    echo -n "  ℹ ${description}... "
    if "$@" &> /dev/null; then
        echo "OK"
    else
        echo "NOT FOUND (this may be expected)"
    fi
}

echo "Cluster Checks:"
echo "---------------"

# Check k3d installed
check "k3d installed" command -v k3d

# Check cluster exists
check "Cluster '${CLUSTER_NAME}' exists" k3d cluster list | grep -q "^${CLUSTER_NAME}"

# Check cluster running
check "Cluster is running" k3d cluster list | grep "^${CLUSTER_NAME}" | grep -q "running"

# Check kubectl configured
check "kubectl configured for context '${CONTEXT}'" kubectl config get-contexts | grep -q "${CONTEXT}"

# Switch to correct context
kubectl config use-context "${CONTEXT}" &> /dev/null

echo ""
echo "Node Checks:"
echo "------------"

# Check nodes ready
check "All nodes ready" kubectl wait --for=condition=Ready nodes --all --timeout=30s

# Get node count
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
echo "  ℹ Node count: ${NODE_COUNT}"

echo ""
echo "Namespace Checks:"
echo "-----------------"

# Check required namespaces exist
check "Namespace 'octolab-system' exists" kubectl get namespace octolab-system
check "Namespace 'octolab-labs' exists" kubectl get namespace octolab-labs

# Check default namespaces
check "Namespace 'kube-system' exists" kubectl get namespace kube-system
check "Namespace 'default' exists" kubectl get namespace default

echo ""
echo "Pod Checks:"
echo "-----------"

# Check system pods running
check "CoreDNS pods running" kubectl get pods -n kube-system -l k8s-app=kube-dns --field-selector=status.phase=Running | grep -q "Running"

# Check for any failing pods in kube-system
if kubectl get pods -n kube-system --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null | grep -q .; then
    echo "  ⚠ Warning: Some pods in kube-system are not running"
    kubectl get pods -n kube-system --field-selector=status.phase!=Running,status.phase!=Succeeded
    FAILED=$((FAILED + 1))
else
    echo "  ✓ All kube-system pods healthy"
fi

echo ""
echo "Network Checks:"
echo "---------------"

# Check if network policies exist (optional, may not be deployed yet)
info_check "Network policies in octolab-labs" kubectl get networkpolicies -n octolab-labs | grep -q "."

echo ""
echo "Ingress Checks:"
echo "---------------"

# Check if ports are accessible (basic connectivity)
check "HTTP port 8080 accessible" nc -z 127.0.0.1 8080 -w 2
check "HTTPS port 8443 accessible" nc -z 127.0.0.1 8443 -w 2

echo ""
echo "Basic Functionality:"
echo "--------------------"

# Try to create a test pod (and clean it up)
check "Can create pods" kubectl run smoke-test --image=busybox:latest --restart=Never --command -- sleep 10
if kubectl get pod smoke-test &> /dev/null; then
    kubectl delete pod smoke-test --wait=false &> /dev/null
fi

echo ""
echo "=========================================="

if [ $FAILED -eq 0 ]; then
    echo "✓ All smoke tests passed"
    echo ""
    echo "Cluster is healthy and ready for use!"
    echo ""
    echo "Access points:"
    echo "  - HTTP:  http://127.0.0.1:8080"
    echo "  - HTTPS: https://127.0.0.1:8443"
    echo ""
    exit 0
else
    echo "✗ ${FAILED} smoke test(s) failed"
    echo ""
    echo "Check the output above for details"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check Docker: docker ps"
    echo "  - Check cluster: k3d cluster list"
    echo "  - Check logs: docker logs k3d-${CLUSTER_NAME}-server-0"
    echo "  - Recreate cluster: ./delete_cluster.sh && ./create_cluster.sh"
    echo ""
    exit 1
fi
