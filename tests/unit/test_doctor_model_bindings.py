"""`shux doctor` reports superharness's model bindings file without changing its exit code."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


def _doctor_output() -> tuple[str, int]:
    from superharness.commands import doctor

    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            doctor.main(["--project", str(REPO_ROOT)])
        except SystemExit:
            pass
    output = buf.getvalue()
    summary = [line for line in output.splitlines() if line.startswith("summary:")][0]
    return output, int(summary.split("warnings=")[1])


def _bindings(verified: date) -> str:
    return f"""schema: 2
providers:
  test-provider:
    verified: {verified.isoformat()}
harnesses:
  codex-cli:
    default_provider: test-provider
    bindings:
      test-provider:
        default:
          id: model-default
"""


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "superharness-config"
    directory.mkdir()
    monkeypatch.setenv("SUPERHARNESS_CONFIG_DIR", str(directory))
    return directory


def test_doctor_reports_missing_bindings(config_dir: Path) -> None:
    """A missing file is reported with its path and the adapter-defaults consequence."""
    output, _ = _doctor_output()

    line = [l for l in output.splitlines() if "model-bindings:" in l][0]
    assert line.startswith("INFO model-bindings:missing")
    assert str(config_dir / "model-bindings.yaml") in line
    assert "adapter defaults" in line


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (_bindings(date.today() - timedelta(days=30)), "WARN model-bindings:stale test-provider"),
        ("schema: 2\nharnesses: [unclosed\n", "WARN model-bindings:invalid"),
    ],
)
def test_doctor_reports_stale_bindings(config_dir: Path, content: str, expected: str) -> None:
    """Stale or invalid bindings are reported, but the warning count does not change."""
    _, baseline_warnings = _doctor_output()
    (config_dir / "model-bindings.yaml").write_text(content)

    output, warnings = _doctor_output()

    line = [l for l in output.splitlines() if "model-bindings:" in l][0]
    assert line.startswith(expected)
    assert "shux models check" in line
    assert warnings == baseline_warnings
