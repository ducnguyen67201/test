"""Application configuration from environment variables.

Pydantic v2 + pydantic-settings modernized configuration.

SECURITY:
- Secrets use SecretStr to prevent accidental logging
- Runtime selection is explicit (fail-closed)
- No import-time side effects (safe for alembic)
- Env file path is deterministic (based on __file__, not CWD)
"""

from pathlib import Path
from typing import Final, Literal, Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# Path Resolution (deterministic, independent of CWD)
# =============================================================================
# Compute paths based on THIS FILE's location, not the current working directory.
# This ensures alembic can run from any directory.
CONFIG_DIR = Path(__file__).resolve().parent  # app/
BACKEND_DIR = CONFIG_DIR.parent  # backend/
ENV_FILE = BACKEND_DIR / ".env"  # Single consolidated env file

# =============================================================================
# Runtime Type Definition
# =============================================================================
# Valid runtime values (module-level constant, not a Pydantic field)
VALID_RUNTIMES: Final[frozenset[str]] = frozenset({
    "compose",
    "firecracker",
    "microvm",  # Alias for firecracker
    "k8s",
    "noop",
})

# =============================================================================
# Canonical MicroVM Paths (single source of truth)
# =============================================================================
# These defaults match deploy paths in infra/firecracker/build-rootfs.sh
MICROVM_DEFAULT_KERNEL_PATH: Final[str] = "/var/lib/octolab/firecracker/vmlinux"
MICROVM_DEFAULT_ROOTFS_PATH: Final[str] = "/var/lib/octolab/firecracker/rootfs.ext4"

