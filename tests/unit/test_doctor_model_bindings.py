"""`shux doctor` reports superharness's model bindings file without changing its exit code."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from superharness.engine import model_refresh
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


def test_doctor_stale_line_names_catalog_refresh(config_dir: Path) -> None:
    """The stale doctor line names the catalog refresh; the warning count does not change."""
    _, baseline_warnings = _doctor_output()
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today() - timedelta(days=30)))

    output, warnings = _doctor_output()

    line = [l for l in output.splitlines() if "model-bindings:" in l][0]
    assert "shux models update --catalog" in line
    assert warnings == baseline_warnings


@pytest.fixture(autouse=True)
def state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep doctor away from the operator's real refresh receipts in the state directory.

    Patches the receipts path rather than SUPERHARNESS_STATE_DIR: setting that
    variable makes doctor refuse to run while this checkout holds a legacy state db.
    """
    directory = tmp_path / "superharness-state"
    directory.mkdir()
    monkeypatch.setattr(
        model_refresh, "receipts_path", lambda: directory / model_refresh.RECEIPTS_FILENAME
    )
    return directory


def _receipt_line(outcome: str, at: datetime) -> str:
    return json.dumps(
        {"at": at.isoformat(), "outcome": outcome, "applied": [], "skipped": [], "errors": {}}
    )


def _write_receipts(state_dir: Path, *lines: str) -> None:
    (state_dir / "model-refresh-receipts.jsonl").write_text("\n".join(lines) + "\n")


def _model_line(output: str) -> str:
    return [l for l in output.splitlines() if "model-bindings:" in l][0]


def test_doctor_reports_last_refresh_outcome(config_dir: Path, state_dir: Path) -> None:
    """A fresh bindings file plus an ok receipt from today reports the refresh outcome."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    today = datetime.now(UTC)
    _write_receipts(state_dir, _receipt_line("ok", today))

    output, _ = _doctor_output()

    line = _model_line(output)
    assert line.startswith("PASS")
    assert f"last refresh ok {today.date().isoformat()}" in line


def test_doctor_warns_on_failed_or_old_refresh(config_dir: Path, state_dir: Path) -> None:
    """A failed receipt, or an ok one older than twice review_after_days, makes the line WARN."""
    _, baseline_warnings = _doctor_output()
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))

    _write_receipts(state_dir, _receipt_line("failed", datetime.now(UTC)))
    failed_output, failed_warnings = _doctor_output()
    failed_line = _model_line(failed_output)
    assert failed_line.startswith("WARN")
    assert "shux models refresh" in failed_line
    assert failed_warnings == baseline_warnings

    _write_receipts(state_dir, _receipt_line("ok", datetime.now(UTC) - timedelta(days=30)))
    old_output, old_warnings = _doctor_output()
    old_line = _model_line(old_output)
    assert old_line.startswith("WARN")
    assert "shux models refresh" in old_line
    assert old_warnings == baseline_warnings


def test_doctor_ignores_malformed_receipts(config_dir: Path, state_dir: Path) -> None:
    """Receipt lines that are not JSON objects leave the PASS line unchanged and raise nothing."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    _write_receipts(state_dir, "{torn", "[1]")

    output, _ = _doctor_output()

    line = _model_line(output)
    assert line.startswith("PASS")
    assert "last refresh" not in line
