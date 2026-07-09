# CONCEPT — Notifications + State Isolation

Status: discussion draft, not yet planned for implementation.
Date: 2026-05-18.
Origin: design conversation with owner about adding lifecycle notifications (Telegram/Slack/email/Signal) and the resulting concern that per-project `.superharness/state.db` could leak via accidental `git add`.

This document captures the full design discussion. It is the source for a future TDD plan.

---

## 1. Goal

Let the user (or team) opt into messages (Telegram, Slack, email, Signal) when lifecycle events fire on tasks and discussions:

- `task.created`
- `task.failed`
- `discuss.started`
- `report_ready`
- `review_requested`

And do so without:

- Leaking bot tokens / API keys into the repo, the DB, agent context windows, or process listings.
- Letting per-project state files end up in a public push by accident.
- Breaking parallel worktree workflows.
- Making the debug surface worse than today's `sqlite3 .superharness/state.db`.

---

## 2. CLI Surface

### 2.1 Channels

```
shux notify channel add supah --kind telegram --chat-id 7891234567
  prompts (stdin, masked): "Bot token: "
  writes token to OS keychain: superharness/supah/bot_token
  writes DB row with keychain_ref + non-secret config

shux notify channel list
  NAME         KIND       ENABLED  LAST USED            LAST ERROR
  supah        telegram   yes      2026-05-18 14:22     -
  team-slack   slack      no       -                    -

shux notify channel test supah
  sends "Supah online — superharness <version> on <host>"

shux notify channel rotate supah
  prompts for new token, swaps reference atomically only after test send succeeds

shux notify channel disable supah        # soft off, keep config
shux notify channel rm supah             # deletes DB row + keychain entry
```

### 2.2 Subscriptions

```
shux notify subscribe --channel supah --events task.created,report_ready
shux notify subscribe --channel supah --event task.created --filter 'owner=claude-code'
shux notify unsubscribe --channel supah --event task.created

shux notify status
  USER       EVENT             CHANNEL    FILTER
  newblacc   task.created      supah      -
  newblacc   report_ready      supah      -
```

### 2.3 Internal + diagnostics

```
shux notify send --event task.created --task T-042   # internal, called by lifecycle hooks
shux notify log --limit 20                           # recent sends
shux notify doctor                                   # keychain reachable? tokens valid?
```

---

## 3. Schema

