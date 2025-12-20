"""Dockerfile validator service for OctoLab.

Validates Dockerfiles from LLM-generated content before building.

SECURITY:
- Blocks dangerous directives (--privileged, external COPY --from)
- Detects dangerous patterns (rm -rf /, curl|sh, wget|sh)
- Enforces size limits
- Validates basic structure and syntax
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# Maximum Dockerfile size (64KB)
MAX_DOCKERFILE_SIZE = 65536


@dataclass
class ValidationResult:
    """Result of Dockerfile validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DockerfileValidator:
    """Validates Dockerfiles before build.

    Performs multiple validation checks:
    1. Basic syntax validation (valid instructions)
    2. Required instructions (FROM)
    3. COPY/ADD file completeness
    4. Dangerous pattern detection
    5. Security checks (--privileged, external COPY --from)
    """

    # Valid Dockerfile instructions
    VALID_INSTRUCTIONS = frozenset(
        [
            "FROM",
            "RUN",
            "CMD",
            "LABEL",
            "EXPOSE",
            "ENV",
            "ADD",
            "COPY",
            "ENTRYPOINT",
            "VOLUME",
            "USER",
            "WORKDIR",
            "ARG",
            "ONBUILD",
            "STOPSIGNAL",
            "HEALTHCHECK",
            "SHELL",
        ]
    )

    # Required instructions
    REQUIRED_INSTRUCTIONS = ["FROM"]

    # Dangerous patterns to block (pattern, error message)
    # Note: rm -rf pattern specifically targets "rm -rf /" or "rm -rf /*" (root only)
    DANGEROUS_PATTERNS = [
        (r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\s*$", "Dangerous: rm -rf on root directory"),
        (r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\*", "Dangerous: rm -rf on root directory"),
        (r"rm\s+-[a-z]*f[a-z]*r[a-z]*\s+/\s*$", "Dangerous: rm -rf on root directory"),
        (r"rm\s+-[a-z]*f[a-z]*r[a-z]*\s+/\*", "Dangerous: rm -rf on root directory"),
        (r"curl\s+[^|]*\|\s*(?:ba)?sh", "Dangerous: curl pipe to shell"),
        (r"wget\s+[^|]*\|\s*(?:ba)?sh", "Dangerous: wget pipe to shell"),
        (r"curl\s+[^|]*\|\s*bash", "Dangerous: curl pipe to bash"),
        (r"wget\s+[^|]*\|\s*bash", "Dangerous: wget pipe to bash"),
    ]

    # Patterns that generate warnings (non-blocking)
    WARNING_PATTERNS = [
        (
            r"chmod\s+777\s+/",
            "chmod 777 on root - consider more restrictive permissions",
        ),
        (
            r"chmod\s+-[Rr]\s+777",
            "Recursive chmod 777 - consider more restrictive permissions",
        ),
    ]

    def validate(
        self, dockerfile: str, source_files: Optional[list[dict]] = None
    ) -> ValidationResult:
        """Validate a Dockerfile.

        Args:
            dockerfile: Dockerfile content
            source_files: List of {filename, content} dicts

        Returns:
            ValidationResult with valid flag, errors, warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 0. Empty/size check
        if not dockerfile or not dockerfile.strip():
            return ValidationResult(valid=False, errors=["Dockerfile is empty"])

        if len(dockerfile) > MAX_DOCKERFILE_SIZE:
            return ValidationResult(
                valid=False,
                errors=[
                    f"Dockerfile too large: {len(dockerfile)} bytes (max {MAX_DOCKERFILE_SIZE})"
                ],
            )

        # 1. Basic syntax check
        syntax_errors = self._check_syntax(dockerfile)
        errors.extend(syntax_errors)

        # 2. Check required instructions
        for instruction in self.REQUIRED_INSTRUCTIONS:
            if not re.search(
                rf"^{instruction}\s+", dockerfile, re.MULTILINE | re.IGNORECASE
            ):
                errors.append(f"Missing required instruction: {instruction}")

        # 3. Check COPY/ADD file completeness
        if source_files is not None:
            file_errors = self._check_file_completeness(dockerfile, source_files)
            errors.extend(file_errors)

        # 4. Check dangerous patterns
        danger_errors = self._check_dangerous_patterns(dockerfile)
        errors.extend(danger_errors)

        # 5. Check security directives
        security_errors = self._check_security_directives(dockerfile)
        errors.extend(security_errors)

        # 6. Check warnings (non-blocking)
        pattern_warnings = self._check_warning_patterns(dockerfile)
        warnings.extend(pattern_warnings)

        # ADD with URL warning
        dockerfile_lower = dockerfile.lower()
        if "add " in dockerfile_lower and (
            "http://" in dockerfile_lower or "https://" in dockerfile_lower
        ):
            warnings.append(
                "Dockerfile uses ADD with URL - consider using COPY with curl/wget instead"
            )

        return ValidationResult(
            valid=len(errors) == 0, errors=errors, warnings=warnings
        )

    def _check_syntax(self, dockerfile: str) -> list[str]:
        """Basic syntax validation - check for valid instructions."""
        errors: list[str] = []
        lines = dockerfile.strip().split("\n")

        in_continuation = False
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            # Handle line continuation
            if in_continuation:
                in_continuation = stripped.endswith("\\")
                continue

            # Check if line ends with continuation
            if stripped.endswith("\\"):
                in_continuation = True

            # Get first word (instruction)
            parts = stripped.split()
            if not parts:
                continue

            first_word = parts[0].upper()

            # Check for valid instruction
            if first_word not in self.VALID_INSTRUCTIONS:
                errors.append(f"Line {i}: Unknown instruction '{parts[0]}'")

        return errors

    def _check_file_completeness(
        self, dockerfile: str, source_files: list[dict]
    ) -> list[str]:
        """Check that all COPY/ADD files exist in source_files."""
        errors: list[str] = []
        source_filenames = {
            f.get("filename", "") for f in source_files if f.get("filename")
        }

        # Pattern to match COPY and ADD instructions
        # Handles: COPY [--chown=...] [--chmod=...] [--from=...] <src> <dest>
        copy_add_pattern = re.compile(
            r"^\s*(?:COPY|ADD)\s+"
            r"(?:--[a-z]+=\S+\s+)*"  # Optional flags like --chown, --chmod, --from
            r"(\S+)",  # Source file/dir
            re.IGNORECASE | re.MULTILINE,
        )

        for match in copy_add_pattern.finditer(dockerfile):
            src = match.group(1)

            # Get the full line to check for --from
            line_start = dockerfile.rfind("\n", 0, match.start()) + 1
            line_end = dockerfile.find("\n", match.end())
            if line_end == -1:
                line_end = len(dockerfile)
            full_line = dockerfile[line_start:line_end]

            # Skip COPY --from (multi-stage builds)
            if "--from=" in full_line.lower() or "--from " in full_line.lower():
                continue

            # Skip URLs (ADD supports URLs)
            if src.startswith("http://") or src.startswith("https://"):
                continue

            # Skip if source starts with -- (it's a flag we didn't fully parse)
            if src.startswith("--"):
                continue

            # Skip "." or "./" (current directory)
            if src in (".", "./"):
                continue

            # Skip wildcards
            if "*" in src or "?" in src:
                continue

            # Normalize path (remove ./ prefix)
            src_normalized = src.lstrip("./")

            # Check if file exists in provided source_files
            if src_normalized not in source_filenames:
                available = list(source_filenames) if source_filenames else ["none"]
                errors.append(
                    f"COPY/ADD references '{src_normalized}' but it's not in source_files. "
                    f"Available files: {available}"
                )

        return errors

    def _check_dangerous_patterns(self, dockerfile: str) -> list[str]:
        """Check for dangerous patterns."""
        errors: list[str] = []

        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, dockerfile, re.IGNORECASE | re.MULTILINE):
                errors.append(message)

        return errors

    def _check_security_directives(self, dockerfile: str) -> list[str]:
        """Check for security-related disallowed directives."""
        errors: list[str] = []
        dockerfile_lower = dockerfile.lower()

        # Block --privileged
        if "--privileged" in dockerfile_lower:
            errors.append("Dockerfile contains disallowed directive: --privileged")

        # Block COPY --from with external URLs
        if re.search(r"copy\s+--from\s*=\s*(https?://|ftp://)", dockerfile_lower):
            errors.append("Dockerfile contains disallowed external COPY --from")

        return errors

    def _check_warning_patterns(self, dockerfile: str) -> list[str]:
        """Check for patterns that warrant warnings."""
        warnings: list[str] = []

        for pattern, message in self.WARNING_PATTERNS:
            if re.search(pattern, dockerfile, re.IGNORECASE):
                warnings.append(message)

        return warnings


# Singleton instance
dockerfile_validator = DockerfileValidator()


# =============================================================================
# Backward-compatible function API (used by labs.py)
# =============================================================================


def validate_dockerfile(dockerfile: str) -> ValidationResult:
    """Validate a Dockerfile for security and correctness.

    Checks:
    1. Size limit (< 64KB)
    2. Must start with FROM instruction
    3. Block --privileged
    4. Block COPY --from= external URLs
    5. Block dangerous patterns (rm -rf, curl|sh, etc.)
    6. Syntax validation

    Args:
        dockerfile: Dockerfile content as string

    Returns:
        ValidationResult with valid=True/False and any errors/warnings

    SECURITY: This is a defense-in-depth check. The guest agent also
    validates Dockerfiles, but we check here first to fail fast.
    """
    return dockerfile_validator.validate(dockerfile, source_files=None)


def validate_copy_commands(
    dockerfile: str, source_files: list[dict]
) -> ValidationResult:
    """Validate that all COPY commands reference files in source_files.

    Args:
        dockerfile: Dockerfile content
        source_files: List of {filename, content} dicts

    Returns:
        ValidationResult with errors for missing files

    SECURITY: Prevents LLM from generating Dockerfiles that reference
    non-existent files, which would cause build failures.
    """
    result = ValidationResult(valid=True)

    # Use the validator's file completeness check
    errors = dockerfile_validator._check_file_completeness(dockerfile, source_files)
    if errors:
        result.valid = False
        result.errors = errors

    return result


def validate_source_file(filename: str, content: str) -> ValidationResult:
    """Validate a source file for the Docker build context.

    Args:
        filename: Name of the file
        content: File content

    Returns:
        ValidationResult
    """
    result = ValidationResult(valid=True)

    # Filename validation
    if not filename:
        result.valid = False
        result.errors.append("Filename is empty")
        return result

    # No path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        result.valid = False
        result.errors.append(f"Invalid filename (path traversal): {filename[:50]}")
        return result

    # Length limit
    if len(filename) > 255:
        result.valid = False
        result.errors.append(f"Filename too long: {len(filename)} chars (max 255)")
        return result

    # Content size limit (1MB)
    if len(content) > 1_000_000:
        result.valid = False
        result.errors.append(f"File too large: {len(content)} bytes (max 1MB)")
        return result

    return result
