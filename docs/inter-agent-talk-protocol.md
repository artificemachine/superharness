# Inter-agent communication — the channel split (`shux discuss` / `shux talk` / mailbox files)

Three channels, three jobs. Field-proven on a multi-host lab (shared NFS
mount, agents on different hosts and OS users) before being folded into
superharness.

| Channel | Job | Medium |
|---|---|---|
| **`shux discuss`** | Transient, fast, emergency actions; superharness's own agent deliberations (verdict rounds, quorum consensus, approval gates) | Discussions engine (SQLite), discussion-id addressed, auto-closes on consensus |
| **`shux talk`** | Ongoing inter-agent conversation and deliverable coordination — versionable, session-name addressed, threads persist until deliberately concluded | Discussions engine (SQLite) + file registry (sessions/threads pointers are plain files, so the conversation surface is versionable) |
| **Mailbox files** | Durable records: handoffs, delivery receipts, protocol declarations, owner decisions | Append-only Markdown, one file per scope |

Rules of thumb:

- A decision that needs a verdict *now* (approve/block, quorum on an action)
  is a **`discuss`** — it converges and closes.
- Working conversation around a deliverable — negotiating an interface,
  iterating on a handoff, coordinating across sessions or hosts — is a
  **`talk`** thread: it stays open, survives across sessions, and its
  registry files can be committed alongside the project.
- Anything that must survive as an audit record — or that a human ratifies —
  goes in a **mailbox** file.

## Channel 1 — `shux discuss` (existing engine, for contrast)

The native deliberation primitive. Discussion-id addressed, round-based,
verdict-driven (`agree`/`disagree`/`partial`/`abstain`), quorum consensus
auto-closes the discussion and can gate follow-up actions. Right for
transient decisions and emergency coordination: the whole point is to
converge and terminate. Wrong for conversation — auto-consensus closes a
thread under participants who merely agree with each other.

## Channel 2 — `shux talk`

Session-name-addressed conversation threads built on the discussions engine.
No discussion-id exchange between agents; names resolve through a small
file registry.

```bash
shux talk register <my-session-name> <agent-kind>   # once per session
shux talk <peer> -m "message"                       # send (first contact auto-creates the thread)
shux talk <peer>                                    # read the thread
shux talk inbox                                     # threads where the peer spoke last
```

- **Agent kinds** are the adapter names (`claude-code`, `codex-cli`, ...), but
  thread participants are the *session names*, so two sessions of the same
  kind converse without identity collisions.
- **Threads never self-close**: every message is submitted with
  `verdict=partial` and `max_rounds=99`, so the engine's auto-consensus
  (all participants agree/abstain) cannot fire under a live conversation.
  Submitting `agree` from both sides is the deliberate way to conclude one.
- **Rotation**: sending into a thread that is no longer `active`
  (closed/cancelled out-of-band) transparently starts a fresh thread; the
  superseded discussion id is appended to the pair's `.history` file.

### Registry layout

Under the talk dir (`$SUPERHARNESS_TALK_DIR`, else `<project>/.superharness/talk`):

```
sessions/<name>.json     name → {agent kind, host, project, registered at}
threads/<a>~<b>.id       sorted-pair pointer → current discussion id
threads/<a>~<b>.history  rotated discussion ids (append-only)
```

### Identity

Each session's identity lives in a small local file:
`$SUPERHARNESS_TALK_SELF` if set, else
`~/.config/superharness/talk-self-<instance>` with `<instance>` from
`$SUPERHARNESS_TALK_INSTANCE` (or `$HERDR_PANE_ID`, or `shared`).

**Co-located agents (same OS user, same box) must not share one identity
file** — whoever registers last wins the identity. Give each pane/process an
instance id.

### Cross-host operation

The registry and the discussions database must be the *same files* on every
participating host:

1. Put the project (or at least its state) on a mount every host sees.
2. Point `SUPERHARNESS_TALK_DIR` at a shared directory.
3. Ensure every host resolves the same state database — a shared project
   checkout using the legacy `.superharness/state.sqlite3` path, or
   `SUPERHARNESS_STATE_DIR` pointed at a shared state root. Per-host XDG
   state paths are mutually invisible; threads created there never cross
   hosts.
4. Keep traffic light: SQLite over network filesystems tolerates chat-scale
   writes, not log-scale ones. (State DBs already use a network-safe journal
   mode on NFS/CIFS.)

## Channel 3 — the append-only mailbox

For records that must persist and be auditable. Plain Markdown files, no
tooling required.

| Scope | Path | Use |
|---|---|---|
| Per-project | `<project>/coordination/MAILBOX.md` | both agents work the same project — the default |
| General | a shared `coordination/GENERAL.md` outside any project | no shared project |
| Named cross-project | `coordination/<topic>.md` beside GENERAL.md | a durable pair/topic spanning projects — announce it in GENERAL.md |

Pick the narrowest scope that fits. Project mailboxes travel with the
project's git history when committed.

### Format

Append-only. One block per message, newest last:

```
## [<UTC ISO-8601>] <session-name>

<message>
```

### Rules

1. **Append-only.** Never edit or delete an earlier block. Corrections are
   new blocks.
2. **Verify your append** — `tail` the file after writing; if your block is
   not there, the write FAILED. Say so; never report success.
   ```bash
   printf '\n## [%s] <session-name>\n\n%s\n' "$(date -u +%FT%TZ)" "MESSAGE" >> <mailbox>
   tail -5 <mailbox>
   ```
3. **Poll at task boundaries** and whenever the operator says there's mail.
   Read the whole tail since your last block, not just the last block.
4. **First block of a new mailbox** states the participants, their
   hosts/repos, and why the mailbox exists.
5. **Contract material** (specs, state machines, items to ratify) goes in a
   real doc under the project's `design/`; the mailbox block carries the
   pointer plus the delta, not the full spec.
6. **The human stays in the loop**: decisions ratified by the owner are
   recorded in the design doc, not just the mailbox.
7. **Unacked = undelivered** for anything that matters — a handoff without a
   receipt block from the recipient has not happened.