Two databases, two locations. Per-project state stays project-scoped. Notification config is global (yours, not the project's).

### 3.1 Global notify DB (`~/.config/superharness/notify.db`)

```sql
CREATE TABLE notification_channels (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,            -- 'supah', 'team-slack'
    kind            TEXT NOT NULL CHECK (kind IN ('telegram','slack','email','signal')),
    keychain_ref    TEXT NOT NULL,                   -- e.g. 'superharness/supah/bot_token'
    config_json     TEXT NOT NULL,                   -- non-secret: chat_id, webhook path, from-addr
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT,
    last_error      TEXT
);

CREATE TABLE notification_subscriptions (
    id              INTEGER PRIMARY KEY,
    user            TEXT NOT NULL,
    channel_id      INTEGER NOT NULL REFERENCES notification_channels(id) ON DELETE CASCADE,
    event           TEXT NOT NULL,
    project_hash    TEXT,                            -- NULL = all projects
    filter_json     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE(user, channel_id, event, project_hash)
);

CREATE TABLE notification_log (
    id              INTEGER PRIMARY KEY,
    channel_id      INTEGER NOT NULL REFERENCES notification_channels(id),
    event           TEXT NOT NULL,
    project_hash    TEXT,
    task_id         TEXT,
    status          TEXT NOT NULL CHECK (status IN ('sent','failed','suppressed','coalesced')),
    error           TEXT,
    sent_at         TEXT NOT NULL,
    payload_hash    TEXT                             -- sha256, NOT the payload
);

CREATE INDEX idx_notif_log_sent_at ON notification_log(sent_at);
CREATE INDEX idx_notif_sub_event ON notification_subscriptions(event);
```

Why hash, not payload: an accidentally-committed `notify.db` then leaks zero message content. The `keychain_ref` is also useless to anyone without your keychain.

---

## 4. Credential Handling

Principle: agents emit events, only the dispatcher holds secrets, secrets live in the OS keychain.

| Layer | Control |
|-------|---------|
| Storage | macOS Keychain via `security add-generic-password`. Linux: `secret-tool` (libsecret). Last-resort fallback: `~/.config/superharness/secrets/<name>` chmod 0600. |
| Acquisition | `shux notify channel add` reads the token from stdin with TTY echo off. Reject if `--token` is passed on argv (argv leaks to `ps` and shell history). |
| In-memory | Token loaded only inside the `shux notify send` subprocess. Held in a `SecretStr`-style wrapper. Zeroed after the HTTP call returns. |
| Subprocess boundary | Agents call `shux notify send --event X --task Y`. They never receive the token, never see env vars containing it. Token lifetime = milliseconds. |
| Env hygiene | `shux notify send` runs with a scrubbed env: only `PATH`, `HOME`, `LANG`. No inherited `*_TOKEN`/`*_KEY` vars leak. |
| Logs | Dispatcher logs event, channel name, status. Never the token, never the message body. `payload_hash` only. |
| Git | `notify.db` lives outside any repo. Pre-commit hook (existing check 1) extended to scan staged files for bot-token shapes: Telegram (`\d{8,10}:[A-Za-z0-9_-]{35}`), Slack webhook (`hooks.slack.com/services/T[A-Z0-9]+/B[A-Z0-9]+/`), SMTP creds. |
| Transport | HTTPS-only, cert verification on, 5s timeout, no retries on 401/403 (rotate, don't retry). |
| Message content | Before send: regex-scrub the body for token shapes. If a scrub triggers, log as `suppressed`. Means an agent tried to send a secret. |
| Rotation | `shux notify channel rotate` is one command. Old token deleted only after new token's test send succeeds. |
| Rate limit | Coalesce: 3 events of the same type within 60s become one summary. Hard cap: 30 messages/hour/channel. Excess goes to `suppressed`. |
| Audit | `shux notify log` + dashboard panel. Failed sends with 401/403 flagged red, prompt rotation. |

Concrete walkthrough — adding `supah`:

```
$ shux notify channel add supah --kind telegram --chat-id 7891234567
Bot token: ************************************************
✓ Stored in keychain: superharness/supah/bot_token
✓ Channel 'supah' created (telegram, chat_id=7891234567)
→ Run 'shux notify channel test supah' to verify
→ Run 'shux notify subscribe --channel supah --events task.created,report_ready' to start receiving

$ shux notify channel test supah
✓ Sent test message to supah (chat_id=7891234567) in 287ms

$ shux notify subscribe --channel supah --events task.created,report_ready
✓ Subscribed newblacc to 2 events via supah
```

---

## 5. State Isolation (the bigger structural fix)

### 5.1 Concern

Today, per-project state lives in `.superharness/state.db`. Even with `.gitignore`, one stray `git add -A` (or another agent's fresh-clone ignore drift) can push task history, decisions, and handoffs into a public repo. Adding notification subscriptions to that DB would compound the risk.

### 5.2 Split

State and config are different things. Today the project conflates them.

| Data | Today | Should be |
|------|-------|-----------|
| Project state (tasks, handoffs, decisions, ledger) | `.superharness/state.db` | `~/.local/state/superharness/projects/<hash>/state.db` |
| Project exports (contract snapshots, .md handoffs for humans) | `.superharness/` | stays — regenerable, already gitignored |
| Project config (autonomy mode, agent roster, deadlines) | `.superharness/config.yaml` | stays in repo — versioned |
| Cross-project secrets (bot tokens, API keys) | nowhere | OS keychain, never on disk |
| Cross-project prefs (notification channels, subs) | n/a | `~/.config/superharness/notify.db` |

### 5.3 XDG-style layout

```
~/.config/superharness/                  # user config, optionally dotfile-versioned
  notify.db                              # channels + subs (refs only, no secrets)
  defaults.yaml                          # default autonomy, default agents

~/.local/state/superharness/             # per-project state, NEVER in any repo
  projects/
    <sha256(worktree_path)[:12]>/
      state.db                           # tasks, handoffs, decisions
      meta.json                          # {"path": "...", "name": "..."}
  notification_log.db                    # cross-project send log

~/.cache/superharness/                   # regenerable
  fts_index/
  agent_warmups/

~/Library/Logs/superharness/             # macOS (already used)
  *.log
```

Hashing the worktree path (not the repo root) means worktrees get isolated state by default. Project rename → re-link via `shux init --link <hash>`.

### 5.4 What `.superharness/` becomes

Thin and intentionally shareable:

```
.superharness/
  config.yaml          # autonomy, agents, deadlines — versioned
  workflow.yaml        # versioned
  README.md            # "state lives in ~/.local/state/superharness/"
  .gitignore           # allowlist pattern
```

`.gitignore` inside `.superharness/`:

```
*
!.gitignore
!config.yaml
!workflow.yaml
!README.md
```

Allowlist beats blocklist — anything new defaults to ignored. Future features can't accidentally start writing committable junk.

### 5.5 Defense in depth (assume gitignore will fail)

| Layer | Control |
|-------|---------|
| Location | State lives outside the repo. Can't add what isn't there. |
| Gitignore allowlist | `.superharness/` whitelists only versionable files. |
| Pre-commit hook | Extend existing check to block staging of `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite*` anywhere in the repo. Opt-out: `ALLOW_DB=1` for rare fixtures. |
| DB content scan | If `ALLOW_DB=1`, sample staged DB with `sqlite3 file '.schema'` and refuse on tables matching `notification_channels|secret*|credential*|token*`. |
| Secret tables fallback | Even on accidental commit, DB only holds `keychain_ref` strings. Useless without your keychain. |

### 5.6 Migration

`shux migrate-state` one-shot:

1. Detect existing `.superharness/state.db`.
2. Move to `~/.local/state/superharness/projects/<hash>/state.db`.
3. Write `meta.json` with project path.
4. Tighten `.superharness/.gitignore` to allowlist.
5. `git rm --cached` anything previously tracked that shouldn't be.

`shux doctor` adds: "state.db found inside repo root → run `shux migrate-state`".

---

## 6. Resolved Concerns

### 6.1 Worktree workflow

Problem: `git worktree add ../sh-feat-x` shares the same git root. Naive project-hashing would collide.

Fix: hash the worktree path, not the repo root.

```python
def project_hash(cwd: Path) -> str:
    toplevel = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    return sha256(toplevel.encode()).hexdigest()[:12]
```

Result: each worktree has its own state dir, automatically isolated. Add `shux worktree link <other-hash>` for the rare case you want to share, and `shux worktree promote <hash>` to merge a feature worktree's task history back into main when the branch closes. Default = isolated, which is correct for parallel deep work.

### 6.2 Backup story (works for any user, not just LAN-GitLab owners)

Problem: state is no longer in the repo, so `git push` no longer backs it up.

Fix: tiered options — pick what fits the user.

**Tier 0 — `shux backup` (built-in, no external dependencies)**:

```
shux backup                          # tars current project state → ~/Backups/superharness/<hash>-<ts>.tar.zst
shux backup --all                    # all projects
shux backup --to <dir>               # custom destination
shux backup restore <archive>        # explicit restore
shux backup list                     # what backups exist, age, size
```

Implementation uses `sqlite3 .backup` (online, no lock fight with the watcher) + `tar --zstd`. Schedulable via existing `shux schedule`:

```
shux schedule add backup-daily --cron "0 3 * * *" --cmd "shux backup --all"
```

This is the default. It works on every machine with no setup beyond running the command.

**Tier 1 — host-level automatic backup (zero config for many users)**:

The state dir lives under `~/.local/state/`, which is already covered by:

- macOS Time Machine (default opt-in for the home directory)
- Linux backup tools that snapshot `$HOME` (timeshift with --include-home, restic profiles, borg)
- Windows File History (when WSL state is mounted into Windows backup scope)

`shux doctor` detects the platform and prints:

```
✓ ~/.local/state/superharness/ is inside your home dir; verify your host backup
  (Time Machine on macOS, restic/borg/timeshift on Linux) covers it.
  Run 'shux backup' for an explicit project archive.
```

For most users this is enough. They already back up `$HOME` and don't need a second system.

**Tier 2 — `shux backup --to <cloud-synced-folder>`**:

Most users have one of: iCloud Drive, Google Drive, Dropbox, OneDrive, Box, pCloud, MEGA, Syncthing. All of these surface as ordinary directories on disk. The CLI does not need a vendor SDK — it writes the tarball, the sync client uploads it.

Default paths per provider — macOS:

| Provider | Default sync path | Notes |
|----------|-------------------|-------|
| iCloud Drive | `~/Library/Mobile Documents/com~apple~CloudDocs/` | Native on macOS. Watch out: "Optimize Mac Storage" can evict the tarball from local disk, making restores slow (must re-download from iCloud). Disable for the backup subfolder, or pin with `brctl evict` exclusion. |
| Google Drive (Desktop) | `~/Library/CloudStorage/GoogleDrive-<email>/My Drive/` | Two modes: "Mirror" keeps a full local copy (safe, uses disk); "Stream" only fetches on demand (saves disk, but a backup file you never open may not actually be uploaded — sync is lazy on stream mode). For backups, force Mirror mode, OR use a dedicated `My Drive/superharness-backups/` folder set to "Available offline". |
| Dropbox | `~/Dropbox/` or `~/Library/CloudStorage/Dropbox/` | Cleanest of the three. Smart Sync has the same eviction caveat as iCloud — mark the backup folder "Local" / "Available offline". |
| OneDrive | `~/Library/CloudStorage/OneDrive-<tenant>/` | Files On-Demand same caveat. Right-click → "Always keep on this device" for the backup folder. |
| Box | `~/Library/CloudStorage/Box-Box/` | Same pattern, same eviction caveat. |
| pCloud | `~/pCloudDrive/` | FUSE-mounted, not a real directory — writes go straight to cloud. Works, but slower than native sync. |
| MEGA | `~/MEGA/` | End-to-end encrypted by default, which is a Tier-4-for-free bonus. |
| Syncthing | `~/Syncthing/` (user-configured) | Peer-to-peer, not cloud, but same UX. No third party sees the tarball. Strong choice for privacy. |

Default paths per provider — Linux:

| Provider | Default sync path | Notes |
|----------|-------------------|-------|
| Google Drive (Insync) | `~/Insync/<email>/Google Drive/` | Insync is the most popular paid client. Folder name uses the account email. |
| Google Drive (rclone mount) | `~/gdrive/` (user-configured) | `rclone mount gdrive: ~/gdrive/` — FUSE-based, works headless. Use `--vfs-cache-mode writes` so the tarball is written locally first. |
| Google Drive (google-drive-ocamlfuse) | `~/google-drive/` | Free FUSE client. Same `--vfs`-style caveat: tune `--background-folder` for write reliability. |
| OneDrive (abraunegg/onedrive) | `~/OneDrive/` | The community CLI client. Runs as a systemd user service: `systemctl --user enable onedrive`. |
| OneDrive (Snap) | `~/snap/onedrive-client/current/OneDrive/` | If installed via `snap install onedrive`. Path lives inside the snap confinement dir. |
| OneDrive (Flatpak) | `~/.var/app/io.github.OneDriveGUI/data/OneDrive/` | If installed via Flatpak. Sandboxed location. |
| Dropbox (official) | `~/Dropbox/` | Daemon: `~/.dropbox-dist/dropboxd`. Same path as macOS. |
| Dropbox (Maestral) | `~/Dropbox (Maestral)/` | Lightweight open-source alternative client. |
| Nextcloud | `~/Nextcloud/` | Self-hostable. Configured per account in the desktop client. |
| Syncthing | `~/Sync/` or `~/Syncthing/` | Default folder configured in the Web UI. Excellent on Linux servers (headless). |
| MEGA | `~/MEGA/` | Same as macOS. End-to-end encrypted by default. |
| pCloud | `~/pCloudDrive/` | FUSE-mounted, same caveat as macOS. |
| Box | not officially supported on Linux | Use `rclone mount box: ~/box/` if needed. |
| Proton Drive | `~/ProtonDrive/` (via `rclone protondrive:`) | No native Linux client; rclone is the common workaround. End-to-end encrypted. |

Default paths per provider — Windows (best-effort, primary target is macOS + Linux):

| Provider | Default sync path |
|----------|-------------------|
| OneDrive | `%USERPROFILE%\OneDrive\` |
| Google Drive (Desktop) | `%USERPROFILE%\My Drive\` (Mirror mode) or `G:\My Drive\` (Stream mode, virtual drive) |
| Dropbox | `%USERPROFILE%\Dropbox\` |
| iCloud for Windows | `%USERPROFILE%\iCloudDrive\` |
| WSL access | All of the above via `/mnt/c/Users/<user>/...` from inside WSL |

The CLI just takes the path:

```
shux backup --to "$HOME/Library/Mobile Documents/com~apple~CloudDocs/superharness-backups/"
shux backup --to "$HOME/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/superharness-backups/"
shux backup --to "$HOME/Dropbox/superharness-backups/"
shux backup --to "$HOME/Library/CloudStorage/OneDrive-Personal/superharness-backups/"
shux backup --to "$HOME/MEGA/superharness-backups/"
shux backup --to "$HOME/Syncthing/superharness-backups/"
```

Convenience: `shux backup --to-cloud <provider>` autodetects the path for `icloud`, `gdrive`, `dropbox`, `onedrive`, `box`, `pcloud`, `mega`, `syncthing`. Errors clearly if the provider isn't installed.

```
shux backup --to-cloud icloud
shux backup --to-cloud gdrive
shux backup --to-cloud dropbox
```

Behind the scenes this is just a path lookup — no API integration, no OAuth, no auth tokens to manage. The sync client owns the cloud relationship.

Caveats `shux doctor` should warn about:

| Check | Warning |
|-------|---------|
| iCloud + Optimize Storage on | "Backup tarballs may be evicted from local disk; restores will require re-download. Consider disabling for the backup folder." |
| Google Drive in Stream mode | "Stream mode does not guarantee a written file is uploaded promptly. Switch to Mirror mode or mark the backup folder 'Available offline'." |
| OneDrive Files On-Demand on | Same as iCloud. |
| Last sync time stale | If the cloud client's last-sync timestamp is >24h old (detectable via file mtimes or vendor logs on best-effort basis), warn that backups may not be reaching the cloud. |
| Backup folder size vs free tier | Free iCloud is 5 GB, free Google Drive is 15 GB, free OneDrive is 5 GB. Warn at 80% of free tier. |

Privacy note for cloud-sync backups: the DB itself contains no secrets (those are in the keychain, never in the tarball). Worst-case content leak is task titles, handoff text, and decisions. If even that is sensitive to put on Google/Apple/Microsoft servers, use Tier 4 (encrypted) or stick with Syncthing/MEGA which are private by design.

No vendor SDK, no integration code, no OAuth dance. The tarball lands in the synced folder and the sync client handles the rest. Document this pattern in `shux backup --help`.

**Tier 3 — `shux backup --to <git-remote>` for users who want versioned history**:

A wrapper that initialises a separate `superharness-state-backup` git repo (lives at `~/.local/state/superharness/backup.git`), commits each backup tarball, and pushes to whatever remote the user configures. Suitable remotes:

- A private GitHub / GitLab.com / Bitbucket / Codeberg repo (free, off-LAN)
- A self-hosted Gitea / Forgejo / GitLab on a NAS or VPS
- An owner's LAN GitLab (this is the original LAN-GitLab use case, now just one option among many)

Safe to push to a private remote because the DB contains zero secrets (those are in the keychain). The worst-case leak is task titles and handoff content. If even that is sensitive, encrypt before push (Tier 4).

**Tier 4 — `shux backup --encrypted` for paranoid / regulated users**:

`age` or `gpg`-encrypt the tarball before it leaves the host. Key managed via keychain (same pattern as bot tokens). Then `--to` any of the above targets. Now the destination is fully untrusted: cloud, public mirror, doesn't matter.

```
shux backup --encrypted --to ~/Dropbox/superharness-backups/
```

**Tier 5 — restic / borg / rclone integration for users already using them**:

Don't reinvent. Document the pattern:

```
restic -r b2:bucket/superharness backup ~/.local/state/superharness/
borg create /mnt/borg::sh-{now} ~/.local/state/superharness/
rclone sync ~/.local/state/superharness/ r2:bucket/superharness/
```

Add `shux backup --print-paths` so external backup tools can pick up exactly the right directories without hard-coding them.

**Recommendation by user type**:

| User profile | What to run |
|--------------|-------------|
| Solo dev on macOS, no extra setup | Tier 0 + Tier 1 (Time Machine covers $HOME). Done. |
| Solo dev who already syncs $HOME via Dropbox/iCloud/Syncthing | Tier 0 + Tier 2 with their existing sync folder as `--to`. |
| Multi-machine dev who wants versioned history | Tier 0 + Tier 3 with a private GitHub repo. Free, off-LAN, history. |
| Owner of a LAN GitLab / homelab | Tier 0 + Tier 3 pointing at LAN GitLab. (The original recommendation, now generalised.) |
| Team / regulated / paranoid | Tier 0 + Tier 4 (encrypted) + Tier 3 to any private remote. |
| Power user with existing backup tooling | Tier 0 + Tier 5 (restic/borg/rclone). `shux backup` still useful for one-shot project archives. |

`shux doctor` warns when no backup of any kind has been observed in 7 days. The warning is the actual safety net — backups you forgot to set up don't help.

### 6.3 Debug surface (no more `cat .superharness/state.db`)

Problem: today `sqlite3 .superharness/state.db 'SELECT * FROM tasks'` works from the repo root. After the move, the path is `~/.local/state/superharness/projects/<hash>/state.db`.

Fix: make `shux` itself the debugger. The DB should be first-class in the CLI, not raw.

**Discovery commands**:

```
shux state path                      # absolute path to current project's state.db
shux state path --all                # paths for all projects
shux state open                      # opens state.db in $EDITOR or sqlite3 REPL
shux state shell                     # drops into sqlite3 <path>, readonly by default
```

**Inspection commands**:

```
shux state dump --table tasks --format json | jq
shux state dump --table handoffs --task T-042
shux state schema                    # CREATE statements for all tables
shux state size                      # bytes + row counts per table
shux state vacuum                    # explicit maintenance
shux state export --format yaml > snapshot.yaml
shux state diff <snapshot.yaml>      # compare current to a previous export
```

**Read-only safety**: `shux state shell` opens with `sqlite3 -readonly` by default. `--rw` requires a confirmation prompt. The watcher detects external writes via WAL and refuses to restart until acknowledged — prevents ad-hoc UPDATE from desyncing the dispatcher's view.

**Shell convenience** (for muscle memory):

```bash
# in ~/.zshrc above the sentinel block
alias shdb='sqlite3 -readonly "$(shux state path)"'
```

Now `shdb 'SELECT id,status FROM tasks'` works from any directory inside any superharness project.

**One panic-button command**:

```
$ shux state info
Project:        superharness
Path:           /Users/airm2max/DevOpsSec/superharness
Hash:           a1b2c3d4e5f6
State dir:      /Users/airm2max/.local/state/superharness/projects/a1b2c3d4e5f6/
State db:       /Users/.../state.db  (2.4 MB, 1247 tasks)
Last backup:    2026-05-17 03:00 (380 KB)
Watcher:        running (PID 78234, port 8787)
```

That single command answers "where is my data, is it backed up, is the watcher healthy" — which is 90% of the reason anyone reaches for `cat` on the DB.

---

## 7. Recommended Implementation Order

The notifications feature is the forcing function for the state-isolation refactor that this project needed anyway.

1. **Foundation** — `state_dir()` resolver + `shux migrate-state` + `.superharness/` allowlist gitignore. Touches everywhere the code reads `.superharness/state.db`; do this first so everything else lands on the new layout.
2. **Debug surface** — `shux state {path,open,shell,dump,info}`. Pure additions, no behaviour change.
3. **Worktree** — switch project-hash to worktree path. Add `shux worktree {link,promote}`. Tests for two-worktree isolation.
4. **Backup** — `shux backup` (Tier 0). `shux doctor` warns on stale backup. Document Tiers 1–5.
5. **Notifications** — schema in `~/.config/superharness/notify.db`. Keychain integration. `shux notify` subcommands. Lifecycle hooks emit `shux notify send`. Coalescing + rate limit + scrubbing in the dispatcher.
6. **Pre-commit hook upgrade** — block `*.db` repo-wide with `ALLOW_DB=1` opt-out + DB content scan. This is a global hook change, ship separately.

Each step is independently shippable and testable. Notifications stay last because they depend on the prior layers being in place (keychain, scrubbing, isolated state).

---

## 8. What We Need (Prerequisites + Inventory)

Before writing a TDD plan, here is the concrete list of dependencies, new modules, integration points, and infrastructure required. Anything not on this list is out of scope for v1.

### 8.1 Runtime dependencies (Python)

Already in the project:
- `sqlite3` (stdlib) — used by current state DB
- `pathlib`, `hashlib`, `subprocess` (stdlib) — sufficient for paths, hashing, keychain shell-out

New:
- `keyring` (Python package) — cross-platform wrapper over macOS Keychain, Linux Secret Service, Windows Credential Manager. Pure-Python with backend autodetection. Avoids us writing per-OS shell-out code.
- `httpx` or `urllib.request` for outbound HTTPS — `httpx` preferred (already common, clean timeout API). If we want zero new deps, stdlib `urllib.request` works for Telegram/Slack webhooks.
- `zstandard` (Python package) — for `shux backup` tarball compression. Optional; fall back to gzip if not installed.

Explicitly NOT needed for v1:
- No Telegram SDK (Bot API is a single HTTPS POST per message)
- No Slack SDK (incoming webhooks are a single HTTPS POST)
- No `signal-cli` (Signal channel deferred)
- No `cryptography` library (encryption is Tier 4, deferred; use `age` binary if/when needed)

### 8.2 System dependencies

- macOS: `security` CLI (always present)
- Linux: `secret-tool` (libsecret) — document install (`apt install libsecret-tools`). Fallback path uses chmod 0600 file.
- Optional: `age` or `gpg` binary for Tier 4 encrypted backup. Not required for v1 ship.

### 8.3 New code modules

Roughly the following new files. Names are suggestions, not fixed.

```
superharness/
  paths.py                          # state_dir(), config_dir(), cache_dir(), log_dir()
                                    # + project_hash(cwd) using worktree path
  state/
    migrate.py                      # shux migrate-state: detect, move, link, gitignore
    inspector.py                    # shux state {path,open,shell,dump,schema,size,info,export,diff}
  worktree/
    link.py                         # shux worktree link/promote
  backup/
    snapshot.py                     # shux backup (Tier 0): sqlite .backup + tar.zst
    targets.py                      # --to <dir>, --to <git-remote> dispatchers
    schedule.py                     # integration with existing shux schedule
  notify/
    db.py                           # notify.db schema + migrations
    channels.py                     # shux notify channel {add,list,test,rotate,disable,rm}
    subscriptions.py                # shux notify {subscribe,unsubscribe,status}
    dispatcher.py                   # shux notify send: read keychain, scrub, send, log
    backends/
      telegram.py                   # Bot API POST
      slack.py                      # webhook POST
      email.py                      # SMTP via stdlib smtplib
      # signal.py deferred
    secrets.py                      # keyring wrapper, SecretStr, env scrubbing
    scrub.py                        # regex scrubber for token shapes in payloads
    ratelimit.py                    # coalescing + 30/hour cap
  hooks/
    lifecycle.py                    # emits notify events on task/discussion transitions
  cli/
    notify.py                       # argparse glue for `shux notify ...`
    state.py                        # argparse glue for `shux state ...`
    backup.py                       # argparse glue for `shux backup ...`
```

Existing code touched:
- Every site that reads/writes `.superharness/state.db` — replace with `paths.state_dir() / "state.db"`. This is the biggest blast radius. Use `tilth_deps` to enumerate before starting.
- `shux init`, `shux doctor`, `shux status` — add state-location awareness, backup-staleness warning, migration nag.
- Task lifecycle transitions (wherever status moves through `todo → plan_proposed → ... → done`) — emit lifecycle events for the dispatcher.

### 8.4 Database migrations

Two DBs in play:

**Per-project state.db** (existing):
- No schema change required for the move itself.
- Add `notification_log` table? NO — log lives in the global notify.db so it survives project deletion.

**Global notify.db** (new, at `~/.config/superharness/notify.db`):
- Initial schema = Section 3.1 above.
- Versioned via `PRAGMA user_version`. Migration runner reuses the existing pattern from state.db migrations (whatever the project already uses).

**File moves** (one-shot, by `shux migrate-state`):
- `.superharness/state.db` → `~/.local/state/superharness/projects/<hash>/state.db`
- `.superharness/state.db-wal`, `.db-shm` → same destination
- `.superharness/.gitignore` rewritten to allowlist
- `meta.json` written with `{"path": "<abs>", "name": "<basename>", "created_at": "..."}`

### 8.5 Pre-commit hook changes

In `~/.githooks/pre-commit`:

- Add check `1g` (new): block staging of `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite`, `*.sqlite3` anywhere in any repo. One-shot opt-out: `ALLOW_DB=1`. Per-repo opt-out: `.allow-db` marker file.
- Extend check `1` (sensitive strings): add regex for Telegram bot token (`\d{8,10}:[A-Za-z0-9_-]{35}`), Slack webhook URL (`hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/`), generic SMTP `password=` patterns.
- Document the new checks in `~/.claude/SECURITY_RULES.md` and the project's CLAUDE.md.

Shipped as a separate change from the superharness PR, since it's a global hook.

### 8.6 Configuration surfaces

New files (none committed to any repo):
- `~/.config/superharness/notify.db`
- `~/.config/superharness/defaults.yaml` (optional, only created when user customizes defaults)

New files (committed):
- `.superharness/.gitignore` rewritten to allowlist (replaces existing)
- `.superharness/README.md` — short note: "state lives in ~/.local/state/superharness/, see docs"

Environment variables (new):
- `SUPERHARNESS_STATE_DIR` — override `~/.local/state/superharness/` (for tests, CI, sandboxes)
- `SUPERHARNESS_CONFIG_DIR` — override `~/.config/superharness/`
- `SUPERHARNESS_NOTIFY_DISABLED=1` — kill switch; dispatcher no-ops, returns success
- `SUPERHARNESS_BACKUP_DIR` — default `--to` for `shux backup`

All read via `paths.py`, never scattered.

### 8.7 Test infrastructure

New fixtures:
- `tmp_state_dir` pytest fixture — points `SUPERHARNESS_STATE_DIR` at a tmpdir, yields path.
- `tmp_config_dir` pytest fixture — same for config.
- `fake_keyring` fixture — in-memory keyring backend (the `keyring` package supports this for tests).
- `mock_http` fixture — captures outbound POSTs to Telegram/Slack/SMTP, asserts payload contents.
- `two_worktrees` fixture — creates a repo + worktree, asserts isolated state dirs.

New test files mirroring code modules:
- `tests/paths_test.py`
- `tests/state/migrate_test.py`
- `tests/state/inspector_test.py`
- `tests/worktree/link_test.py`
- `tests/backup/snapshot_test.py`
- `tests/notify/db_test.py`
- `tests/notify/dispatcher_test.py`
- `tests/notify/secrets_test.py`
- `tests/notify/scrub_test.py`
- `tests/notify/ratelimit_test.py`
- `tests/notify/backends/telegram_test.py`
- `tests/notify/backends/slack_test.py`
- `tests/notify/backends/email_test.py`
- `tests/hooks/lifecycle_test.py`
- `tests/cli/notify_test.py`
- `tests/cli/state_test.py`
- `tests/cli/backup_test.py`

Acceptance gates:
- No test may write to the real `~/.config/`, `~/.local/state/`, or real keychain. Fixtures redirect everything.
- One end-to-end test per backend that captures the HTTP request via `mock_http` and asserts the payload exactly.
- One regression test that creates a `.db` file and asserts the pre-commit hook blocks it.

### 8.8 Documentation surfaces

Must update or create:
- `docs/CONCEPT-notifications-and-state-isolation.md` — this file (the spec).
- `docs/notify-security.md` — threat model, key rotation, kill switch (`SUPERHARNESS_NOTIFY_DISABLED`).
- `docs/backup-guide.md` — the 6-tier matrix from Section 6.2, with copy-paste examples per tier.
- `docs/state-locations.md` — XDG layout, env-var overrides, "where is my data" reference.
- `docs/migration-state-relocation.md` — `shux migrate-state` walkthrough, rollback instructions.
- `superharness/CLAUDE.md` — update "Commands" section with `shux notify`, `shux state`, `shux backup`, `shux worktree link/promote`.
- `superharness/AGENTS.md` — same updates.
- `README.md` — one paragraph + link to the new docs.
- `CHANGELOG.md` — per the project's append-per-commit rule, every commit in this work adds a CHANGELOG line.

### 8.9 Integration points (existing systems to wire in)

- **Task lifecycle**: wherever status transitions happen, emit a notify event. Need to enumerate transition sites first (`tilth_search "task.status" kind:callers`).
- **Discussion lifecycle**: same audit needed. May require adding hooks if none exist today.
- **`shux schedule`**: needs to support running `shux backup --all` as a cron entry. Verify the existing scheduler can take arbitrary commands.
- **`shux doctor`**: add checks for state-in-repo, stale backup, keychain reachable, notify channels healthy.
- **`shux status`**: surface unread notification log entries (optional, low priority).
- **Dashboard**: add a "Notifications" panel listing channels + recent sends. Read from notify.db. Deferred to v1.1.
- **MCP server (`shux mcp`)**: expose `notify_send` and `state_info` as MCP tools so other agents can trigger notifications and inspect state without shelling out. Deferred unless requested.

### 8.10 Platform support

Required for v1:
- macOS (primary target — that's where the owner runs)
- Linux (must work — CI, remote VMs, OpenClaw sandbox)

Best-effort:
- Windows / WSL — `keyring` and the XDG paths work, but no one has tested. Document as "should work, file an issue."

### 8.11 Out of scope for v1

Explicitly deferred to keep v1 shippable:
- Signal backend (`signal-cli` dependency too heavy for one channel)
- Encrypted backups (Tier 4) — add when first user asks
- Dashboard notification panel — backend ships first, UI follows
- Multi-user / team mode for shared channels — single-user v1
- Web push / desktop notifications
- MCP `notify_send` tool — agents use `shux notify send` CLI for now
- Restic/borg/rclone-aware backup wrappers — document the pattern, don't wrap

### 8.12 Risk register

| Risk | Mitigation |
|------|------------|
| Migration corrupts existing state.db | `shux migrate-state` does `sqlite3 .backup` first, keeps original until success confirmed, then renames (not deletes) to `.superharness/state.db.pre-migration` |
| `keyring` backend missing on Linux | Detect at install, print install command for `secret-tool`, fall back to chmod 0600 file with warning |
| Agent loop spams notifications | Rate limit (30/hr/channel) + coalescing (3 same-event/60s) + kill switch env var |
| Bot token leaks via stderr / crash dump | `SecretStr` wrapper, scrubbed exception handlers in dispatcher, no token in env beyond the send subprocess |
| Two agents write to state.db simultaneously across worktrees | Worktree-hashed path means they write to different DBs, no contention |
| Backup tarballs accumulate forever | `shux backup --keep <N>` flag, default keep 30, prune oldest. Add to `shux doctor` "backup dir size" check |
| User accidentally `git rm` the state dir | State lives outside repo; `git rm` can't reach it. Belt-and-suspenders. |
| `~/.local/state/` deleted by aggressive disk cleanup tools | Backup tier covers this; `shux doctor` flags missing state dir with restore instructions |

### 8.13 Definition of Done for v1

- `shux migrate-state` moves existing projects without data loss (regression test).
- All existing tests still pass after the `paths.py` refactor (no behavior change for non-notify code).
- `shux notify channel add supah --kind telegram` + subscribe + create a task → message arrives in Telegram. End-to-end manual test documented.
- `shux backup` produces a valid tarball, `shux backup restore` round-trips it byte-for-byte (sqlite content equality).
- `shux state info` runs in <100ms and prints all sections.
- Two worktrees of the same repo do not see each other's tasks (regression test).
- Pre-commit hook blocks `*.db` (regression test).
- Token never appears in: argv, env outside dispatcher subprocess, log files, exception messages, payload_hash table, state.db. Verified by grep on test artifacts.
- `shux doctor` returns 0 with all green checks on a fresh install.

---

## 9. Onboarding Integration (`shux onboard`, `shux explain`)

Note on naming: the existing commands are `shux onboard` (the 7-step setup wizard) and `shux explain` (the 10-second pitch, aliased as `shux why` / `shux wtf`). This section uses those names. No separate `shux demo` or `shux wizard` exists today.

### 9.1 Why surface this in onboarding

The big risk with the new state-isolation + notification + backup story is that **users won't discover any of it**. Today's flow lands them in `.superharness/state.db` and they never think about backups until they lose data. Three first-run decisions need to be elevated:

1. **Where does state live?** (auto, but tell them so they're not surprised by `~/.local/state/superharness/`)
2. **Do they want lifecycle notifications?** (opt-in, with a 30-second path to a working Telegram bot)
3. **What's their backup story?** (force a choice — even "none, I'll handle it" is a choice)

If `shux onboard` doesn't ask these three questions, 95% of users will never set them up, then complain when something breaks.

### 9.2 Proposed `shux onboard` extension

Today: 7 steps (project init, agent roster, etc.). Add three steps at the end, after the existing flow:

**Step 8 — State location confirmation** (informational, ~10 seconds):

```
─ State Location ─────────────────────────────────────────────
Project state will live OUTSIDE this repo, at:
  ~/.local/state/superharness/projects/a1b2c3d4e5f6/state.db

This means:
  ✓ Can't be committed by accident
  ✓ Survives `rm -rf .superharness/`
  ✓ Each git worktree gets its own isolated state

To find it later:    shux state path
To inspect it:       shux state info
To open the DB:      shux state shell

[Press Enter to continue]
```

No prompt, just informed consent. The single-screen explanation is the entire UX surface for "where is my data."

**Step 9 — Backup setup** (choice required, ~60 seconds):

```
─ Backup Setup ───────────────────────────────────────────────
Your task history and decisions are not in git. You need a backup.

Pick one (you can change later with `shux backup --to ...`):

  1) Time Machine / system backup     (macOS detected — covers ~/.local/state/)
  2) iCloud Drive                     (detected at ~/Library/Mobile Documents/...)
  3) Google Drive                     (detected at ~/Library/CloudStorage/GoogleDrive-...)
  4) Dropbox                          (detected at ~/Dropbox/)
  5) OneDrive                         (not detected — install first)
  6) Syncthing                        (not detected — install first)
  7) Private git repo                 (GitHub / GitLab / Gitea / Codeberg)
  8) Custom path                      (any directory)
  9) Skip — I'll set up backup myself

