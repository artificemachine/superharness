"""
superharness pack engine — export and import portable .superharness project state.

Pack format: <name>-<timestamp>.superharness.pack.tar.gz
Contents:
  superharness-pack.yaml   — pack manifest (format version, created_at, source_project)
  .superharness/           — sanitized state directory
    contract.yaml          — project_path fields scrubbed to "."
    inbox.yaml             — absolute paths scrubbed
    ledger.md              — portable ledger
    handoffs/              — session handoff records
    decisions.yaml         — decision log
    failures.yaml          — failure log
    discussions/           — discussion records
    modules/               — module configs
    review-lenses/         — review lens configs

Excluded (machine-local):
  watcher.yaml             — local watcher config
  watcher.heartbeat*       — runtime heartbeat state
  watcher-env.yaml         — machine environment snapshot
  dashboard-health.log     — dashboard runtime log
  launcher-logs/           — launcher execution logs
  inbox.archive.yaml       — large machine-specific archive
  agents/                  — agent runtime state
  session-progress.md      — session-specific state
  session-summary-*.md     — session summaries
  *.flock                  — filesystem locks
  heartbeat.yaml           — runtime heartbeat
  contracts/               — contract copies (machine-local)
"""
from __future__ import annotations

import copy
import io
import os
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

PACK_FORMAT_VERSION = "1"

PORTABLE_ENTRIES = [
    "contract.yaml",
    "inbox.yaml",
    "ledger.md",
    "handoffs",
    "decisions.yaml",
    "failures.yaml",
    "discussions",
    "modules",
    "review-lenses",
]

MACHINE_LOCAL_PATTERNS = [
    r"^watcher\.yaml$",
    r"^watcher\.heartbeat",
    r"^watcher-env\.yaml$",
    r"^dashboard-health\.log$",
    r"^launcher-logs(/|$)",
    r"^inbox\.archive\.yaml$",
    r"^agents(/|$)",
    r"^session-progress\.md$",
    r"^session-summary",
    r"\.flock$",
    r"^heartbeat\.yaml$",
    r"^contracts(/|$)",
    r"^__pycache__(/|$)",
    r"\.tmp$",
]

ABS_PATH_PATTERN = re.compile(r'/(?:Users|home)/[^/\s"\'<>]+(?:/[^\s"\'<>]*)*')


def _is_machine_local(rel_path: str) -> bool:
    for pattern in MACHINE_LOCAL_PATTERNS:
        if re.match(pattern, rel_path):
            return True
    return False


def _scrub_string(value: str) -> str:
    return ABS_PATH_PATTERN.sub(".", value)


def _scrub_value(value):
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_scrub_value(item) for item in value]
    elif isinstance(value, str):
        return _scrub_string(value)
    return value


def scrub_contract(doc: dict) -> dict:
    """Scrub machine-local fields from a contract.yaml document."""
    result = copy.deepcopy(doc)
    if isinstance(result, dict):
        if "project_path" in result:
            result["project_path"] = "."
        tasks = result.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    if "project_path" in task:
                        task["project_path"] = "."
                    for key in ("summary", "stopped_reason", "title"):
                        if key in task and isinstance(task[key], str):
                            task[key] = _scrub_string(task[key])
    return result


def scrub_yaml_doc(content: str) -> str:
    """Parse YAML, scrub absolute paths, return scrubbed YAML string."""
    try:
        doc = yaml.safe_load(content)
    except Exception:
        return _scrub_string(content)
    if doc is None:
        return content
    scrubbed = _scrub_value(doc)
    return yaml.dump(scrubbed, default_flow_style=False, allow_unicode=True)


def _add_file_to_tar(
    tar: tarfile.TarFile,
    file_path: Path,
    arcname: str,
    scrub_secrets: bool = False,
) -> None:
    suffix = file_path.suffix.lower()
    should_scrub = suffix in (".yaml", ".yml", ".md", ".txt", ".json")
    if should_scrub:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            if suffix in (".yaml", ".yml"):
                if file_path.name == "contract.yaml":
                    doc = yaml.safe_load(raw)
                    if isinstance(doc, dict):
                        doc = scrub_contract(doc)
                        scrubbed = yaml.dump(doc, default_flow_style=False, allow_unicode=True)
                    else:
                        scrubbed = _scrub_string(raw)
                else:
                    scrubbed = scrub_yaml_doc(raw)
            else:
                scrubbed = _scrub_string(raw)
            if scrub_secrets:
                from superharness.guard.redact import redact as _redact_secrets
                scrubbed = _redact_secrets(scrubbed)
            data = scrubbed.encode("utf-8")
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            return
        except (OSError, UnicodeDecodeError):
            pass
    tar.add(str(file_path), arcname=arcname)


