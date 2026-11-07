"""Hermes Agent harness adapter: registry, manifest, invocation, launcher.

No test here makes a live Hermes model call. Launcher tests put a fake
``hermes`` executable first on PATH that only records what it was given.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import superharness
from superharness.engine.adapter_registry import load_manifest, resolve_launcher
from superharness.harnesses import KNOWN_HARNESSES, get_harness

_SCRIPTS = Path(superharness.__file__).parent / "scripts"
_LAUNCHER = _SCRIPTS / "delegate-to-hermes.sh"

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="Hermes launcher tests execute a POSIX bash script"
)


def test_hermes_is_a_known_harness():
    assert "hermes" in KNOWN_HARNESSES
    assert get_harness("hermes").name == "hermes"


def test_hermes_manifest_declares_launcher_and_binary():
    manifest = load_manifest("hermes")
    assert manifest.name == "hermes"
    assert manifest.launcher_script == "delegate-to-hermes.sh"
    assert manifest.requires.get("bin") == "hermes"
    assert set(manifest.model_tiers) == {"mini", "standard", "max"}
    assert resolve_launcher("hermes", str(_SCRIPTS)) == str(_LAUNCHER)


def test_hermes_invocation_passes_model_unprefixed():
    """Hermes resolves provider from its own config, so the model id is untouched."""
    invocation = get_harness("hermes").build_invocation(
        task={"prompt": "do the thing", "model": "claude-sonnet-4", "effort": "high"},
        project_dir="/tmp/proj",
        non_interactive=True,
    )
    assert invocation.argv == (
        "bash",
        str(_LAUNCHER),
        "--project",
        "/tmp/proj",
        "--prompt",
        "do the thing",
        "--non-interactive",
        "--model",
        "claude-sonnet-4",
        "--effort",
        "high",
    )
    assert invocation.cwd == "/tmp/proj"


def test_hermes_invocation_omits_model_and_effort_when_unset():
    invocation = get_harness("hermes").build_invocation(
        task={"prompt": "p"}, project_dir="/tmp/proj", non_interactive=False
    )
    assert "--model" not in invocation.argv
    assert "--effort" not in invocation.argv
    assert "--non-interactive" not in invocation.argv


def test_hermes_discover_models_is_empty_without_a_native_list_command():
    """Hermes has no offline model-list command; dispatch falls back to its config."""
    assert get_harness("hermes").discover_models() == []


@pytest.fixture
def fake_hermes(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A fake `hermes` first on PATH that records argv, stdin and cwd."""
    record = tmp_path / "record"
    record.mkdir()
    fake = tmp_path / "hermes"
    fake.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" > "$HERMES_RECORD/argv"\n'
        'cat > "$HERMES_RECORD/stdin"\n'
        'pwd > "$HERMES_RECORD/cwd"\n'
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "HERMES_RECORD": str(record),
    }
    return env, record


def _run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_LAUNCHER), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@posix_only
def test_launcher_runs_hermes_oneshot_with_prompt_on_stdin(tmp_path, fake_hermes):
    env, record = fake_hermes
    project = tmp_path / "proj"
    project.mkdir()
    prompt = 'fix "quotes" and $(whoami) and `ticks`'

    result = _run(
        "--project", str(project), "--prompt", prompt, "--non-interactive",
        "--model", "claude-sonnet-4", "--effort", "high", env=env,
    )

    assert result.returncode == 0, result.stderr
    argv = (record / "argv").read_text().splitlines()
    assert argv[:4] == ["chat", "-Q", "--query-file", "-"]
    assert argv[argv.index("-m") + 1] == "claude-sonnet-4"
    assert argv[argv.index("--reasoning") + 1] == "high"
    assert "--yolo" not in argv
    # The prompt travels on stdin verbatim, never as an argv element.
    assert (record / "stdin").read_text().rstrip("\n") == prompt
    assert prompt not in argv
    assert Path((record / "cwd").read_text().strip()).resolve() == project.resolve()


@posix_only
def test_launcher_forwards_yolo_only_when_requested(tmp_path, fake_hermes):
    env, record = fake_hermes
    result = _run("--project", str(tmp_path), "--prompt", "p", "--yolo", env=env)
    assert result.returncode == 0, result.stderr
    assert "--yolo" in (record / "argv").read_text().splitlines()


