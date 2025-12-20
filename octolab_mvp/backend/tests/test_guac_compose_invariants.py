"""Tests for Guacamole docker-compose.yml invariants.

These tests verify critical security and configuration requirements
for the Guacamole stack WITHOUT requiring Docker to run.

Invariants tested:
- guac-db has NO published ports (except in debug profile)
- guac-db healthcheck uses CMD-SHELL with pg_isready and env vars
- guacamole service references guac-db by service name
"""

import os
import re
from pathlib import Path

import pytest

# Find the compose file relative to test file
REPO_ROOT = Path(__file__).parent.parent.parent
COMPOSE_FILE = REPO_ROOT / "infra" / "guacamole" / "docker-compose.yml"


@pytest.fixture
def compose_content():
    """Load the docker-compose.yml content."""
    if not COMPOSE_FILE.exists():
        pytest.skip(f"Compose file not found: {COMPOSE_FILE}")
    return COMPOSE_FILE.read_text()


@pytest.fixture
def compose_yaml(compose_content):
    """Parse the docker-compose.yml as YAML if PyYAML is available."""
    try:
        import yaml
        return yaml.safe_load(compose_content)
    except ImportError:
        pytest.skip("PyYAML not available, using regex-based tests only")


class TestGuacDbNoPorts:
    """Verify guac-db has no published ports by default."""

    def test_guac_db_no_ports_in_content(self, compose_content):
        """Assert guac-db service definition doesn't have 'ports:' section.

        This is a regex-based check that works without PyYAML.
        """
        # Find the guac-db service block
        # Pattern: service name followed by content until next service or end
        guac_db_pattern = r"^\s*guac-db:\s*\n((?:[ \t]+.*\n)*)"
        match = re.search(guac_db_pattern, compose_content, re.MULTILINE)

        assert match, "guac-db service not found in compose file"
        guac_db_block = match.group(1)

        # Check for 'ports:' in the guac-db block
        # Should NOT have ports unless under profiles
        ports_line = re.search(r"^\s+ports:\s*$", guac_db_block, re.MULTILINE)

        assert ports_line is None, (
            "guac-db has 'ports:' defined. "
            "Guac DB should NOT publish ports by default (security)."
        )

    def test_guac_db_no_port_5432(self, compose_content):
        """Assert 5432 is not published to host anywhere in the file.

        The DB port should be internal only.
        """
        # Check for any port mapping involving 5432 to host
        # Pattern: "HOST:5432" or just "5432:5432"
        dangerous_patterns = [
            r'"\d*:5432"',      # "HOST:5432" or ":5432"
            r"'\d*:5432'",      # 'HOST:5432' or ':5432'
            r'-\s*5432:5432',   # - 5432:5432
            r'-\s*"\d+:5432"',  # - "HOST:5432"
        ]

        for pattern in dangerous_patterns:
            match = re.search(pattern, compose_content)
            if match:
                # Check if it's in a comment
                line_start = compose_content.rfind('\n', 0, match.start()) + 1
                line = compose_content[line_start:match.end()]
                if not line.strip().startswith('#'):
                    pytest.fail(
                        f"Port 5432 appears to be published to host: {line.strip()}\n"
                        "Guac DB should NOT publish port 5432 for security."
                    )


