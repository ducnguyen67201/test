"""Tests for the Guac DB diagnosis helper (guac_diagnose.py).

These tests verify that the diagnosis logic correctly classifies
common failure modes based on log and inspect output.
"""

import sys
from pathlib import Path

import pytest

# Add dev/scripts to path so we can import guac_diagnose
DEV_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "dev" / "scripts"
sys.path.insert(0, str(DEV_SCRIPTS_DIR))

from guac_diagnose import (
    DiagnosisCode,
    classify,
    classify_inspect,
    classify_logs,
    redact_sensitive,
)


class TestRedactSensitive:
    """Test sensitive value redaction."""

    def test_redacts_password_env_var(self):
        text = "POSTGRES_PASSWORD=supersecret123"
        result = redact_sensitive(text)
        assert "supersecret123" not in result
        assert "****" in result

    def test_redacts_secret_key(self):
        text = "GUAC_ENC_KEY=abc123xyz"
        result = redact_sensitive(text)
        assert "abc123xyz" not in result

    def test_redacts_token(self):
        text = "API_TOKEN=mytoken123"
        result = redact_sensitive(text)
        assert "mytoken123" not in result

    def test_redacts_password_in_log_line(self):
        text = "password: mysecret"
        result = redact_sensitive(text)
        assert "mysecret" not in result

    def test_preserves_non_sensitive(self):
        text = "LOG_LEVEL=DEBUG"
        result = redact_sensitive(text)
        assert result == text

    def test_handles_multiline(self):
        text = """
        POSTGRES_USER=guacamole
        POSTGRES_PASSWORD=secret123
        LOG_LEVEL=INFO
        """
        result = redact_sensitive(text)
        assert "secret123" not in result
        assert "guacamole" in result  # Username is not redacted
        assert "INFO" in result


class TestClassifyLogs:
    """Test log classification for common failure modes."""

    def test_detects_port_bind_conflict(self):
        log_text = """
        Error starting userland proxy: listen tcp4 0.0.0.0:5432: bind: address already in use
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.PORT_BIND_CONFLICT in codes

    def test_detects_stale_volume_password_failed(self):
        log_text = """
        FATAL:  password authentication failed for user "guacamole"
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.STALE_VOLUME_CREDS in codes

    def test_detects_stale_volume_role_not_exist(self):
        log_text = """
        FATAL:  role "guacamole" does not exist
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.STALE_VOLUME_CREDS in codes

    def test_detects_db_files_incompatible(self):
        log_text = """
        FATAL:  database files are incompatible with server
        DETAIL:  The data directory was initialized by PostgreSQL version 15, which is not compatible with this version 16.4.
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.DB_FILES_INCOMPATIBLE in codes

    def test_detects_init_sql_error_syntax(self):
        log_text = """
        ERROR:  syntax error at or near "CREAT"
        LINE 1: CREAT TABLE foo...
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.INIT_SQL_ERROR in codes

    def test_detects_init_sql_error_relation_exists(self):
        log_text = """
        ERROR:  relation "guacamole_user" already exists
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.INIT_SQL_ERROR in codes

    def test_detects_permission_denied(self):
        log_text = """
        could not open file "/var/lib/postgresql/data/pg_hba.conf": Permission denied
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.PERMISSION_DENIED in codes

    def test_no_false_positives_on_clean_logs(self):
        log_text = """
        PostgreSQL init process complete; ready for start up.
        2024-01-01 00:00:00.000 UTC [1] LOG:  database system is ready to accept connections
        """
        diagnoses = classify_logs(log_text)
        assert len(diagnoses) == 0

    def test_deduplicates_same_code(self):
        # Multiple password failures should only produce one diagnosis
        log_text = """
        FATAL:  password authentication failed for user "guacamole"
        FATAL:  password authentication failed for user "guacamole"
        FATAL:  password authentication failed for user "guacamole"
        """
        diagnoses = classify_logs(log_text)
        codes = [d.code for d in diagnoses]
        # Should be deduplicated
        assert codes.count(DiagnosisCode.STALE_VOLUME_CREDS) == 1


class TestClassifyInspect:
    """Test inspect output classification."""

    def test_detects_unexpanded_env_var(self):
        inspect_text = """
        "Healthcheck": {
            "Test": ["CMD-SHELL", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
        }
        """
        diagnoses = classify_inspect(inspect_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.HEALTHCHECK_ENV_NOT_EXPANDED in codes

    def test_no_false_positive_on_expanded_var(self):
        inspect_text = """
        "Healthcheck": {
            "Test": ["CMD-SHELL", "pg_isready -U guacamole -d guacamole_db"]
        }
        """
        diagnoses = classify_inspect(inspect_text)
        codes = [d.code for d in diagnoses]
        assert DiagnosisCode.HEALTHCHECK_ENV_NOT_EXPANDED not in codes


class TestClassifyCombined:
    """Test combined classification from logs and inspect."""

    def test_combines_log_and_inspect_diagnoses(self):
        log_text = "FATAL: password authentication failed for user"
        inspect_text = '"Test": ["CMD-SHELL", "pg_isready -U $POSTGRES_USER"]'

        diagnoses = classify(log_text, inspect_text)
        codes = [d.code for d in diagnoses]

        assert DiagnosisCode.STALE_VOLUME_CREDS in codes
        assert DiagnosisCode.HEALTHCHECK_ENV_NOT_EXPANDED in codes

    def test_empty_inputs_return_empty(self):
        diagnoses = classify("", "")
        assert len(diagnoses) == 0


class TestDiagnosisRemediations:
    """Test that diagnoses include helpful remediations."""

    def test_stale_volume_suggests_reset(self):
        log_text = "FATAL: password authentication failed"
        diagnoses = classify_logs(log_text)
        d = next(d for d in diagnoses if d.code == DiagnosisCode.STALE_VOLUME_CREDS)
        assert "guac-reset-db" in d.remediation.lower()

    def test_port_conflict_suggests_lsof(self):
        log_text = "bind: address already in use"
        diagnoses = classify_logs(log_text)
        d = next(d for d in diagnoses if d.code == DiagnosisCode.PORT_BIND_CONFLICT)
        assert "lsof" in d.remediation.lower() or "port" in d.remediation.lower()

    def test_init_sql_suggests_check_file(self):
        log_text = "ERROR: syntax error"
        diagnoses = classify_logs(log_text)
        d = next(d for d in diagnoses if d.code == DiagnosisCode.INIT_SQL_ERROR)
        assert "initdb.sql" in d.remediation.lower()