@posix_only
@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_launcher_help_does_not_invoke_hermes(fake_hermes, help_flag):
    env, record = fake_hermes
    result = _run(help_flag, env=env)
    assert result.returncode == 0
    assert "Usage: delegate-to-hermes.sh" in result.stdout
    assert not (record / "argv").exists()


@posix_only
def test_launcher_rejects_missing_prompt_without_invoking_hermes(fake_hermes):
    env, record = fake_hermes
    result = _run("--project", ".", env=env)
    assert result.returncode == 1
    assert "No prompt" in result.stderr
    assert not (record / "argv").exists()


@posix_only
def test_launcher_rejects_unknown_effort_without_invoking_hermes(tmp_path, fake_hermes):
    env, record = fake_hermes
    result = _run("--project", str(tmp_path), "--prompt", "p", "--effort", "turbo", env=env)
    assert result.returncode == 2
    assert "effort" in result.stderr
    assert not (record / "argv").exists()


@posix_only
def test_launcher_reports_missing_hermes_binary(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    result = _run("--project", str(tmp_path), "--prompt", "p", env=env)
    assert result.returncode == 127
    assert "hermes" in result.stderr


# --- Keychain-backed API key -------------------------------------------------

_FAKE_SECRET = "fake-secret-not-a-real-key"


@pytest.fixture
def fake_keychain(tmp_path: Path, fake_hermes) -> tuple[dict[str, str], Path]:
    """Add a fake `security` to PATH; make fake hermes record its DEEPSEEK_API_KEY."""
    env, record = fake_hermes
    security_log = tmp_path / "security-argv"
    fake_security = tmp_path / "security"
    fake_security.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$@" > "{security_log}"\n'
        f'if [[ "${{FAKE_SECURITY_FAIL:-}}" == 1 ]]; then echo "not found" >&2; exit 44; fi\n'
        f'printf "%s\\n" "{_FAKE_SECRET}"\n'
    )
    fake_security.chmod(0o755)
    hermes = tmp_path / "hermes"
    hermes.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" > "$HERMES_RECORD/argv"\n'
        'cat > "$HERMES_RECORD/stdin"\n'
        'printf "%s" "${DEEPSEEK_API_KEY:-<unset>}" > "$HERMES_RECORD/key"\n'
    )
    hermes.chmod(0o755)
    env = {k: v for k, v in env.items() if k != "DEEPSEEK_API_KEY"}
    return env, record


@posix_only
def test_launcher_passes_keychain_key_to_hermes_by_environment_only(tmp_path, fake_keychain):
    env, record = fake_keychain
    result = _run("--project", str(tmp_path), "--prompt", "p", env=env)

    assert result.returncode == 0, result.stderr
    assert (record / "key").read_text() == _FAKE_SECRET
    # The secret never appears in hermes argv, its stdin, or launcher output.
    assert _FAKE_SECRET not in (record / "argv").read_text()
    assert _FAKE_SECRET not in (record / "stdin").read_text()
    assert _FAKE_SECRET not in result.stdout + result.stderr
    # Lookup asks for the password of the `env:<NAME>` service, nothing else.
    security_argv = (Path(env["PATH"].split(os.pathsep)[0]) / "security-argv").read_text().splitlines()
    assert security_argv[:1] == ["find-generic-password"]
    assert security_argv[security_argv.index("-s") + 1] == "env:DEEPSEEK_API_KEY"
    assert "-w" in security_argv


@posix_only
def test_launcher_keeps_an_existing_environment_key(tmp_path, fake_keychain):
    env, record = fake_keychain
    env = {**env, "DEEPSEEK_API_KEY": "already-exported"}
    result = _run("--project", str(tmp_path), "--prompt", "p", env=env)

    assert result.returncode == 0, result.stderr
    assert (record / "key").read_text() == "already-exported"
    assert not (Path(env["PATH"].split(os.pathsep)[0]) / "security-argv").exists()


@posix_only
def test_launcher_warns_and_continues_when_keychain_lookup_fails(tmp_path, fake_keychain):
    env, record = fake_keychain
    env = {**env, "FAKE_SECURITY_FAIL": "1"}
    result = _run("--project", str(tmp_path), "--prompt", "p", env=env)

    assert result.returncode == 0, result.stderr
    assert "Keychain" in result.stderr and "DEEPSEEK_API_KEY" in result.stderr
    assert (record / "key").read_text() == "<unset>"