Choice [1]:
```

Detection logic: probe filesystem for the canonical paths from the Tier 2 tables (Section 6.2). Show "detected" for paths that exist, "not detected" for those that don't. Default to option 1 (system backup) on macOS, option 6 (Syncthing) on headless Linux servers, option 9 (skip) otherwise.

If a cloud option is chosen, also offer:

```
Encrypt backups before upload? [y/N]
(Recommended if backup destination is a public cloud you don't fully trust.
 Uses `age` — install with `brew install age` if missing.)
```

After choice, schedule the daily cron:

```
✓ Scheduled daily backup at 03:00 → shux schedule add backup-daily ...
✓ First backup running now in background ...
✓ Backup saved: ~/Backups/superharness/a1b2c3d4e5f6-20260518-143022.tar.zst (412 KB)
```

**Step 10 — Notifications setup** (choice required, ~90 seconds for Telegram):

```
─ Notifications ──────────────────────────────────────────────
Get a message when tasks change state? (e.g., task.created, report_ready)

Pick a channel (or skip):

  1) Telegram                         (recommended — quickest setup)
  2) Slack                            (incoming webhook)
  3) Email                            (SMTP)
  4) Skip — no notifications

Choice [4]:
```

If Telegram chosen:

```
Setting up Telegram:

  Step 1: Open Telegram, search for @BotFather
  Step 2: Send /newbot, give it a name (e.g., "supah")
  Step 3: Copy the bot token BotFather gives you

