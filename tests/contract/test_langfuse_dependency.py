"""Packaging contract for the optional Langfuse observability integration."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_langfuse_is_declared_only_in_the_observability_extra():
    project = _toml(ROOT / "pyproject.toml")["project"]

    assert project["optional-dependencies"]["observability"] == [
        "langfuse>=4.7,<5"
    ]
    assert all(
        not dependency.lower().startswith("langfuse")
        for dependency in project["dependencies"]
    )


def test_uv_lock_contains_langfuse_for_the_project_extra():
    lock = _toml(ROOT / "uv.lock")
    packages = {package["name"]: package for package in lock["package"]}

    assert "langfuse" in packages
    superharness = packages["superharness"]
    assert superharness["optional-dependencies"]["observability"] == [
        {"name": "langfuse"}
    ]


def test_langfuse_runbook_has_secure_operator_contract():
    runbook = ROOT / "docs" / "langfuse-observability.md"
    text = runbook.read_text(encoding="utf-8")

    assert len(text.splitlines()) <= 50
    for required in (
        "superharness[observability]",
        "SUPERHARNESS_LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_TRACING_ENVIRONMENT",
        "https://langfuse-ops.gitsilence.net",
        "chmod 600",
        "shux doctor --langfuse-auth",
        "Prompts, responses, task text, raw task IDs, paths, logs, and secrets are never exported",
    ):
        assert required in text

    assert "/Users/" not in text


def test_langfuse_runbook_is_indexed():
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "[`langfuse-observability.md`](langfuse-observability.md)" in index
