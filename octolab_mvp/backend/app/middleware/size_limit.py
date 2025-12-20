"""Request size limit middleware for OctoLab.

Prevents denial-of-service attacks by limiting request body size.
Applied to specific routes (e.g., Falco ingestion endpoint).
"""

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Default limit: 1MB (for Falco ingestion)
DEFAULT_SIZE_LIMIT_BYTES = 1 * 1024 * 1024


class SizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce request body size limits on specific paths.

    Usage:
        app.add_middleware(
            SizeLimitMiddleware,
            path_limits={
                "/internal/falco/ingest": 1 * 1024 * 1024,  # 1MB
            }
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        path_limits: dict[str, int] | None = None,
        default_limit: int | None = None,
    ):
        """Initialize middleware.

        Args:
            app: The ASGI application
            path_limits: Dictionary mapping path prefixes to size limits in bytes
            default_limit: Default limit for unlisted paths (None = no limit)
        """
        super().__init__(app)
        self.path_limits = path_limits or {}
        self.default_limit = default_limit

    def get_limit_for_path(self, path: str) -> int | None:
        """Get the size limit for a given path.

        Returns:
            Size limit in bytes, or None if no limit applies.
        """
        for prefix, limit in self.path_limits.items():
            if path.startswith(prefix):
                return limit
        return self.default_limit

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request, checking body size against limits."""
        limit = self.get_limit_for_path(request.url.path)

        if limit is None:
            # No limit for this path
            return await call_next(request)

        # Check Content-Length header first (fast path)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > limit:
                    logger.warning(
                        f"Request body too large: {length} bytes > {limit} bytes limit "
                        f"for path {request.url.path}"
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large. Maximum size: {limit} bytes"
                        },
                    )
            except ValueError:
                pass  # Invalid Content-Length, continue to streaming check

        # For requests without Content-Length or chunked encoding,
        # we need to read the body incrementally
        # Note: This consumes the body, so we need to reconstruct it
        body_chunks = []
        total_size = 0

        async for chunk in request.stream():
            total_size += len(chunk)
            if total_size > limit:
                logger.warning(
                    f"Request body exceeded limit during streaming: {total_size} bytes > "
                    f"{limit} bytes limit for path {request.url.path}"
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request body too large. Maximum size: {limit} bytes"
                    },
                )
            body_chunks.append(chunk)

        # Reconstruct the body for the endpoint
        body = b"".join(body_chunks)

        # Create a new request with the body we've read
        async def receive():
            return {"type": "http.request", "body": body}

        request._receive = receive

        return await call_next(request)