# Type alias for runtime (used for validation)
RuntimeName = Literal["compose", "firecracker", "microvm", "k8s", "noop"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    SECURITY:
    - Secrets use SecretStr to prevent accidental logging
    - Runtime selection requires explicit OCTOLAB_RUNTIME (no default fallback)
    - All validation happens at instantiation, not import time
    """

    # =========================================================================
    # Pydantic Settings Configuration
    # =========================================================================
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Environment
    # =========================================================================
    app_env: str = "dev"  # Environment: dev, test, staging, production

    # =========================================================================
    # Database
    # =========================================================================
    database_url: str
    hackvm_dir: Optional[str] = None

    # =========================================================================
    # Application metadata
    # =========================================================================
    app_name: str = "OctoLab"
    app_version: str = "0.1.0"

    # =========================================================================
    # Logging
    # =========================================================================
    log_level: str = "INFO"

    # =========================================================================
    # JWT Authentication
    # =========================================================================
    # SECURITY: Use SecretStr to prevent accidental logging
    secret_key: SecretStr  # JWT signing secret
    algorithm: str = "HS256"  # JWT algorithm
    access_token_expire_minutes: int = 30  # Token expiration in minutes

    # =========================================================================
    # Service Token (for internal frontend-to-backend calls)
    # =========================================================================
    # SECURITY: Optional shared secret for service-to-service auth
    # Used by octo-web frontend to call backend APIs on behalf of users
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    service_token: Optional[SecretStr] = Field(default=None, validation_alias="OCTOLAB_SERVICE_TOKEN")

    # =========================================================================
    # Self-service Registration
    # =========================================================================
    # SECURITY: Default false; enable in dev via ALLOW_SELF_SIGNUP=true in .env.local
    allow_self_signup: bool = False

    # =========================================================================
    # Admin Authorization
    # =========================================================================
    # Comma-separated list of admin email addresses for privileged operations
    # Example: OCTOLAB_ADMIN_EMAILS=admin@example.com,ops@example.com
    # SECURITY: Empty means no admin access. Never trust client-supplied admin claims.
    admin_emails_raw: str = Field(default="", validation_alias="OCTOLAB_ADMIN_EMAILS")

    @property
    def admin_emails(self) -> set[str]:
        """Parse admin emails from raw config string.

        Returns:
            Set of lowercase, trimmed admin email addresses.
            Empty set if not configured.

        Example:
            " A@B.com,  c@d.com ,, " => {"a@b.com", "c@d.com"}
        """
        if not self.admin_emails_raw:
            return set()
        return {
            email.strip().lower()
            for email in self.admin_emails_raw.split(",")
            if email.strip()
        }

    # =========================================================================
    # Notification Settings (Slack & Discord Webhooks)
    # =========================================================================
    # Slack webhook URL for alerts (optional)
    # Create at: https://api.slack.com/messaging/webhooks
    slack_webhook_url: Optional[str] = Field(
        default=None, validation_alias="OCTOLAB_SLACK_WEBHOOK_URL"
    )

    # Discord webhook URL for alerts (optional)
    # Create in Discord: Server Settings > Integrations > Webhooks > New Webhook
    discord_webhook_url: Optional[str] = Field(
        default=None, validation_alias="OCTOLAB_DISCORD_WEBHOOK_URL"
    )

    # Minimum pass rate threshold (0-100) - alerts sent when below this
    # Default 100 = alert on any failure, 90 = alert if <90% pass rate
    cve_verify_alert_threshold: int = Field(
        default=100, validation_alias="OCTOLAB_CVE_ALERT_THRESHOLD"
    )

    @property
    def notifications_enabled(self) -> bool:
        """Check if any notification channel is configured."""
        return bool(self.slack_webhook_url or self.discord_webhook_url)

    # =========================================================================
    # VNC / noVNC Configuration
    # =========================================================================
    vnc_base_url: str = "http://localhost:6080/vnc.html"
    novnc_bind_addr: str = "127.0.0.1"
    novnc_port_min: int = 30000
    novnc_port_max: int = 39999
    hackvm_public_host: str = "localhost"

    # =========================================================================
    # Kubernetes Runtime Configuration
    # =========================================================================
    octolab_k8s_kubeconfig: Optional[str] = None
    octolab_k8s_context: Optional[str] = None
    octolab_k8s_ingress_enabled: bool = False
    octolab_k8s_base_domain: str = "octolab.local"
    octobox_image: str = "octobox-beta:dev"

    # Kubernetes Context Selection for Runtime
    kubectl_context: Optional[str] = None
    kubectl_request_timeout_seconds: int = 5
    kubectl_kubeconfig_path: Optional[str] = None

    # =========================================================================
    # Compose Runtime Configuration
    # =========================================================================
    hackvm_compose_path: Optional[str] = None
    compose_port_min: int = 30000
    compose_port_max: int = 39999
    compose_bind_host: str = "127.0.0.1"
    retain_failed_labs: bool = Field(
        default=False,
        validation_alias="OCTOLAB_RETAIN_FAILED_LABS",
        description="Retain compose resources on provisioning failure for debugging",
    )

    # VNC Authentication Mode
    # SECURITY: "none" mode ONLY allowed when compose_bind_host is localhost
    vnc_auth_mode: str = "none"

    # Dev-only: Force cmdlog layer rebuild
    dev_force_cmdlog_rebuild: bool = False

    # Teardown timeout
    teardown_timeout_seconds: int = 600

    # =========================================================================
    # noVNC Readiness Probe Configuration
    # =========================================================================
    novnc_ready_gating_enabled: bool = True
    novnc_ready_timeout_seconds: int = 120
    novnc_ready_poll_interval_seconds: float = 1.0
    novnc_ready_paths: list[str] = ["vnc.html", "vnc_lite.html", ""]

    # Lab Startup Timeout
    # Firecracker labs: boot ~20-70s (single/concurrent), image load ~80-150s, compose ~20s
    # Total: ~120-240s, so 5 minutes (300s) provides comfortable margin
    lab_startup_timeout_seconds: int = 300

    # =========================================================================
    # Evidence Configuration
    # =========================================================================
    # SECURITY: Use SecretStr for HMAC secret
    evidence_hmac_secret: Optional[SecretStr] = None
    evidence_export_timeout_seconds: int = 120
    evidence_seal_timeout_seconds: int = 60
    evidence_tlog_reader: str = "volume_tar"

    # =========================================================================
    # Cost Guardrails: Quotas and TTL
    # =========================================================================
    max_active_labs_per_user: int = 2
    max_lab_creates_per_hour_per_user: int = 10
    default_lab_ttl_minutes: int = 120
    evidence_retention_hours: int = 72
    evidence_retention_days: int = 7
    max_log_lines_per_container: int = 2000
    max_evidence_zip_mb: int = 200

    # Container Health Check Timeout
    container_health_timeout_seconds: int = 90

    # =========================================================================
    # Teardown Worker Configuration
    # =========================================================================
    teardown_worker_enabled: bool = True
    teardown_worker_interval_seconds: float = 5.0
    teardown_worker_batch_size: int = 3
    teardown_worker_startup_tick: bool = True

    # =========================================================================
    # Internal API Token
    # =========================================================================
    # SECURITY: Use SecretStr for internal token
    internal_token: Optional[SecretStr] = None

    # =========================================================================
    # Falco Ingestion Configuration
    # =========================================================================
    falco_rate_limit_per_lab: int = 100
    falco_dedup_ttl_seconds: int = 60
    falco_max_batch_size: int = 100

    # =========================================================================
    # Apache Guacamole Configuration
    # =========================================================================
    guac_enabled: bool = False
    guac_base_url: str = "http://127.0.0.1:8081/guacamole"
    # Public URL for Guacamole (returned to browser). Use relative URL for nginx proxy.
    guac_public_url: str = "/guacamole"
    guac_admin_user: str = "guacadmin"
    # SECURITY: Use SecretStr for passwords and encryption keys
    guac_admin_password: Optional[SecretStr] = None
    guac_enc_key: Optional[SecretStr] = None
    guacd_container_name: str = "octolab-guacd"

    # =========================================================================
    # Docker Network Cleanup Configuration
    # =========================================================================
    control_plane_containers: list[str] = ["octolab-guacd"]
    docker_network_timeout_seconds: int = 30
    net_rm_max_retries: int = 6
    net_rm_backoff_ms: int = 200

    # =========================================================================
    # Firecracker microVM Runtime Configuration
    # =========================================================================
    # SECURITY: Default is firecracker (production-safe). Compose only in dev/test.
    # Valid values: "firecracker", "microvm", "compose", "k8s", "noop"
    octolab_runtime: str = Field(
        default="firecracker",
        description="Lab runtime. Only 'firecracker' is supported in production.",
    )

    # State directory for per-lab VM data
    microvm_state_dir: str = "/var/lib/octolab/microvm"

    # Paths to firecracker/jailer binaries
    firecracker_bin: str = "firecracker"
    jailer_bin: str = "jailer"

    # SECURITY: Dev-only override to allow running without jailer (DANGEROUS)
    dev_unsafe_allow_no_jailer: bool = False

    # WSL jailer policy: controls whether smoke test uses jailer
    # - None (default): auto-detect (False on WSL, True on native Linux if jailer present)
    # - True: always use jailer
    # - False: never use jailer (for WSL dev or debugging)
    # SECURITY: Production should always use jailer. WSL cannot run jailer.
    microvm_use_jailer: Optional[bool] = None

    # Kernel and rootfs paths for guest VM
    # Defaults match deploy paths in infra/firecracker/build-rootfs.sh
    microvm_kernel_path: str = MICROVM_DEFAULT_KERNEL_PATH
    microvm_rootfs_base_path: str = MICROVM_DEFAULT_ROOTFS_PATH

    # vsock configuration
    microvm_vsock_port: int = 5000

    # Network daemon (netd) socket path
    # The backend connects to this socket to request bridge/tap creation
    # This socket is served by microvm-netd running as root
    microvm_netd_sock: str = "/run/octolab/microvm-netd.sock"

    # Timeouts
    microvm_boot_timeout_secs: int = 20
    microvm_cmd_timeout_secs: int = 120  # Default command timeout
    microvm_compose_timeout_secs: int = 600  # Longer timeout for compose_up (10 min)
    microvm_diag_timeout_secs: int = 30  # Short timeout for diag command

    # Output limits (DoS prevention)
    microvm_max_output_bytes: int = 65536

    # VM resource limits
    microvm_vcpu_count: int = 1
    microvm_mem_size_mib: int = 512

    # =========================================================================
    # Validators
    # =========================================================================

    @field_validator("octolab_runtime", mode="after")
    @classmethod
    def validate_runtime(cls, v: str) -> str:
        """Validate and normalize runtime selection.

        SECURITY:
        - Invalid runtime values are rejected here (Literal type + validator)
        - Production enforcement happens in enforce_firecracker_in_prod
        """
        runtime_lower = v.lower().strip()
        if runtime_lower not in VALID_RUNTIMES:
            raise ValueError(
                f"OCTOLAB_RUNTIME={v!r} is invalid. "
                f"Valid values: {', '.join(sorted(VALID_RUNTIMES))}. "
                "No fallback allowed."
            )

        # Normalize: "microvm" -> "firecracker"
        if runtime_lower == "microvm":
            return "firecracker"
        return runtime_lower

    @field_validator("octolab_runtime", mode="after")
    @classmethod
    def enforce_firecracker_in_prod(cls, v: str, info) -> str:
        """Block compose runtime in production.

        SECURITY: Multi-tenant isolation requires Firecracker microVMs.
        Compose runtime is only allowed in dev/test environments.
        """
        app_env = info.data.get("app_env", "dev")
        if app_env.lower() == "production" and v not in ("firecracker", "noop"):
            raise ValueError(
                f"Production requires OCTOLAB_RUNTIME=firecracker. "
                f"Got '{v}'. Compose/k8s only allowed in dev/test environments."
            )
        return v

    @field_validator("compose_port_min", "compose_port_max", mode="after")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Validate port is in valid range."""
        if v < 1024 or v > 65535:
            raise ValueError(f"Port must be between 1024 and 65535, got {v}")
        return v

    def model_post_init(self, __context) -> None:
        """Post-init validation for cross-field constraints."""
        # Validate compose port range relationship
        if self.compose_port_min >= self.compose_port_max:
            raise ValueError(
                f"compose_port_min ({self.compose_port_min}) must be less than "
                f"compose_port_max ({self.compose_port_max})"
            )

        # SECURITY: Require HMAC secret in production environments
        if self.app_env.lower() not in ("dev", "test") and not self.evidence_hmac_secret:
            raise ValueError(
                f"EVIDENCE_HMAC_SECRET is required in {self.app_env} environment. "
                "Set via environment variable. NEVER log the secret value."
            )

        # SECURITY: Require Guacamole secrets when enabled in production
        if self.guac_enabled:
            if not self.guac_enc_key:
                raise ValueError(
                    "GUAC_ENC_KEY is required when GUAC_ENABLED=true. "
                    'Generate with: python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"'
                )
            if self.app_env.lower() not in ("dev", "test") and not self.guac_admin_password:
                raise ValueError(
                    f"GUAC_ADMIN_PASSWORD is required when GUAC_ENABLED=true "
                    f"in {self.app_env} environment."
                )


# =============================================================================
# Global Settings Instance
# =============================================================================
# Instantiated at import time. This is intentional for FastAPI patterns.
# SECURITY: All validation happens in __init__, not side effects like doctor checks.
settings = Settings()