Paste bot token: ************************************************
  ✓ Token stored in keychain (superharness/supah/bot_token)

  Step 4: Send any message to your new bot from your Telegram account
  Step 5: Press Enter when done — we'll fetch your chat_id automatically

[Press Enter]
  ✓ Found chat_id: 7891234567 (newblacc)

Sending test message...
  ✓ Received in Telegram

Which events do you want?
  [x] task.created
  [x] report_ready
  [x] review_requested
  [ ] task.failed
  [ ] discuss.started

(Space to toggle, Enter to confirm)
```

The auto chat_id fetch uses Telegram's `getUpdates` endpoint right after the user messages the bot — saves them from copy-pasting another ID manually. This is the only place where the onboarding flow gets clever instead of just asking.

### 9.3 Proposed `shux explain` extension

`shux explain` is the 10-second pitch — should stay short. Add one sentence about the new surfaces:

```
superharness — multi-agent task tracking with state outside the repo,
keychain-backed notifications, and host/cloud backup baked in.

Get started:  shux onboard
Find state:   shux state info
Send a test:  shux notify channel test <name>
```

No expansion beyond that — `explain` is the elevator pitch, not the manual.

### 9.4 Proposed new commands for re-onboarding

Users who installed before these features need a way to opt in without redoing the whole `onboard` flow:

```
shux notify setup         # just step 10 of onboard, standalone
shux backup setup         # just step 9 of onboard, standalone
shux state setup          # just step 8 of onboard, standalone (essentially `shux migrate-state` + tour)
```

Each is a thin wrapper around the corresponding onboard step. `shux doctor` recommends them when the corresponding feature is unconfigured:

```
⚠ No backup configured for this project.
  Run: shux backup setup

