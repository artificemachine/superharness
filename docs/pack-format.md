# superharness Pack Format

`shux pack` exports and imports portable `.superharness` project state as a
gzip-compressed tar archive (`*.superharness.pack.tar.gz`).

---

## Commands

```
shux pack export [--project <dir>] [--output <file>]
shux pack import <pack-file> [--project <dir>] [--collision skip|overwrite|fail]
```

### Export

```
shux pack export
```

Exports the `.superharness/` directory of the current project (or `--project`)
to a portable tarball named `<project>-<timestamp>Z.superharness.pack.tar.gz`
in the current working directory.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--project / -p` | cwd | Source project root |
| `--output / -o` | `<project>-<ts>.superharness.pack.tar.gz` in cwd | Output file path |

### Import

```
shux pack import myapp-20260101T000000Z.superharness.pack.tar.gz
```

Extracts pack contents into the destination project's `.superharness/`
directory, creating it if absent.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--project / -p` | cwd | Destination project root |
| `--collision` | `skip` | `skip` keep existing; `overwrite` replace; `fail` abort |

---

## Pack Contents

Each pack file contains exactly two things at the top level:

```
superharness-pack.yaml          ← manifest (always present)
.superharness/                  ← sanitized state
```

### Portable entries (always included when present)

| Entry | Description |
|-------|-------------|
| `contract.yaml` | Task contract (project_path scrubbed to `.`) |
| `inbox.yaml` | Dispatch queue (absolute paths scrubbed) |
| `ledger.md` | Append-only ledger |
| `handoffs/` | Session handoff records |
| `decisions.yaml` | Decision log |
| `failures.yaml` | Failure log |
| `discussions/` | Discussion records |
| `modules/` | Module configs |
| `review-lenses/` | Review lens configs |

### Excluded (machine-local state)

| Pattern | Reason |
|---------|--------|
| `watcher.yaml` | Local watcher schedule config |
| `watcher.heartbeat*` | Runtime heartbeat state |
| `watcher-env.yaml` | Machine environment snapshot |
| `dashboard-health.log` | Runtime log |
| `launcher-logs/` | Execution logs |
| `inbox.archive.yaml` | Large historical archive |
| `agents/` | Agent runtime state |
| `session-progress.md` | In-progress session state |
| `session-summary-*.md` | Session summaries |
| `*.flock` | Filesystem locks |
| `heartbeat.yaml` | Runtime heartbeat |
| `contracts/` | Contract copies |

---

## Secret Scrubbing

Before packing, the engine scrubs all YAML and Markdown files:

- `project_path` keys in `contract.yaml` (top-level and per-task) are replaced
  with `"."`.
- All other YAML, Markdown, and text files are scanned with the regex
  `/(?:Users|home)/[^/\s"'<>]+(?:/[^\s"'<>]*)*` and any match is replaced
  with `"."`.

Binary files are packed without modification.

---

## Manifest (`superharness-pack.yaml`)

```yaml
format_version: "1"
created_at: "2026-01-01T00:00:00Z"
source_project: myapp
portable_entries:
  - contract.yaml
  - inbox.yaml
  - ledger.md
  - handoffs
  - decisions.yaml
  - failures.yaml
  - discussions
  - modules
  - review-lenses
excluded: "machine-local state: watcher, heartbeat, env, launcher-logs, agents, session files, lock files"
```

The importer validates `format_version` and rejects unknown versions.

---

## Round-trip guarantee

A `shux pack export` followed by `shux pack import` on a clean destination
preserves all task IDs, status, titles, and ledger entries. Absolute path
fields become `"."` and are not restored (they are machine-local by design).

---

## Use cases

- **Sharing a project skeleton** — export a template project, strip secrets,
  import on a new machine or team member's workstation.
- **Backup and restore** — snapshot portable state before a destructive
  operation; restore with `--collision overwrite`.
- **Agent handoff across machines** — agents receive a pack, import into a
  fresh checkout, and resume work without manual setup.
- **CI bootstrap** — store a baseline pack in the repo and import at the start
  of each CI run to seed `.superharness/` state.
