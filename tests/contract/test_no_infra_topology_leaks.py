"""Iteration 6 — no tracked file may leak private-infrastructure topology.

The maintainer-identity guard (test_no_tracked_personal_data.py) only
covers the owner's username and home path. PR #77 (2026-08-03 triage)
proved that is not enough: its file contents exposed internal hostnames
(vm740/vm903/vm913/P510), a collaborator username, NAS mounts
(/mnt/pve/gs-nas/...), and control-token paths — and CI was fully green.

This test scans every tracked file for *classes* of infrastructure
topology (hostname shapes, private IP ranges, NAS mounts, token paths,
any-user home paths). No private string is hardcoded here — the exact
private identifiers (usernames, specific hosts, LAN domains) live in a
gitignored blocklist read by _blocklist_lines() when present, so this
repo never commits the very strings it exists to keep out.

Gitleaks (CI job "Gitleaks") covers real secrets and high-entropy
strings; GitHub native push protection covers confirmed secret formats
server-side. This test is the topology layer neither of those sees.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# This test file itself is exempt — its regex sources and docstrings
# necessarily discuss the patterns (no match can fire on a pattern's own
# literal text, but the blocklist section below proves the principle).
_SELF = "tests/contract/test_no_infra_topology_leaks.py"

# Gitignored (see .gitignore `.security-blocklist.txt`). Local machines may
# list exact private strings — one per line — that must never appear in any
# tracked file (usernames, LAN domains, specific hosts). CI lacks the file,
# so it runs the generic patterns only; the blocklist is the stronger
# local-only jaw of the ratchet.
_BLOCKLIST_FILE = _REPO_ROOT / ".security-blocklist.txt"

# ---------------------------------------------------------------------------
# Generic infra-topology patterns. Deliberately class-shaped, never
# identifier-shaped: catching `vm\d{3}` doesn't require knowing which
# hosts exist, and stays useful when the fleet changes. Each pattern is
# written as a joined tuple so its own literal source can never match
# itself in this file.
# ---------------------------------------------------------------------------
_HOSTNAME_SHAPES = [
    r"\bvm\d{3}\b",  # vm740, vm903, vm913...
    r"\bP\d{3,4}\b",  # P510-style workstation ids
    r"\bSite-[A-Za-z]\b",  # Site-A/Site-B style datacenter ids
    r"\b[\w-]+-sidecar\b",  # vm903-sidecar-style model/device refs
]

_PRIVATE_IP_RANGES = [
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    r"\b192\.168\.\d{1,3}\.\d{1,3}\b",
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b",
]

_INFRA_MARKERS = [
    r"/mnt/pve/",  # Proxmox NAS mount
    r"\bgs-nas\b",  # NAS share namespace
    r"control-token",  # token file paths (RMDI-style routers)
    r"/var/lib/rmdi/",
]

_PERSONAL_CLOUD_PATHS = [
    r"GoogleDrive-[^/\s<>]*@[^/\s<>]+",
]

_USER_HOME_PATTERNS = [
    # Any real macOS/Linux user's home path. Placeholder fixture users
    # (test/someuser/otheruser/example/dummy/fake/demo/user/alice/bob) are
    # excluded at the pattern level — they are ubiquitous in test fixtures
    # and are not private. Any other username IS treated as a potential
    # real person (incl. future collaborators).
    r"/Users/(?!test|someuser|otheruser|example|dummy|fake|demo|user|alice|bob|admin|root)\w+/",
    r"/home/(?!test|someuser|otheruser|example|dummy|fake|demo|user|alice|bob|admin|root)\w+/",
]

_ALL_PATTERNS: list[tuple[str, str]] = []
for _label, _patterns in (
    ("hostname", _HOSTNAME_SHAPES),
    ("private-ip", _PRIVATE_IP_RANGES),
    ("infra-marker", _INFRA_MARKERS),
    ("personal-cloud", _PERSONAL_CLOUD_PATHS),
    ("user-home", _USER_HOME_PATTERNS),
):
    for _p in _patterns:
        _ALL_PATTERNS.append((f"{_label}:{_p}", re.compile(_p)))

# ---------------------------------------------------------------------------
# Documented allowlist — hits on *placeholder* values only, each with the
# reason. May only shrink; adding a file here requires a comment stating
# why the occurrence is not private. This allowlist exists so the ratchet
# can be strict by default without inventing new vocabulary each run.
# ---------------------------------------------------------------------------
LEAK_ALLOWLIST: dict[str, tuple[str, ...]] = {
    # Prompt default in the onboarding wizard — 10.0.0.1 is an example
    # placeholder the user replaces; not a real endpoint.
    "src/superharness/commands/onboard.py": ("private-ip",),
    # Sanitization guidance doc — names 10.0.0.1 as the *example* to use
    # instead of a real IP. Documenting the rule, not leaking an address.
    "docs/archive/plan-module-system.md": ("private-ip",),
    # Gateway-wizard test fixture — user@10.0.0.10 is a placeholder relay
    # host (RFC-1918 example range, no real endpoint).
    "tests/unit/test_gateway_wizard.py": ("private-ip",),
}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def _blocklist_lines() -> list[str]:
    if not _BLOCKLIST_FILE.exists():
        return []
    lines = [
        ln.strip()
        for ln in _BLOCKLIST_FILE.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return lines


def _read(rel: str) -> str:
    try:
        return (_REPO_ROOT / rel).read_text(errors="ignore")
    except Exception:
        return ""


def test_no_infra_topology_patterns_in_tracked_files():
    """Generic class-shaped patterns: hostname shapes, private IPs, NAS
    mounts, token paths, personal cloud paths, and any-user home paths. Hits on documented
    placeholder values (LEAK_ALLOWLIST) are exempt with a stated reason."""
    offenders: dict[str, list[str]] = {}
    for rel in _tracked_files():
        if rel == _SELF:
            continue
        text = _read(rel)
        hits = [label for label, rx in _ALL_PATTERNS if rx.search(text)]
        allowed = set(LEAK_ALLOWLIST.get(rel, ()))
        unexpected = [h for h in hits if h.split(":", 1)[0] not in allowed]
        if unexpected:
            offenders[rel] = unexpected
    assert not offenders, (
        "tracked files leak private-infrastructure topology "
        f"(hostnames/private-IPs/NAS/token-paths/personal-cloud-paths/user-homes): {offenders}. "
        "Remove the identifier or abstract it (e.g. vm740 -> <router-host>) "
        "before merging to a public repo."
    )


def test_no_blocklisted_identifiers_in_tracked_files():
    """Local-only jaw: exact private strings from the gitignored blocklist
    must not appear in any tracked file. Skipped in CI where the blocklist
    file is absent (the generic patterns above still run there)."""
    blocklist = _blocklist_lines()
    if not blocklist:
        return  # CI: generic patterns already ran; nothing local to add
    offenders: dict[str, list[str]] = {}
    for rel in _tracked_files():
        if rel == _SELF:
            continue
        text = _read(rel)
        hits = [ident for ident in blocklist if ident.lower() in text.lower()]
        if hits:
            offenders[rel] = hits
    assert not offenders, (
        "tracked files contain gitignored-blocklist identifiers "
        f"(private usernames/domains/hosts): {offenders}"
    )