⚠ No notification channels configured.
  Run: shux notify setup    (optional, takes ~60s for Telegram)
```

### 9.5 Detection helpers (new module)

Put cloud-sync detection in one place — used by `shux onboard`, `shux backup --to-cloud <provider>`, and `shux doctor`:

```
superharness/
  backup/
    detect.py        # detect_cloud_providers() → {provider: path|None}
                     # detect_optimize_storage() → warnings
                     # detect_last_sync() → best-effort staleness
```

Single source of truth for "is iCloud here? is Google Drive in Mirror mode? is OneDrive syncing?" so all three command surfaces give consistent answers.

### 9.6 What NOT to do in onboarding

- Don't auto-create cloud accounts or run OAuth flows. Users bring their own already-installed sync clients.
- Don't auto-install `age`, `secret-tool`, or `signal-cli`. Print the install command, let them decide.
- Don't make notifications mandatory. Skip-with-no-friction is the default.
- Don't ask the user to pick between 6 backup tiers. Auto-recommend based on detected providers, with "Skip" as last resort. The full tier matrix lives in `docs/backup-guide.md` for users who want to read.
- Don't make the wizard >3 minutes total even if every prompt is answered. If it gets longer, split into `shux onboard --quick` (essentials) vs `shux onboard --full`.

### 9.7 Onboarding integration → checklist for the implementation plan

Adds to Section 8.3 (new code modules):

```
superharness/
  commands/
    onboard.py                       # extend existing — add steps 8, 9, 10
  backup/
    detect.py                        # cloud provider detection (new)
    setup.py                         # `shux backup setup` standalone (new)
  notify/
    setup.py                         # `shux notify setup` standalone (new)
                                     # + Telegram chat_id auto-fetch via getUpdates
  state/
    setup.py                         # `shux state setup` standalone (new)
