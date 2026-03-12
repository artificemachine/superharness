# superharness — Release Notes

All notable releases with semver tags. For the full iteration log, see `CHANGELOG.md`.

---

## v0.7.0 — Adoption Hardening (2026-03-10)

### Added
- `superharness watch --foreground --interval SEC` — cross-platform continuous watcher (no launchd required)
- `superharness uninstall [--dry-run] [--all]` — clean removal of system artifacts
- `superharness doctor --check` — CI-friendly mode (exits non-zero on any warning)
- Platform-specific install hints in `doctor` output for each missing dependency
- `requirements.txt` and `.ruby-version` for explicit dependency declaration
- `RELEASES.md` (this file) for semver release notes

### Changed
- `superharness init` no longer installs launchd watcher by default; use `--with-watcher` to opt in
- QUICKSTART.md rewritten: zero manual YAML editing required (uses `task create` CLI)
- README "3-Step Start" replaced with "Quick Start" including `doctor` as step 0

### Fixed
- `init-project.sh` silently installing launchd plist without user consent
- No discoverable uninstall path for system artifacts
- `doctor` printing FAIL/WARN without remediation hints

---

## v0.6.0 — Reliability Pass (2026-03-10)

### Added
- Task `failed` and `stopped` statuses with required `reason` and `summary` fields
- Deadline enforcement in watcher cycle
- Monitor UI polish (status badges, sort order)
- Watcher timeout recovery and lock guard

### Fixed
- Stabilized watcher/monitor tests
- Cleared security gate findings

---

## v0.5.0 — Initial Public Shape (2026-03-08)

First version with complete CLI surface: init, delegate, enqueue, dispatch, watch, doctor, hygiene, monitor-ui.
