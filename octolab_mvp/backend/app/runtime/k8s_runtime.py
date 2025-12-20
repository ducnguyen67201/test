"""Kubernetes-backed LabRuntime implementation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import subprocess
from pathlib import Path
from typing import Any, Tuple
from subprocess import CalledProcessError, TimeoutExpired

from app.config import settings
from app.models.lab import Lab
from app.models.recipe import Recipe
from app.runtime.base import LabRuntime
from app.utils.redact import redact_argv, truncate_text, sanitize_subprocess_error
from app.helpers.cluster_detector import detect_cluster_type, check_apiserver_readiness

logger = logging.getLogger(__name__)


class K8sLabRuntime(LabRuntime):
    """Provision labs by creating Kubernetes resources in per-lab namespaces."""

    def __init__(
        self,
        kubeconfig_path: str | Path | None = None,
        context: str | None = None,
        ingress_enabled: bool = False,
        base_domain: str = "octolab.local",
    ) -> None:
        """
        Initialize K8s runtime.

        Args:
            kubeconfig_path: Path to kubeconfig file (defaults to ~/.kube/config or in-cluster)
            context: Kubernetes context name (optional)
            ingress_enabled: Whether to create Ingress resources
            base_domain: Base domain for Ingress hosts
        """
        self.kubeconfig_path = kubeconfig_path
        self.context = context
        self.ingress_enabled = ingress_enabled
        self.base_domain = base_domain
        self.kubectl_timeout = 60  # seconds

    def ns_name(self, lab: Lab) -> str:
        """
        Generate namespace name from lab ID.

        Kubernetes namespace names must be DNS-1123 subdomains:
        - lowercase alphanumeric or '-'
        - start and end with alphanumeric
        - max 63 characters

        UUIDs are already lowercase hex with hyphens, so we just prefix with "lab-"
        and ensure it's under 63 chars.
        """
        ns = f"lab-{lab.id}"
        # UUIDs are 36 chars, so "lab-" + UUID = 40 chars (safe)
        if len(ns) > 63:
            # Truncate and append hash suffix if needed (shouldn't happen with UUIDs)
            hash_suffix = hashlib.sha256(str(lab.id).encode()).hexdigest()[:8]
            ns = f"lab-{str(lab.id)[:47]}-{hash_suffix}"
        return ns.lower()

    def _resource_name(self, lab: Lab, suffix: str = "") -> str:
        """Generate resource name from lab ID with optional suffix."""
        name = f"octobox-{lab.id}"
        if suffix:
            name = f"{name}-{suffix}"
        # Ensure DNS-1123 compliance and length limit
        if len(name) > 63:
            hash_suffix = hashlib.sha256(str(lab.id).encode()).hexdigest()[:8]
            name = f"octobox-{str(lab.id)[:39-len(suffix)]}-{hash_suffix}-{suffix}" if suffix else f"octobox-{str(lab.id)[:47]}-{hash_suffix}"
        return name.lower()

    def _labels(self, lab: Lab) -> dict[str, str]:
        """Generate labels for resources (includes lab-id and owner-id for isolation)."""
        return {
            "app": "octobox-beta",
            "app.octolab.io/lab-id": str(lab.id),
            "app.octolab.io/owner-id": str(lab.owner_id),
        }

    def _kubectl_base_args(self, namespace: str | None = None) -> list[str]:
        """Build base kubectl command args."""
        args = ["kubectl"]
        # Use kubeconfig from runtime (higher priority), then from settings, otherwise default
        kubeconfig_to_use = self.kubeconfig_path or settings.kubectl_kubeconfig_path
        if kubeconfig_to_use:
            args.extend(["--kubeconfig", str(kubeconfig_to_use)])

        # Use context from runtime (higher priority), then from settings, otherwise none
        context_to_use = self.context or settings.kubectl_context or settings.octolab_k8s_context
        if context_to_use:
            args.extend(["--context", context_to_use])

        if namespace:
            args.extend(["-n", namespace])
        return args

    def _redact_strings(self, text: str, sensitive_strings: set[str]) -> str:
        """Redact sensitive strings from text."""
        result = text
        for sensitive in sensitive_strings:
            if sensitive:
                result = result.replace(sensitive, "***REDACTED***")
        return result

    def _redact_cmd(self, cmd: list[str], sensitive_strings: set[str]) -> list[str]:
        """Redact sensitive strings from command args."""
        redacted = []
        for arg in cmd:
            redacted_arg = arg
            for sensitive in sensitive_strings:
                if sensitive and sensitive in arg:
                    # Replace the sensitive part but keep the arg structure
                    if "=" in arg:
                        # Handle --from-literal=VNC_PASSWORD=value format
                        key, value = arg.split("=", 1)
                        if sensitive in value:
                            redacted_arg = f"{key}=***REDACTED***"
                    else:
                        # Standalone value arg
                        redacted_arg = "***REDACTED***"
            redacted.append(redacted_arg)
        return redacted

    async def _run_kubectl(self, args: list[str], *, namespace: str | None = None, timeout_s: int | None = None) -> subprocess.CompletedProcess[str]:
        """
        Execute kubectl command with centralized security enforcement and timeout from settings.

        Args:
            args: kubectl subcommand and arguments
            namespace: Optional namespace to target (defaults to none)
            timeout_s: Command timeout in seconds (defaults to settings.kubectl_request_timeout_seconds)

        Returns:
            CompletedProcess with stdout/stderr

        Raises:
            RuntimeError with sanitized message if command fails
        """
        # Validate inputs to prevent command injection
        if not args or not isinstance(args, list):
            raise ValueError("args must be a non-empty list of strings")

        for arg in args:
            if not isinstance(arg, str):
                raise ValueError(f"All command arguments must be strings, got {type(arg)}: {arg}")

        # Build the command with base args including kubeconfig and context
        cmd = self._kubectl_base_args(namespace) + args

        # Use requested timeout or fallback to configured default from settings
        effective_timeout = timeout_s or settings.kubectl_request_timeout_seconds

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,  # Raise CalledProcessError on non-zero exit
                timeout=effective_timeout,
                shell=False,  # Critical security: never use shell=True
            )

        try:
            return await asyncio.to_thread(_run)
        except (CalledProcessError, TimeoutExpired) as e:
            # Sanitize error information before raising
            if isinstance(e, CalledProcessError):
                # Use existing redaction utilities to sanitize the error
                sanitized_error = sanitize_subprocess_error(e)

                # Redact the command args to prevent credential leaks
                redacted_cmd = redact_argv(cmd)

                # Build safe error message without raw outputs
                error_msg = (
                    f"kubectl command failed with exit code {e.returncode}.\n"
                    f"Command: {' '.join(redacted_cmd)}\n"
                    f"Error details logged separately for security."
                )

                logger.error(
                    "kubectl command failed: cmd=%s, returncode=%d",
                    ' '.join(redacted_cmd),
                    e.returncode
                )

                raise RuntimeError(error_msg) from None  # Prevent chaining to hide original exception
            else:  # TimeoutExpired
                redacted_cmd = redact_argv(cmd)

                error_msg = (
                    f"kubectl command timed out after {effective_timeout}s.\n"
                    f"Command: {' '.join(redacted_cmd)}\n"
                    f"This may indicate that the Kubernetes API server is not responding."
                )

                logger.warning(
                    "kubectl command timed out: cmd=%s, timeout=%ds",
                    ' '.join(redacted_cmd),
                    effective_timeout
                )

                raise RuntimeError(error_msg) from None  # Prevent credential leak through exception chaining

    async def _run_kubectl_plumbing(
        self,
        args: list[str],
        namespace: str | None = None,
        timeout_s: int | None = None,
        request_timeout_s: int | None = 30,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """
        Execute kubectl command with secure plumbing and proper error handling.

        Args:
            args: kubectl subcmd and args
            namespace: optional namespace
            timeout_s: overall subprocess timeout
            request_timeout_s: kubectl request timeout
            capture_output: whether to capture stdout/stderr

        Returns:
            CompletedProcess with redacted error details on failure.
        """
        base_args = self._kubectl_base_args(namespace)

        # Insert request timeout after kubectl if not already present
        cmd = base_args.copy()
        # Find position where to insert --request-timeout (after kubectl command)
        if request_timeout_s:
            cmd.insert(1, f"--request-timeout={request_timeout_s}s")

        cmd.extend(args)

        timeout_s = timeout_s or self.kubectl_timeout

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                check=True,  # We want CalledProcessError to be caught and redacted
                timeout=timeout_s,
            )

        try:
            return await asyncio.to_thread(_run)
        except (CalledProcessError, TimeoutExpired) as e:
            if isinstance(e, CalledProcessError):
                # Use redact utilities to sanitize error message
                sanitized_error = sanitize_subprocess_error(e)

                # Build redacted command string
                redacted_cmd = redact_argv(cmd)

                raise RuntimeError(
                    f"kubectl command failed (exit code {e.returncode}):\n"
                    f"Command: {' '.join(redacted_cmd)}\n"
                    f"STDOUT:\n{truncate_text(sanitized_error['stdout'])}\n"
                    f"STDERR:\n{truncate_text(sanitized_error['stderr'])}"
                )
            else:  # TimeoutExpired
                redacted_cmd = redact_argv(cmd)
                raise RuntimeError(
                    f"kubectl command timed out after {timeout_s}s:\n"
                    f"Command: {' '.join(redacted_cmd)}"
                )

    async def _run_kubectl_safe(
        self,
        args: list[str],
        namespace: str | None = None,
        timeout: int | None = None,
        check: bool = True,
        sensitive_strings: set[str] | None = None,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """
        Execute kubectl command safely with redaction support.

        Never raises CalledProcessError (always RuntimeError with redacted output).
        """
        cmd = self._kubectl_base_args(namespace) + args
        timeout_sec = timeout or self.kubectl_timeout
        sensitive = sensitive_strings or set()

        def _run() -> subprocess.CompletedProcess[str]:
            if stdin is not None:
                # Use Popen for stdin support
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = proc.communicate(input=stdin, timeout=timeout_sec)
                result = subprocess.CompletedProcess(
                    cmd, proc.returncode, stdout, stderr
                )
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,  # We handle errors ourselves
                    timeout=timeout_sec,
                )

            if result.returncode != 0 and check:
                # Redact sensitive strings before raising
                redacted_cmd = self._redact_cmd(cmd, sensitive)
                redacted_stdout = self._redact_strings(result.stdout, sensitive)
                redacted_stderr = self._redact_strings(result.stderr, sensitive)

                cmd_str = " ".join(redacted_cmd)
                raise RuntimeError(
                    f"kubectl command failed (exit code {result.returncode}):\n"
                    f"Command: {cmd_str}\n"
                    f"STDOUT:\n{redacted_stdout}\n"
                    f"STDERR:\n{redacted_stderr}"
                )

            return result

        return await asyncio.to_thread(_run)

    async def _kubectl(
        self,
        args: list[str],
        namespace: str | None = None,
        timeout: int | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """
        Execute kubectl command with standardized arguments and security.

        Args:
            args: kubectl subcommand and args (e.g., ["get", "pods"])
            namespace: Optional namespace to target
            timeout: Command timeout in seconds
            check: Whether to raise on non-zero exit (preserved for backward compatibility)

        Returns:
            CompletedProcess with stdout/stderr
        """
        effective_timeout = timeout or self.kubectl_timeout

        try:
            # Use the secure runner with proper error handling
            result = await self._run_kubectl(args, namespace=namespace, timeout_s=effective_timeout)
            return result
        except RuntimeError as e:
            # If check is False, return a CompletedProcess-like object instead of re-raising
            if not check:
                # For compatibility with subprocess.CompletedProcess, return an object with error info
                from subprocess import CompletedProcess
                return CompletedProcess(
                    args=args,
                    returncode=1,
                    stdout="",
                    stderr=str(e)
                )
            else:
                # If check is True (default), re-raise the error
                raise

    async def _kubectl_apply(
        self,
        yaml_content: str,
        namespace: str | None = None,
        resource_hint: str | None = None,
        sensitive_strings: set[str] | None = None,
    ) -> None:
        """
        Apply YAML content via kubectl apply -f -.

        Args:
            yaml_content: YAML content to apply
            namespace: Optional namespace to target
            resource_hint: Hint about resource type (e.g., "secret") for special handling
            sensitive_strings: Set of strings to redact from errors (e.g., passwords)
        """
        # For secrets, never log YAML content and add VNC_PASSWORD to sensitive set
        if resource_hint == "secret":
            sensitive = sensitive_strings or set()
            sensitive.add("VNC_PASSWORD")
            # Never log YAML for secrets
            try:
                await self._run_kubectl(
                    ["apply", "-f", "-"],
                    namespace=namespace,
                    timeout_s=settings.kubectl_request_timeout_seconds,
                )
            except RuntimeError as e:
                # Log error without YAML content
                logger.error(
                    "kubectl apply failed for %s resource (YAML content redacted for security)",
                    resource_hint,
                )
                raise
        else:
            # For non-secrets, log normally but still redact sensitive strings
            # Check for OpenAPI failure and retry with --validate=false
            await self._kubectl_apply_with_retry(
                yaml_content,
                namespace=namespace,
                sensitive_strings=sensitive_strings,
            )

    async def _kubectl_apply_with_retry(
        self,
        yaml_content: str,
        namespace: str | None = None,
        sensitive_strings: set[str] | None = None,
    ) -> None:
        """
        Apply YAML with retry logic for OpenAPI download failures.
        """
        args = ["apply", "-f", "-"]

        try:
            # Use the centralized _run_kubectl method for security and proper timeout handling
            await self._run_kubectl(
                args,
                namespace=namespace,
                timeout_s=settings.kubectl_request_timeout_seconds,
            )
        except RuntimeError as e:
            error_str = str(e)

            # Check if this is an OpenAPI download failure
            if ("failed to download openapi" in error_str.lower() and
                "server is currently unable to handle the request" in error_str.lower()):

                logger.warning("Detected OpenAPI download failure, retrying with --validate=false")

                # Retry with --validate=false
                retry_args = ["apply", "--validate=false", "-f", "-"]
                await self._run_kubectl(
                    retry_args,
                    namespace=namespace,
                    timeout_s=settings.kubectl_request_timeout_seconds,
                )
            else:
                # Re-raise original error if not matching the specific pattern
                raise

    async def _create_namespace(self, lab: Lab) -> None:
        """Create namespace for lab with labels."""
        ns_name = self.ns_name(lab)
        labels = self._labels(lab)

        # Build namespace YAML
        label_pairs = " ".join(f"{k}={v}" for k, v in labels.items())
        yaml_content = f"""apiVersion: v1