class TestGuacDbHealthcheck:
    """Verify guac-db healthcheck is properly configured."""

    def test_healthcheck_uses_cmd_shell(self, compose_content):
        """Assert healthcheck uses CMD-SHELL format."""
        # Look for healthcheck in guac-db block
        assert 'CMD-SHELL' in compose_content, (
            "Healthcheck should use CMD-SHELL format for env var expansion"
        )

    def test_healthcheck_has_pg_isready(self, compose_content):
        """Assert healthcheck uses pg_isready command."""
        assert 'pg_isready' in compose_content, (
            "Healthcheck should use pg_isready for reliable DB health check"
        )

    def test_healthcheck_references_env_vars(self, compose_content):
        """Assert healthcheck references POSTGRES_USER and/or POSTGRES_DB."""
        # Should have either $POSTGRES_USER or $$POSTGRES_USER (escaped for compose)
        has_user_ref = (
            '$POSTGRES_USER' in compose_content or
            '$$POSTGRES_USER' in compose_content
        )
        has_db_ref = (
            '$POSTGRES_DB' in compose_content or
            '$$POSTGRES_DB' in compose_content
        )

        assert has_user_ref or has_db_ref, (
            "Healthcheck should reference POSTGRES_USER/POSTGRES_DB env vars "
            "to work correctly when credentials change"
        )

    def test_healthcheck_has_reasonable_timeouts(self, compose_content):
        """Assert healthcheck has interval, timeout, retries configured."""
        # These should all be present in the healthcheck section
        assert 'interval:' in compose_content, "Healthcheck missing interval"
        assert 'timeout:' in compose_content, "Healthcheck missing timeout"
        assert 'retries:' in compose_content, "Healthcheck missing retries"


class TestGuacamoleServiceConfig:
    """Verify guacamole service is properly configured."""

    def test_guacamole_depends_on_guac_db(self, compose_content):
        """Assert guacamole service depends on guac-db."""
        assert 'guac-db:' in compose_content and 'depends_on:' in compose_content, (
            "guacamole should depend on guac-db"
        )

    def test_guacamole_uses_guac_db_hostname(self, compose_content):
        """Assert guacamole uses guac-db as POSTGRESQL_HOSTNAME."""
        # Look for POSTGRESQL_HOSTNAME: guac-db or similar
        assert re.search(r'POSTGRESQL_HOSTNAME:\s*guac-db', compose_content), (
            "guacamole should use 'guac-db' as POSTGRESQL_HOSTNAME "
            "(service name for internal DNS)"
        )

    def test_guacamole_binds_localhost_only(self, compose_content):
        """Assert guacamole only binds to 127.0.0.1."""
        # Look for 127.0.0.1:PORT:PORT pattern
        if re.search(r'ports:', compose_content):
            assert '127.0.0.1:' in compose_content, (
                "guacamole should bind to 127.0.0.1 only for security"
            )


class TestYamlStructure:
    """Tests that require PyYAML for proper YAML parsing."""

    def test_guac_db_no_ports_yaml(self, compose_yaml):
        """Assert guac-db service has no ports in YAML structure."""
        services = compose_yaml.get('services', {})
        guac_db = services.get('guac-db', {})

        assert 'ports' not in guac_db, (
            f"guac-db should not have 'ports' key. Found: {guac_db.get('ports')}"
        )

    def test_guac_db_has_healthcheck_yaml(self, compose_yaml):
        """Assert guac-db has healthcheck configured."""
        services = compose_yaml.get('services', {})
        guac_db = services.get('guac-db', {})

        assert 'healthcheck' in guac_db, "guac-db should have healthcheck configured"

        healthcheck = guac_db['healthcheck']
        assert 'test' in healthcheck, "healthcheck should have 'test' command"
        assert 'interval' in healthcheck, "healthcheck should have 'interval'"
        assert 'timeout' in healthcheck, "healthcheck should have 'timeout'"
        assert 'retries' in healthcheck, "healthcheck should have 'retries'"

    def test_guacamole_depends_on_healthy_db_yaml(self, compose_yaml):
        """Assert guacamole waits for guac-db to be healthy."""
        services = compose_yaml.get('services', {})
        guacamole = services.get('guacamole', {})

        depends_on = guacamole.get('depends_on', {})
        guac_db_dep = depends_on.get('guac-db', {})

        if isinstance(guac_db_dep, dict):
            assert guac_db_dep.get('condition') == 'service_healthy', (
                "guacamole should wait for guac-db to be healthy"
            )
        # If it's just a string dependency, that's acceptable but not ideal

    def test_volumes_defined_yaml(self, compose_yaml):
        """Assert guac-db-data volume is defined."""
        volumes = compose_yaml.get('volumes', {})
        assert 'guac-db-data' in volumes, (
            "guac-db-data volume should be defined for data persistence"
        )
