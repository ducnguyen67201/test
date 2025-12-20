"""Runtime package exports."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.runtime.base import LabRuntime
from app.runtime.compose_runtime import ComposeLabRuntime
from app.runtime.k8s_runtime import K8sLabRuntime
from app.runtime.noop import NoopRuntime


def _resolve_compose_path() -> Path:
    env_path = os.environ.get("OCTOLAB_COMPOSE_PATH")
    if env_path:
        return Path(env_path).expanduser()

    if settings.hackvm_dir:
        candidate = Path(settings.hackvm_dir).expanduser() / "octolab-hackvm" / "docker-compose.yml"
        if candidate.exists():
            return candidate

    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "octolab-hackvm" / "docker-compose.yml"


def get_runtime_for_type(runtime_type: str) -> LabRuntime:
    """Return a runtime implementation for the specified type.

    Unlike get_runtime() which returns a cached singleton based on settings,
    this function returns a runtime for a specific type. Used by teardown worker
    to tear down labs using their stored runtime type (not the global setting).

    Args:
        runtime_type: One of "firecracker", "compose", "k8s", "noop"

    Returns:
        LabRuntime instance for the specified type

    SECURITY:
    - Does NOT cache - returns fresh instance each call
    - Does NOT check APP_ENV restrictions (labs were already created under those rules)
    """
    if runtime_type == "noop":
        return NoopRuntime()

    if runtime_type == "k8s":
        kubeconfig = settings.octolab_k8s_kubeconfig
        kubeconfig_path = Path(kubeconfig).expanduser() if kubeconfig else None
        return K8sLabRuntime(
            kubeconfig_path=kubeconfig_path,
            context=settings.octolab_k8s_context,
            ingress_enabled=settings.octolab_k8s_ingress_enabled,
            base_domain=settings.octolab_k8s_base_domain,
        )

    if runtime_type == "firecracker":
        from app.runtime.firecracker_runtime import FirecrackerLabRuntime
        return FirecrackerLabRuntime()

    if runtime_type == "compose":
        compose_path = _resolve_compose_path()
        return ComposeLabRuntime(compose_path)

    # Fallback: return noop for unknown types (shouldn't happen)
    return NoopRuntime()


@lru_cache(maxsize=1)
def get_runtime() -> LabRuntime:
    """Return the singleton runtime implementation.

    Runtime selection is controlled by OCTOLAB_RUNTIME config (already validated):
    - "firecracker": Firecracker microVM based labs (DEFAULT, production-required)
    - "compose": Docker Compose based labs (DEV/TEST ONLY)
    - "k8s": Kubernetes based labs (DEV/TEST ONLY)
    - "noop": No-op for testing

    SECURITY:
    - Default is firecracker for production-safe multi-tenant isolation
    - Production (APP_ENV=production) ONLY allows firecracker/noop
    - Compose/k8s blocked in production - raises RuntimeError
    - Firecracker requires additional preflight checks (done in main.py lifespan)
    """
    # Use validated settings (no env fallback here - validation already done)
    runtime_choice = settings.octolab_runtime

    if runtime_choice == "noop":
        return NoopRuntime()

    if runtime_choice == "k8s":
        # SECURITY: k8s is dev/test only - production requires firecracker
        app_env = settings.app_env.lower()
        if app_env == "production":
            raise RuntimeError(
                "K8s runtime is blocked in production. "
                "Set OCTOLAB_RUNTIME=firecracker for multi-tenant isolation."
            )
        kubeconfig = settings.octolab_k8s_kubeconfig
        kubeconfig_path = Path(kubeconfig).expanduser() if kubeconfig else None
        return K8sLabRuntime(
            kubeconfig_path=kubeconfig_path,
            context=settings.octolab_k8s_context,
            ingress_enabled=settings.octolab_k8s_ingress_enabled,
            base_domain=settings.octolab_k8s_base_domain,
        )

    if runtime_choice == "firecracker":
        # Lazy import to avoid loading firecracker code when not needed
        from app.runtime.firecracker_runtime import FirecrackerLabRuntime
        return FirecrackerLabRuntime()

    if runtime_choice == "compose":
        # SECURITY: Compose is dev/test only - production requires firecracker
        app_env = settings.app_env.lower()
        if app_env == "production":
            raise RuntimeError(
                "Compose runtime is blocked in production. "
                "Set OCTOLAB_RUNTIME=firecracker for multi-tenant isolation."
            )
        compose_path = _resolve_compose_path()
        return ComposeLabRuntime(compose_path)

    # This should never happen - settings validation catches invalid runtimes
    raise RuntimeError(
        f"Unknown runtime: {runtime_choice!r}. This indicates a bug - "
        "settings validation should have caught this."
    )