kind: Namespace
metadata:
  name: {ns_name}
  labels:
"""
        for key, value in labels.items():
            yaml_content += f"    {key}: {value}\n"

        await self._kubectl_apply(yaml_content)
        logger.info("Created namespace %s for lab %s", ns_name, lab.id)

    async def _create_secret(self, lab: Lab, vnc_password: str) -> None:
        """Create Secret containing VNC password."""
        ns_name = self.ns_name(lab)
        secret_name = self._resource_name(lab, "vnc-secret")

        # Use kubectl create secret with --dry-run=client -o yaml | apply pattern
        # This is idempotent and avoids shell escaping issues
        # Correct format: --from-literal=VNC_PASSWORD=<value> (single arg)
        result = await self._run_kubectl(
            [
                "create",
                "secret",
                "generic",
                secret_name,
                f"--from-literal=VNC_PASSWORD={vnc_password}",
                "--dry-run=client",
                "-o",
                "yaml",
            ],
            namespace=ns_name,
            timeout_s=settings.kubectl_request_timeout_seconds,
        )

        yaml_content = result.stdout

        # Apply the generated YAML (mark as secret resource for special handling)
        await self._kubectl_apply(
            yaml_content,
            namespace=ns_name,
            resource_hint="secret",
            sensitive_strings={vnc_password},
        )
        logger.info("Created Secret %s in namespace %s", secret_name, ns_name)

    def _render_deployment(self, lab: Lab, secret_name: str) -> str:
        """Render Deployment YAML template."""
        ns_name = self.ns_name(lab)
        deployment_name = self._resource_name(lab)
        labels = self._labels(lab)
        label_selector = "app.octolab.io/lab-id"

        # Build label selector string for metadata
        label_str = "\n".join(f"      {k}: {v}" for k, v in labels.items())

        # Use the image from config settings for flexibility
        image_name = getattr(settings, 'octobox_image', 'octobox-beta:dev')

        return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {deployment_name}
  namespace: {ns_name}
  labels:
{label_str}
spec:
  replicas: 1
  selector:
    matchLabels:
      {label_selector}: {lab.id}
  template:
    metadata:
      labels:
{label_str}
    spec:
      containers:
        - name: octobox-beta
          image: {image_name}
          imagePullPolicy: IfNotPresent
          env:
            - name: VNC_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {secret_name}
                  key: VNC_PASSWORD
            - name: VNC_LOCALHOST
              value: "1"
            - name: VNC_RFBPORT
              value: "5900"
            - name: VNC_DISPLAY
              value: ":0"
          volumeMounts:
            - name: evidence
              mountPath: /evidence
          resources:
            requests:
              cpu: "200m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "2Gi"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
        - name: novnc
          image: bonigarcia/novnc:1.3.0
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 6080
              name: novnc
          env:
            - name: VNC_SERVER
              value: "localhost:5900"
            - name: AUTOCONNECT
              value: "true"
            - name: VNC_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {secret_name}
                  key: VNC_PASSWORD
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "200m"
              memory: "256Mi"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
            runAsNonRoot: true
            runAsUser: 1000
            readOnlyRootFilesystem: true
      volumes:
        - name: evidence
          persistentVolumeClaim:
            claimName: {self._resource_name(lab, "evidence")}
"""

    def _render_service(self, lab: Lab) -> str:
        """Render Service YAML template (port 6080 only)."""
        ns_name = self.ns_name(lab)
        service_name = self._resource_name(lab, "novnc")
        deployment_name = self._resource_name(lab)
        labels = self._labels(lab)
        label_selector = "app.octolab.io/lab-id"

        label_str = "\n".join(f"    {k}: {v}" for k, v in labels.items())

        return f"""apiVersion: v1
kind: Service
metadata:
  name: {service_name}
  namespace: {ns_name}
  labels:
{label_str}
spec:
  type: ClusterIP
  selector:
    {label_selector}: {lab.id}
  ports:
    - name: novnc
      port: 6080
      targetPort: 6080
      protocol: TCP
  # NOTE: VNC port 5900 is NOT exposed via this Service.
  # VNC is bound to localhost inside the pod and only accessible via the noVNC sidecar.
"""

    def _render_pvc(self, lab: Lab) -> str:
        """Render PVC YAML template."""
        ns_name = self.ns_name(lab)
        pvc_name = self._resource_name(lab, "evidence")
        labels = self._labels(lab)

        label_str = "\n".join(f"    {k}: {v}" for k, v in labels.items())

        return f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {pvc_name}
  namespace: {ns_name}
  labels:
{label_str}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
"""

    def _render_ingress(self, lab: Lab, service_name: str) -> str:
        """Render Ingress YAML template (optional)."""
        ns_name = self.ns_name(lab)
        ingress_name = self._resource_name(lab, "novnc")
        labels = self._labels(lab)
        host = f"lab-{lab.id}.{self.base_domain}"

        label_str = "\n".join(f"    {k}: {v}" for k, v in labels.items())

        return f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {ingress_name}
  namespace: {ns_name}
  labels:
{label_str}
  annotations:
    traefik.ingress.kubernetes.io/service-upgrade: "websocket"
    traefik.ingress.kubernetes.io/request-timeout: "300s"
spec:
  ingressClassName: traefik
  rules:
    - host: {host}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {service_name}
                port:
                  number: 6080
"""

    async def _wait_for_deployment_ready(
        self,
        lab: Lab,
        timeout: int = 180,
    ) -> None:
        """Wait for deployment to be ready."""
        ns_name = self.ns_name(lab)
        deployment_name = self._resource_name(lab)

        # Use kubectl rollout status with timeout, with secure execution
        args = [
            "rollout",
            "status",
            f"deployment/{deployment_name}",
            f"--timeout={timeout}s",
        ]

        # Use centralized kubectl runner for security and proper timeout handling
        await self._run_kubectl(args, namespace=ns_name, timeout_s=timeout + 10)
        logger.info("Deployment %s in namespace %s is ready", deployment_name, ns_name)

    async def _check_apiserver_ready(self) -> bool:
        """Check if apiserver is ready by calling /readyz endpoint."""
        try:
            # Run kubectl get --raw='/readyz' with a tight timeout
            result = await self._run_kubectl(
                ["get", "--raw", "/readyz"],
                timeout_s=5,  # Tight timeout for readiness check
            )
            return True
        except RuntimeError:
            # If we get an error (e.g., connection refused), apiserver is not ready
            return False

    async def _check_apiserver_readiness_with_detection(self) -> Tuple[bool, str]:
        """
        Check if apiserver is ready using the cluster detector helper.
        Returns (is_ready, message) with actionable information.
        """
        try:
            is_ready, message = await asyncio.get_event_loop().run_in_executor(
                None,
                check_apiserver_readiness
            )
            return is_ready, message
        except Exception as e:
            # Use direct detection fallback
            _, _, cluster_type = await asyncio.get_event_loop().run_in_executor(
                None,
                detect_cluster_type
            )
            return False, f"API server unreachable (detected: {cluster_type}): {type(e).__name__}"

    async def create_lab(self, lab: Lab, recipe: Recipe) -> None:  # noqa: ARG002
        """
        Provision lab resources in Kubernetes.

        Creates:
        - Namespace (lab-{lab.id})
        - Secret (VNC password)
        - PVC (evidence storage)
        - Deployment (octobox + novnc)
        - Service (port 6080)
        - Ingress (optional, if enabled)
        """
        # Preflight check: ensure apiserver is ready before starting provisioning
        if not await self._check_apiserver_ready():
            raise RuntimeError(
                "Kubernetes apiserver is not ready. Cannot provision lab at this time. "
                "Please try again later when the control plane is available."
            )

        ns_name = self.ns_name(lab)

        # Generate random VNC password
        vnc_password = secrets.token_urlsafe(16)[:16]  # 16 chars, URL-safe
        logger.info("Generated VNC password for lab %s", lab.id)

        # Create namespace
        await self._create_namespace(lab)

        # Create Secret
        secret_name = self._resource_name(lab, "vnc-secret")
        await self._create_secret(lab, vnc_password)

        # Create PVC
        pvc_yaml = self._render_pvc(lab)
        await self._kubectl_apply(pvc_yaml, namespace=ns_name)

        # Create Deployment
        deployment_yaml = self._render_deployment(lab, secret_name)
        await self._kubectl_apply(deployment_yaml, namespace=ns_name)

        # Create Service
        service_name = self._resource_name(lab, "novnc")
        service_yaml = self._render_service(lab)
        await self._kubectl_apply(service_yaml, namespace=ns_name)

        # Create Ingress (if enabled)
        if self.ingress_enabled:
            ingress_yaml = self._render_ingress(lab, service_name)
            await self._kubectl_apply(ingress_yaml, namespace=ns_name)

        # Wait for deployment to be ready
        await self._wait_for_deployment_ready(lab)

        logger.info("Lab %s provisioned successfully in namespace %s", lab.id, ns_name)

    class NamespaceVerificationResult:
        """Enum-like class for namespace verification results."""
        NOT_FOUND = "not_found"
        MISMATCH = "mismatch"
        OK = "ok"

    async def _verify_namespace_labels(self, lab: Lab, ns_name: str) -> str:
        """
        Verify namespace has expected labels matching lab.

        Security check: ensures we're deleting the correct namespace.

        Returns:
            NamespaceVerificationResult: NOT_FOUND, MISMATCH, or OK
        """
        try:
            result = await self._kubectl(
                ["get", "namespace", ns_name, "-o", "jsonpath={.metadata.labels}"],
                check=False,
            )
            if result.returncode != 0:
                logger.warning("Namespace %s not found or inaccessible", ns_name)
                return self.NamespaceVerificationResult.NOT_FOUND

            # Parse labels (format: key1=value1 key2=value2)
            labels_str = result.stdout.strip()
            labels = {}
            for pair in labels_str.split():
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    labels[key] = value

            # Verify critical labels match
            expected_lab_id = str(lab.id)
            expected_owner_id = str(lab.owner_id)

            if labels.get("app.octolab.io/lab-id") != expected_lab_id:
                logger.error(
                    "Namespace %s lab-id label mismatch: expected %s, got %s",
                    ns_name,
                    expected_lab_id,
                    labels.get("app.octolab.io/lab-id"),
                )
                return self.NamespaceVerificationResult.MISMATCH

            if labels.get("app.octolab.io/owner-id") != expected_owner_id:
                logger.error(
                    "Namespace %s owner-id label mismatch: expected %s, got %s",
                    ns_name,
                    expected_owner_id,
                    labels.get("app.octolab.io/owner-id"),
                )
                return self.NamespaceVerificationResult.MISMATCH

            return self.NamespaceVerificationResult.OK
        except Exception as e:
            logger.exception("Failed to verify namespace labels: %s", e)
            return self.NamespaceVerificationResult.MISMATCH  # Treat as security failure

    async def destroy_lab(self, lab: Lab) -> None:
        """
        Tear down lab resources by deleting namespace.

        Security: Verifies namespace labels match lab before deletion.
        If namespace doesn't exist, treats as no-op (safe).
        If labels mismatch, hard fails (security safeguard).
        """
        ns_name = self.ns_name(lab)

        # Check if namespace exists first
        namespace_check_result = await self._kubectl(
            ["get", "namespace", ns_name, "-o", "jsonpath={.metadata.name}"],
            check=False,
        )

        if namespace_check_result.returncode != 0:
            # Namespace doesn't exist - treat as no-op success
            logger.info(
                "Namespace %s does not exist for lab %s; "
                "treating as no-op (already destroyed)",
                ns_name,
                lab.id,
            )
            return

        # Namespace exists - verify labels match for security
        verification_result = await self._verify_namespace_labels(lab, ns_name)

        if verification_result == self.NamespaceVerificationResult.MISMATCH:
            raise RuntimeError(
                f"Security violation: Namespace {ns_name} labels do not match lab {lab.id}. "
                "Refusing to delete for safety. This indicates a potential cross-tenant access attempt."
            )
        elif verification_result == self.NamespaceVerificationResult.NOT_FOUND:
            # This case shouldn't happen since we already confirmed the namespace exists,
            # but handle it for completeness
            logger.info(
                "Namespace %s does not exist for lab %s; treating as no-op",
                ns_name,
                lab.id,
            )
            return
        elif verification_result == self.NamespaceVerificationResult.OK:
            # Proceed with deletion
            # Delete namespace (cascades to all resources)
            try:
                await self._kubectl(
                    ["delete", "namespace", ns_name],
                    timeout=120,  # Namespace deletion can take time
                    check=True,  # Raise exception if deletion fails
                )
                logger.info("Deleted namespace %s for lab %s", ns_name, lab.id)
            except Exception as e:
                logger.exception("Error deleting namespace %s: %s", ns_name, e)
                raise
        else:
            # Should not happen - unknown verification result
            raise RuntimeError(f"Unknown verification result: {verification_result}")

    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """
        Check if Kubernetes resources exist for a lab.

        Uses kubectl to check if the namespace exists.
        Short timeout (5s) to prevent blocking during reconciliation.

        Args:
            lab: Lab model instance

        Returns:
            True if namespace exists, False otherwise
        """
        ns_name = self.ns_name(lab)

        try:
            result = await self._kubectl(
                ["get", "namespace", ns_name, "-o", "jsonpath={.metadata.name}"],
                check=False,
                timeout=5,
            )

            exists = result.returncode == 0

            if exists:
                logger.debug(f"Resources exist for lab {lab.id}: namespace {ns_name} found")
            else:
                logger.debug(f"No resources found for lab {lab.id}: namespace {ns_name} not found")

            return exists

        except Exception as e:
            logger.warning(f"Error checking resources for lab {lab.id}: {type(e).__name__}; assuming exist")
            return True  # Conservative: assume exist on error

