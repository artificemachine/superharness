"""Tests for `shux models` (commands/models.py)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.commands.models import main as models_main


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
        bulk:
          id: model-bulk
        default:
          id: model-default
        escalate-1:
          id: model-max
"""


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "superharness-config"
    directory.mkdir()
    monkeypatch.setenv("SUPERHARNESS_CONFIG_DIR", str(directory))
    return directory


def test_check_missing_file_exits_2(config_dir: Path) -> None:
    """No bindings file: the path is named, adapter defaults are announced, exit 2."""
    result = CliRunner().invoke(models_main, ["check"])

    assert result.exit_code == 2
    assert str(config_dir / "model-bindings.yaml") in result.output
    assert "adapter defaults" in result.output


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (_bindings(date.today() - timedelta(days=30)), "test-provider"),
        ("schema: 2\nharnesses: [unclosed\n", "invalid"),
    ],
)
def test_check_reports_stale_provider(config_dir: Path, content: str, expected: str) -> None:
    """A stale provider or an invalid file is reported without a traceback, exit 1."""
    (config_dir / "model-bindings.yaml").write_text(content)

    result = CliRunner().invoke(models_main, ["check"])

    assert result.exit_code == 1
    assert expected in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


_TWO_HARNESSES = f"""schema: 2
providers:
  test-provider:
    verified: {date.today().isoformat()}
harnesses:
  codex-cli:
    default_provider: test-provider
    bindings:
      test-provider:
        default:
          id: codex-default
  pi:
    default_provider: test-provider
    bindings:
      test-provider:
        default:
          id: pi-default
"""


def _discovered(*ids: str) -> list:
    from datetime import datetime, timezone

    from superharness.engine.model_discovery import DiscoveredModel

    now = datetime.now(timezone.utc)
    return [DiscoveredModel(i, i, "native", "unknown", now) for i in ids]


def _probe(monkeypatch: pytest.MonkeyPatch, answer) -> list[tuple[str, list[str] | None]]:
    from superharness.engine import model_router

    calls: list[tuple[str, list[str] | None]] = []

    def _fake(agent, auth_mode="unknown", chain=None):
        calls.append((agent, chain))
        return answer(agent)

    monkeypatch.setattr(model_router, "_discover_for_agent", _fake)
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "unknown")
    return calls


def _availability(output: str) -> dict[tuple[str, str], str]:
    rows = json.loads(output)["bindings"]
    return {(r["harness"], r["tier"]): r["availability"] for r in rows}