def export_pack(
    project_dir: str | Path,
    output_path: str | Path | None = None,
    scrub: bool = False,
) -> Path:
    """Export portable .superharness state to a .tar.gz pack file.

    When scrub=True, text files are passed through the credential redactor
    before being bundled so API keys, tokens, and private keys are stripped.
    """
    project_dir = Path(project_dir).resolve()
    sh_dir = project_dir / ".superharness"
    if not sh_dir.is_dir():
        raise FileNotFoundError(f"No .superharness directory found at {project_dir}")

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    project_name = project_dir.name

    if output_path is None:
        output_path = Path.cwd() / f"{project_name}-{ts}.superharness.pack.tar.gz"
    else:
        output_path = Path(output_path)

    manifest = {
        "format_version": PACK_FORMAT_VERSION,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_project": project_name,
        "portable_entries": PORTABLE_ENTRIES,
        "excluded": (
            "machine-local state: watcher, heartbeat, env, "
            "launcher-logs, agents, session files, lock files"
        ),
    }
    manifest_bytes = yaml.dump(manifest, default_flow_style=False, allow_unicode=True).encode("utf-8")

    with tarfile.open(str(output_path), "w:gz") as tar:
        info = tarfile.TarInfo(name="superharness-pack.yaml")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        for entry_name in PORTABLE_ENTRIES:
            entry_path = sh_dir / entry_name
            if not entry_path.exists():
                continue
            if entry_path.is_file():
                _add_file_to_tar(tar, entry_path, f".superharness/{entry_name}", scrub_secrets=scrub)
            elif entry_path.is_dir():
                for root, dirs, files in os.walk(str(entry_path)):
                    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                    for fname in sorted(files):
                        fpath = Path(root) / fname
                        rel = str(fpath.relative_to(sh_dir))
                        if not _is_machine_local(rel):
                            _add_file_to_tar(tar, fpath, f".superharness/{rel}", scrub_secrets=scrub)

    return output_path


CollisionPolicy = Literal["skip", "overwrite", "fail"]


def import_pack(
    pack_path: str | Path,
    dest_dir: str | Path,
    collision: CollisionPolicy = "skip",
) -> dict:
    """Import a .superharness pack into dest_dir."""
    pack_path = Path(pack_path)
    dest_dir = Path(dest_dir).resolve()

    if not pack_path.is_file():
        raise FileNotFoundError(f"Pack file not found: {pack_path}")

    result: dict = {"imported": [], "skipped": [], "manifest": {}}

    with tarfile.open(str(pack_path), "r:gz") as tar:
        members = tar.getmembers()

        manifest_member = next(
            (m for m in members if m.name == "superharness-pack.yaml"), None
        )
        if manifest_member is None:
            raise ValueError("Pack file is missing superharness-pack.yaml manifest")

        f = tar.extractfile(manifest_member)
        if f:
            manifest = yaml.safe_load(f.read().decode("utf-8")) or {}
            result["manifest"] = manifest
            fmt = str(manifest.get("format_version", ""))
            if fmt != PACK_FORMAT_VERSION:
                raise ValueError(
                    f"Unsupported pack format version: {fmt!r} (expected {PACK_FORMAT_VERSION!r})"
                )

        if collision == "fail":
            collisions = [
                m.name for m in members
                if m.name != "superharness-pack.yaml" and (dest_dir / m.name).exists()
            ]
            if collisions:
                raise RuntimeError(
                    f"Import aborted: {len(collisions)} collision(s) found: {collisions[:5]}"
                )

        for member in members:
            if member.name == "superharness-pack.yaml":
                continue
            dest_file = dest_dir / member.name
            if dest_file.exists():
                if collision == "skip":
                    result["skipped"].append(member.name)
                    continue
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                dest_file.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                f = tar.extractfile(member)
                if f:
                    dest_file.write_bytes(f.read())
                    result["imported"].append(member.name)

    return result