```

Adds to Section 8.7 (test infrastructure):

- `test_onboard_extended_flow.py` — script the new 3 steps, assert correct DB rows.
- `test_detect_cloud_providers.py` — monkeypatch filesystem, assert each provider detected correctly across macOS / Linux / Windows path conventions.
- `test_notify_setup_telegram_chatid_fetch.py` — mock `api.telegram.org/bot<TOKEN>/getUpdates`, assert chat_id parsed correctly.

Adds to Section 8.13 (DoD):

- A new user running `shux onboard` from scratch should have working state, backup, and (optional) notifications within 3 minutes of finishing the wizard. End-to-end manual test.
- `shux doctor` on a fresh project after `shux onboard` returns zero warnings.

---

## 10. Open Questions

- **Multi-user team mode**: today subscriptions are keyed by `user`, defaulted to the local OS user. For a shared team install, who owns the notify.db? Per-user `~/.config/superharness/notify.db` is correct, but team-wide channel definitions (a shared Slack webhook) need a different lifecycle. Defer until requested.
- **Discussion lifecycle events**: are `discuss.started`, `discuss.replied`, `discuss.closed` the right grain? The current discussion subsystem may need event hooks added first.
- **Signal**: keep deferred unless a user asks. `signal-cli` is a heavy dependency for a niche channel.
- **Rate-limit semantics**: should the 30/hour cap be per-channel-per-event or per-channel-total? Per-channel-total is safer.
- **Web push / desktop notifications**: out of scope for v1. Could be a Tier 0 channel later (no token, just OS APIs) but adds platform complexity.

---

## 11. Provenance

Captured from a single design discussion on 2026-05-18. No code written yet. Next step: turn Section 7 into a TDD plan, decompose each step into `shux task create` entries with `tdd.red/green/refactor` blocks, and propose for approval.
