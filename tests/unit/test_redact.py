"""Tests for credential redaction (cherry-picked from hermes-agent)."""
import pytest
from superharness.guard.redact import redact


class TestRedaction:
    def test_redact_openai_key(self):
        assert redact("sk-abc123def456") == "[REDACTED_API_KEY]"

    def test_redact_openai_key_in_text(self):
        result = redact("Use key sk-proj-abc123 for this")
        assert "sk-proj-abc123" not in result
        assert "[REDACTED_API_KEY]" in result

    def test_redact_bearer_token(self):
        result = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
        assert "eyJhbGci" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_redact_password_in_assignment(self):
        result = redact("password=SecretPass123!")
        assert "SecretPass123" not in result
        assert "[REDACTED_PASSWORD]" in result

    def test_redact_db_connection_string(self):
        result = redact("postgres://admin:secretpass@localhost:5432/db")
        assert "secretpass" not in result
        assert "[REDACTED_PASSWORD]" in result

    def test_redact_private_key_pem(self):
        result = redact("-----BEGIN RSA PRIVATE KEY-----\nabc123\n-----END RSA PRIVATE KEY-----")
        assert "BEGIN RSA PRIVATE KEY" not in result
        assert "[REDACTED_KEY]" in result

    def test_redact_telegram_bot_token(self):
        result = redact("123456:ABC-DEF1234ghijkl")
        assert "123456:ABC-DEF" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_preserve_safe_text(self):
        safe = "This is a normal sentence with no secrets."
        assert redact(safe) == safe

    def test_redact_aws_key(self):
        result = redact("AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7" not in result
        assert "[REDACTED_KEY]" in result

    def test_redact_github_token(self):
        result = redact("ghp_abc123def456ghi789")
        assert "ghp_" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_redact_multiple_secrets(self):
        result = redact("key sk-abc123 and password=secret")
        assert "[REDACTED_API_KEY]" in result
        assert "[REDACTED_PASSWORD]" in result