def test_check_probe_marks_dead_binding(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery that answers without the bound model marks it unavailable; one probe per harness."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    calls = _probe(monkeypatch, lambda agent: _discovered("model-default", "other-model"))

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 1, result.output
    assert _availability(result.output) == {
        ("codex-cli", "bulk"): "unavailable",
        ("codex-cli", "default"): "available",
        ("codex-cli", "escalate-1"): "unavailable",
    }
    assert [agent for agent, _ in calls] == ["codex-cli"]
    assert set(calls[0][1] or []) == {"model-bulk", "model-default", "model-max"}


def test_check_probe_unknown_when_discovery_empty(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery that cannot answer leaves every binding unknown, which is not a failure."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    _probe(monkeypatch, lambda agent: [])

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 0, result.output
    assert set(_availability(result.output).values()) == {"unknown"}


def test_check_probe_survives_one_harness_failure(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One harness whose discovery raises is reported unknown with the error; others still report."""
    (config_dir / "model-bindings.yaml").write_text(_TWO_HARNESSES)

    def _answer(agent):
        if agent == "codex-cli":
            raise RuntimeError("probe crashed")
        return _discovered("pi-default")

    _probe(monkeypatch, _answer)

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 0, result.output
    rows = {r["harness"]: r for r in json.loads(result.output)["bindings"]}
    assert rows["codex-cli"]["availability"] == "unknown"
    assert "probe crashed" in rows["codex-cli"]["error"]
    assert rows["pi"]["availability"] == "available"


def _manifest_first_choice(harness: str, tier: str) -> str:
    from superharness.engine.adapter_registry import load_manifest

    manifest = load_manifest(harness)
    chain = manifest.resolve_accept_chain(tier, "unknown")
    return chain[0] if chain else manifest.model_tiers[tier]["id"]


def test_init_writes_valid_schema2_from_manifests(config_dir: Path) -> None:
    """init writes a schema-2 file from the adapter manifests that dispatch then reads."""
    from superharness.engine import model_router
    from superharness.engine.model_bindings import load_bindings

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 0, result.output
    bindings = load_bindings(config_dir / "model-bindings.yaml")
    assert bindings.status == "ok"
    codex = bindings.data["harnesses"]["codex-cli"]
    assert codex["default_provider"] == "adapter-manifest"
    ladder = codex["bindings"]["adapter-manifest"]
    assert ladder["bulk"]["id"] == _manifest_first_choice("codex-cli", "mini")
    assert ladder["default"]["id"] == _manifest_first_choice("codex-cli", "standard")
    assert ladder["escalate-1"]["id"] == _manifest_first_choice("codex-cli", "max")
    assert model_router._resolve_runtime_binding_model("codex-cli", "standard") == ladder["default"]["id"]
    assert CliRunner().invoke(models_main, ["check"]).exit_code == 0


def test_init_refuses_existing_without_force(config_dir: Path) -> None:
    """An existing file is never overwritten without --force."""
    target = config_dir / "model-bindings.yaml"
    target.write_text("# operator file\n")

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 1
    assert target.read_text() == "# operator file\n"
    assert "--force" in result.output


def test_init_force_keeps_backup(config_dir: Path) -> None:
    """--force replaces the file and keeps a byte-identical timestamped backup."""
    target = config_dir / "model-bindings.yaml"
    target.write_bytes(b"# previous operator file\n")

    result = CliRunner().invoke(models_main, ["init", "--force"])

    assert result.exit_code == 0, result.output
    backups = list(config_dir.glob("model-bindings.yaml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"# previous operator file\n"
    assert "schema: 2" in target.read_text()


def test_init_failed_write_leaves_no_partial_file(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing final rename exits 1 and leaves neither a target nor a temporary file."""
    from superharness.commands import models

    def _fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(models.os, "replace", _fail)

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 1
    assert "disk full" in result.output
    assert list(config_dir.iterdir()) == []


def test_init_from_copies_valid_file(config_dir: Path, tmp_path: Path) -> None:
    """--from imports a valid schema-2 file byte for byte."""
    source = tmp_path / "elsewhere.yaml"
    source.write_text("# operator comment\n" + _bindings(date.today()))

    result = CliRunner().invoke(models_main, ["init", "--from", str(source)])

    assert result.exit_code == 0, result.output
    assert (config_dir / "model-bindings.yaml").read_bytes() == source.read_bytes()
    assert CliRunner().invoke(models_main, ["check"]).exit_code == 0


@pytest.mark.parametrize(
    "source_text",
    ["schema: 1\nharnesses: {}\n", None],
    ids=["wrong-schema", "absent-source"],
)
def test_init_from_rejects_invalid_schema_and_writes_nothing(
    config_dir: Path, tmp_path: Path, source_text: str | None
) -> None:
    """An invalid or absent source is refused with its path named, and nothing is written."""
    source = tmp_path / "source.yaml"
    if source_text is not None:
        source.write_text(source_text)

    result = CliRunner().invoke(models_main, ["init", "--from", str(source)])

    assert result.exit_code == 1
    assert str(source) in result.output
    assert not (config_dir / "model-bindings.yaml").exists()


def _dead_default_bindings() -> str:
    return _bindings(date.today()).replace("id: model-default", "id: dead-model")


def _codex_standard_chain() -> list[str]:
    from superharness.engine.adapter_registry import load_manifest

    return load_manifest("codex-cli").resolve_accept_chain("standard", "unknown")


def test_update_dry_run_writes_nothing(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """update without --apply never touches the file."""
    target = config_dir / "model-bindings.yaml"
    target.write_text(_dead_default_bindings())
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    _probe(monkeypatch, lambda agent: _discovered(*_codex_standard_chain()))

    result = CliRunner().invoke(models_main, ["update"])

    assert result.exit_code == 0, result.output
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert not list(config_dir.glob("*.bak-*"))


def test_update_proposes_manifest_replacement_for_dead_binding(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead binding gets the first accept-chain model that discovery confirms."""
    (config_dir / "model-bindings.yaml").write_text(_dead_default_bindings())
    chain = _codex_standard_chain()
    confirmed = chain[-1]
    calls = _probe(monkeypatch, lambda agent: _discovered("model-bulk", "model-max", confirmed))

    result = CliRunner().invoke(models_main, ["update", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["proposals"] == [
        {
            "harness": "codex-cli",
            "tier": "default",
            "current": "dead-model",
            "proposed": confirmed,
            "reason": "bound model unavailable; first confirmed model of the adapter accept chain",
        }
    ]
    assert payload["verified_refresh"] == []
    asked = set(calls[0][1] or [])
    assert {"dead-model", *chain} <= asked


@pytest.mark.parametrize("failure", ["none-confirmed", "probe-raises"])
def test_update_proposes_nothing_without_confirmed_replacement(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """No confirmed candidate, or a failing probe: no model is invented."""
    (config_dir / "model-bindings.yaml").write_text(_dead_default_bindings())

    def _answer(agent):
        if failure == "probe-raises":
            raise RuntimeError("probe crashed")
        return _discovered("model-bulk", "model-max", "unrelated")

    _probe(monkeypatch, _answer)

    result = CliRunner().invoke(models_main, ["update", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    if failure == "probe-raises":
        assert payload["proposals"] == []
        assert "probe crashed" in payload["errors"]["codex-cli"]
    else:
        assert payload["proposals"] == [
            {
                "harness": "codex-cli",
                "tier": "default",
                "current": "dead-model",
                "proposed": None,
                "reason": "bound model unavailable and no accept-chain model confirmed; edit it by hand",
            }
        ]


def _apply_with_confirmed(monkeypatch: pytest.MonkeyPatch, *extra: str) -> str:
    confirmed = _codex_standard_chain()[-1]
    _probe(monkeypatch, lambda agent: _discovered("model-bulk", "model-max", confirmed, *extra))
    return confirmed


def test_update_apply_replaces_dead_binding_and_backs_up(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--apply writes the confirmed replacement, keeps a backup, and dispatch reads it."""
    from superharness.engine import model_router

    target = config_dir / "model-bindings.yaml"
    original = _dead_default_bindings().encode()
    target.write_bytes(original)
    confirmed = _apply_with_confirmed(monkeypatch)

    result = CliRunner().invoke(models_main, ["update", "--apply"])

    assert result.exit_code == 0, result.output
    assert model_router._resolve_runtime_binding_model("codex-cli", "standard") == confirmed
    backups = list(config_dir.glob("model-bindings.yaml.bak-*"))
    assert [b.read_bytes() for b in backups] == [original]


def test_update_apply_preserves_comments(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every comment of the operator's file survives --apply."""
    target = config_dir / "model-bindings.yaml"
    text = "# operator header\n" + _dead_default_bindings().replace(
        "          id: dead-model", "          id: dead-model  # inline note"
    ).replace("harnesses:", "# harness section\nharnesses:")
    target.write_text(text)
    _apply_with_confirmed(monkeypatch)

    result = CliRunner().invoke(models_main, ["update", "--apply"])

    assert result.exit_code == 0, result.output
    written = target.read_text()
    for comment in ("# operator header", "# harness section", "# inline note"):
        assert comment in written


def test_update_apply_bumps_verified_for_confirmed_providers(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a provider whose bindings are all confirmed gets today's verified date."""
    from superharness.engine.model_bindings import load_bindings

    old = (date.today() - timedelta(days=30)).isoformat()
    target = config_dir / "model-bindings.yaml"
    target.write_text(f"""schema: 2
providers:
  confirmed-provider:
    verified: {old}
  unknown-provider:
    verified: {old}
harnesses:
  codex-cli:
    default_provider: confirmed-provider
    bindings:
      confirmed-provider:
        default:
          id: codex-default
  pi:
    default_provider: unknown-provider
    bindings:
      unknown-provider:
        default:
          id: pi-default
""")
    _probe(monkeypatch, lambda agent: _discovered("codex-default") if agent == "codex-cli" else [])

    result = CliRunner().invoke(models_main, ["update", "--apply"])

    assert result.exit_code == 0, result.output
    providers = load_bindings(target).data["providers"]
    assert str(providers["confirmed-provider"]["verified"]) == date.today().isoformat()
    assert str(providers["unknown-provider"]["verified"]) == old


def test_update_apply_failed_replace_leaves_original(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing final rename exits 1 with the error and leaves the original bytes."""
    from superharness.commands import models

    target = config_dir / "model-bindings.yaml"
    original = _dead_default_bindings().encode()
    target.write_bytes(original)
    _apply_with_confirmed(monkeypatch)

    def _fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(models.os, "replace", _fail)

    result = CliRunner().invoke(models_main, ["update", "--apply"])

    assert result.exit_code == 1
    assert "disk full" in result.output
    assert target.read_bytes() == original
    assert not list(config_dir.glob(".model-bindings.yaml.*.tmp"))


def test_update_apply_end_to_end(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """init, a dead binding, check --probe fails, update --apply, check --probe passes."""
    from superharness.engine.model_bindings import load_bindings

    runner = CliRunner()
    assert runner.invoke(models_main, ["init"]).exit_code == 0
    target = config_dir / "model-bindings.yaml"
    standard = load_bindings(target).data["harnesses"]["codex-cli"]["bindings"]["adapter-manifest"]["default"]["id"]
    target.write_text(target.read_text().replace(f"id: {standard}", "id: dead-model", 1))
    alive = set(_codex_standard_chain())
    others = set()
    for harness in load_bindings(target).data["harnesses"].values():
        for tier in harness["bindings"]["adapter-manifest"].values():
            others.add(tier["id"])
    _probe(monkeypatch, lambda agent: _discovered(*((others | alive) - {"dead-model"})))

    assert runner.invoke(models_main, ["check", "--probe"]).exit_code == 1
    assert runner.invoke(models_main, ["update", "--apply"]).exit_code == 0
    assert runner.invoke(models_main, ["check", "--probe"]).exit_code == 0


def test_check_json_lists_bindings(config_dir: Path) -> None:
    """--json returns path, status, stale providers and every binding; exit 0 when fresh."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))

    result = CliRunner().invoke(models_main, ["check", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["path"] == str(config_dir / "model-bindings.yaml")
    assert payload["status"] == "ok"
    assert payload["stale_providers"] == []
    assert payload["bindings"] == [
        {"harness": "codex-cli", "provider": "test-provider", "tier": "bulk", "model": "model-bulk"},
        {"harness": "codex-cli", "provider": "test-provider", "tier": "default", "model": "model-default"},
        {"harness": "codex-cli", "provider": "test-provider", "tier": "escalate-1", "model": "model-max"},
    ]
