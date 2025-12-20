#!/usr/bin/env python3
"""End-to-end verification for user registration.

Verifies:
1. OpenAPI includes /auth/register endpoint
2. Registration creates user and returns token (when ALLOW_SELF_SIGNUP=true)
3. Token works for /auth/me
4. Duplicate registration returns 409

SECURITY: Never prints full tokens or passwords.

Usage:
    python3 dev/scripts/e2e_register_verify.py

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import json
import secrets
import subprocess
import sys
from typing import Any


def redact_token(token: str, visible_chars: int = 8) -> str:
    """Redact token for safe display."""
    if not token:
        return "<empty>"
    if len(token) <= visible_chars:
        return "****"
    return token[:visible_chars] + "****"


def run_curl(
    method: str,
    url: str,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict | str]:
    """Run curl command and return status code + response.

    Args:
        method: HTTP method
        url: URL to request
        data: JSON body data
        headers: Additional headers
        timeout: Request timeout

    Returns:
        Tuple of (status_code, response_data)
    """
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method, url]

    if data:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])

    if headers:
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        output = result.stdout.strip()
        lines = output.split("\n")

        if not lines:
            return 0, "Empty response"

        status_code = int(lines[-1]) if lines[-1].isdigit() else 0
        body = "\n".join(lines[:-1])

        try:
            return status_code, json.loads(body)
        except json.JSONDecodeError:
            return status_code, body

    except subprocess.TimeoutExpired:
        return 0, "Request timed out"
    except Exception as e:
        return 0, f"Error: {type(e).__name__}"


def check_openapi_includes_register() -> bool:
    """Check that /auth/register appears in OpenAPI schema."""
    print("\n[1/4] Checking OpenAPI schema includes /auth/register...")

    status, data = run_curl("GET", "http://127.0.0.1:8000/openapi.json")

    if status != 200:
        print(f"  FAIL: Could not fetch OpenAPI (status {status})")
        return False

    if not isinstance(data, dict):
        print(f"  FAIL: Invalid OpenAPI response")
        return False

    paths = data.get("paths", {})
    if "/auth/register" not in paths:
        print(f"  FAIL: /auth/register not in OpenAPI paths")
        print(f"  Available paths: {list(paths.keys())}")
        return False

    print(f"  PASS: /auth/register found in OpenAPI schema")
    return True


def check_register_creates_user() -> tuple[bool, str | None]:
    """Check that registration creates user and returns token.

    Returns:
        Tuple of (success, token_or_none)
    """
    print("\n[2/4] Testing registration creates user and returns token...")

    # Generate unique email
    random_suffix = secrets.token_hex(4)
    email = f"e2e_test_{random_suffix}@example.com"
    password = f"testpass_{secrets.token_hex(8)}"

    status, data = run_curl(
        "POST",
        "http://127.0.0.1:8000/auth/register",
        data={"email": email, "password": password},
    )

    if status == 404:
        print(f"  SKIP: Registration disabled (ALLOW_SELF_SIGNUP=false)")
        print(f"  To enable: set ALLOW_SELF_SIGNUP=true in backend/.env.local")
        return True, None  # Not a failure, just disabled

    if status != 201:
        print(f"  FAIL: Expected 201, got {status}")
        if isinstance(data, dict):
            print(f"  Detail: {data.get('detail', 'unknown')}")
        return False, None

    if not isinstance(data, dict):
        print(f"  FAIL: Response is not JSON object")
        return False, None

    token = data.get("access_token")
    user = data.get("user", {})

    if not token:
        print(f"  FAIL: No access_token in response")
        return False, None

    if not user.get("email"):
        print(f"  FAIL: No user.email in response")
        return False, None

    print(f"  PASS: User created (email: {user.get('email')})")
    print(f"  PASS: Token received (redacted: {redact_token(token)})")
    return True, token


def check_token_works_for_me(token: str) -> bool:
    """Check that token works for /auth/me."""
    print("\n[3/4] Testing token works for /auth/me...")

    status, data = run_curl(
        "GET",
        "http://127.0.0.1:8000/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    if status != 200:
        print(f"  FAIL: Expected 200, got {status}")
        return False

    if not isinstance(data, dict):
        print(f"  FAIL: Response is not JSON object")
        return False

    email = data.get("email")
    if not email:
        print(f"  FAIL: No email in /auth/me response")
        return False

    print(f"  PASS: /auth/me returned user (email: {email})")
    return True


def check_duplicate_returns_409() -> bool:
    """Check that duplicate registration returns 409."""
    print("\n[4/4] Testing duplicate registration returns 409...")

    # Generate unique email
    random_suffix = secrets.token_hex(4)
    email = f"e2e_dup_{random_suffix}@example.com"
    password = f"testpass_{secrets.token_hex(8)}"

    # First registration
    status1, _ = run_curl(
        "POST",
        "http://127.0.0.1:8000/auth/register",
        data={"email": email, "password": password},
    )

    if status1 == 404:
        print(f"  SKIP: Registration disabled")
        return True

    if status1 != 201:
        print(f"  FAIL: First registration failed (status {status1})")
        return False

    # Second registration with same email
    status2, data2 = run_curl(
        "POST",
        "http://127.0.0.1:8000/auth/register",
        data={"email": email, "password": "differentpassword"},
    )

    if status2 != 409:
        print(f"  FAIL: Expected 409 for duplicate, got {status2}")
        return False

    print(f"  PASS: Duplicate registration returned 409 Conflict")
    return True


def main() -> int:
    """Run all verification checks."""
    print("=" * 60)
    print("OctoLab Registration E2E Verification")
    print("=" * 60)

    results = []

    # Check 1: OpenAPI includes register
    results.append(("OpenAPI schema", check_openapi_includes_register()))

    # Check 2: Registration creates user (returns token if successful)
    success, token = check_register_creates_user()
    results.append(("Registration creates user", success))

    # Check 3: Token works (only if we got a token)
    if token:
        results.append(("Token works for /auth/me", check_token_works_for_me(token)))
    else:
        print("\n[3/4] SKIP: No token to test (registration disabled)")

    # Check 4: Duplicate returns 409
    results.append(("Duplicate returns 409", check_duplicate_returns_409()))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks passed!")
        return 0
    else:
        print("Some checks failed. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
