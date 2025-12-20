"""noVNC readiness probe for server-side gating.

This module provides server-side readiness checking for noVNC endpoints
to ensure labs are only marked READY when actually reachable.

Security:
- Only probes server-controlled host:port combinations
- Does not fetch arbitrary user-provided URLs
- Uses short timeouts to prevent hanging
- No secrets in logs
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class NovncNotReady(Exception):
    """Raised when noVNC endpoint is not ready within timeout."""

    pass


async def probe_novnc_ready(
    host: str,
    port: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
    paths: list[str],
) -> str:
    """Probe noVNC endpoint for readiness.

    Attempts TCP connection + HTTP GET until success or timeout.

    Args:
        host: Server-controlled hostname (e.g., "127.0.0.1")
        port: Server-allocated port (e.g., 38044)
        timeout_seconds: Total timeout for all probe attempts
        poll_interval_seconds: Delay between probe attempts
        paths: List of HTTP paths to test (e.g., ["vnc.html", ""])

    Returns:
        The successfully probed URL path (e.g., "vnc.html")

    Raises:
        NovncNotReady: If endpoint not reachable within timeout

    Security:
        - Only builds URLs from server-controlled inputs
        - No user-provided URLs are fetched
        - Short per-attempt timeouts prevent hanging
    """
    start_time = datetime.now(timezone.utc)
    deadline = start_time.timestamp() + timeout_seconds
    attempt = 0

    # Ensure paths list is not empty
    if not paths:
        paths = [""]

    while datetime.now(timezone.utc).timestamp() < deadline:
        attempt += 1
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        # Try TCP connect first (faster failure if port not listening)
        try:
            await asyncio.wait_for(
                _tcp_probe(host, port),
                timeout=min(5.0, timeout_seconds - elapsed),
            )
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError) as e:
            logger.debug(
                f"TCP probe failed for {host}:{port} (attempt {attempt}, "
                f"elapsed {elapsed:.1f}s): {type(e).__name__}"
            )
            # Wait before retry
            await asyncio.sleep(poll_interval_seconds)
            continue

        # TCP connected, try HTTP GET on each path
        for path in paths:
            try:
                # Build URL from server-controlled components only
                url = f"http://{host}:{port}/{path.lstrip('/')}" if path else f"http://{host}:{port}/"

                await asyncio.wait_for(
                    _http_probe(url),
                    timeout=min(10.0, timeout_seconds - elapsed),
                )

                # Success!
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.info(
                    f"noVNC readiness probe succeeded for {host}:{port}/{path} "
                    f"(attempt {attempt}, elapsed {elapsed:.1f}s)"
                )
                return path

            except (asyncio.TimeoutError, OSError, Exception) as e:
                logger.debug(
                    f"HTTP probe failed for {host}:{port}/{path}: {type(e).__name__}"
                )
                # Try next path
                continue

        # All paths failed, wait before retry
        await asyncio.sleep(poll_interval_seconds)

    # Timeout exceeded
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    raise NovncNotReady(
        f"noVNC endpoint {host}:{port} not ready after {elapsed:.1f}s "
        f"({attempt} attempts, timeout {timeout_seconds}s)"
    )


async def _tcp_probe(host: str, port: int) -> None:
    """Attempt TCP connection to host:port.

    Raises:
        OSError/ConnectionRefusedError: If connection fails
    """
    reader, writer = await asyncio.open_connection(host, port)
    writer.close()
    await writer.wait_closed()


async def _http_probe(url: str) -> None:
    """Attempt HTTP GET to URL.

    Uses asyncio subprocess curl for simplicity (no external HTTP library needed).
    Accepts 200, 301, 302 as success (noVNC may redirect).

    Args:
        url: Server-controlled URL to probe

    Raises:
        Exception: If HTTP request fails or returns unexpected status
    """
    # Use curl via subprocess for HTTP check (simpler than adding httpx dependency)
    # -s: silent, -o /dev/null: discard body, -w %{http_code}: output status code only
    # --max-time: timeout per request
    proc = await asyncio.create_subprocess_exec(
        "curl",
        "-s",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        "5",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise Exception(f"curl failed with return code {proc.returncode}")

    status_code = stdout.decode().strip()

    # Accept 2xx and 3xx as success (noVNC may redirect to vnc.html)
    if status_code.startswith("2") or status_code.startswith("3"):
        return

    raise Exception(f"HTTP status {status_code} not acceptable")
