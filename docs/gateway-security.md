# Notification Gateway — Security Audit & Design

**Status:** Phase 1 in code (outbound only). Phase 2 (inbound commands) deferred — see [Open hardening work](#open-hardening-work) before enabling.

**Last audit:** 2026-05-14 against `superharness` `feat/gateway-claw-relay` and `hermes-agent` `main` (Nous Research, MIT).

---

## Why this document exists

The gateway lets an operator interact with a remote AI agent through a chat surface (Telegram, Slack, etc.). Two directions of message flow exist:

- **Outbound** — `superharness → chat`. Pushes notifications about lifecycle events (plan ready, task failed). Risk: text content leaks into a third-party log.
- **Inbound** — `chat → superharness`. Lets a sender post `/approve <task_id>` and similar commands that change task state, which the watcher then dispatches. **An accepted inbound command is equivalent to remote code execution via the agent.**

These two have radically different risk profiles. Treating them as one feature (as `hermes-agent` does, and as the first cut of this gateway started to) produces gaps that are hard to spot in code review because the surface area looks small. This document is the threat model that justifies splitting them.

---

## Threat model

| Attacker capability | Reachable by | Mitigated by |
|---|---|---|
| Read past notification content | Telegram employee, Telegram breach, allowed-sender's compromised client | Only send IDs + statuses, never plan text |
| Pose as the bot (outbound) | Bot-token leak | Token at `~/.config/.../credentials.env` mode 0600; no project-level copy |
| Issue commands as an allowed sender | Telegram account takeover (SIM swap, session hijack, social), allowed sender's device compromise | Phase 2 controls — see below |
| Replay an old `/approve` | Captured Telegram message, replayed via separate bot session | `message_id` dedup in DB; freshness window |
| Spoof intent via forward | Authorized sender forwards a privileged command, attacker forwards it again from a non-authorized account | Reject `forward_origin` |
| Group-chat exposure | Bot added to a group the operator does not control | DM-only by default |
| DoS the watcher with command floods | Anyone with the bot username (in groups) | Per-sender rate limit |

---

## Comparison: superharness vs hermes-agent

`hermes-agent` is the most direct open-source comparison — same problem (operator commands a remote agent via Telegram/Discord/Slack/WhatsApp/Signal), MIT licensed, currently shipping.

| # | Control | superharness | hermes-agent | Industry baseline |
|---|---|---|---|---|
| 1 | Token storage | `.superharness/watcher-env.yaml` 0600 (project-level) | `~/.hermes/.env` 0600 (machine-level) | Machine-level 0600 or OS keychain |
| 2 | Sender allowlist | CSV, str-compare | CSV env var, str-compare | OK on both |
| 3 | Auth-before-write | yes | yes | required |
| 4 | Replay / dedup | `message_id` in DB | none (`drop_pending_updates=False`) | `message_id` dedup |
| 5 | Edited messages | processed (low risk — dedup blocks re-execute) | ignored | dedup or ignore |
| 6 | Forward-origin check | **missing** | **missing** | required |
| 7 | Reply-to attribution | safe (`from.id` only) | safe | use `from.id` only |
| 8 | Group-chat hardening | none | silent-drop unknown senders | DM-only by default |
| 9 | Per-sender rate limit | **missing** | **missing** | 5-10/min |
| 10 | Second-factor confirm for destructive ops | **missing** | **missing** | inline-button or one-time code |
| 11 | Freshness window on `/approve` | **missing** | 5-min TTL | 5-30 min |
| 12 | Structured audit log | DB row per command | logger.info only | DB row keyed by `(sender_id, message_id)` |
| 13 | Plaintext over the wire | only IDs + statuses | full LLM output, 3500 chars/reply | only IDs |
| 14 | Webhook vs polling | polling | polling | polling (no public TLS surface) |

**Score:** superharness is slightly better than hermes on dedup (4), audit (12), and plaintext leakage (13). Both share the five high-risk gaps: **6, 9, 10, 11**, plus project-level token storage (1).

---

## Three insights worth keeping

### 1. Inbound and outbound have radically different risk profiles

Outbound = "post a string to a chat" — leaks notification text, that's it. Inbound = "anyone posting a string can change task state, which executes arbitrary code via the agent." Treating them as one feature is what produces hermes-style gaps. They must be wired independently.

### 2. `/approve` is remote code execution

The plan content was authored by the agent — the operator only authorizes it. If a Telegram account is taken over, the attacker doesn't need to inject code; they just type `/approve t-abc` against whatever plan is pending. This is a known industry pattern (Atlantis Terraform-via-PR-comment has the same shape) and the standard mitigation is a freshness window plus a second factor. Without those, the inbound path turns Telegram into a single-factor RCE vector keyed to the operator's phone.

### 3. The relay is the right place to put security policy, not the client

`hermes-agent` embeds rate-limiting, confirm flows, and pairing in every client (Telegram, Discord, Slack, WhatsApp, Signal). A relay (claw-relay or any HTTP relay matching the same API shape) is the natural chokepoint — put rate-limit, dedup, sender allowlist there once, and every consumer (superharness, nocture, future tools) inherits it. The Mac just reads structured records out of the relay inbox.

---

## Recommendation

Ship in two phases. Split outbound from inbound. Defer inbound until hardened.

### Phase 1 — shipped (low risk, high value)

- Outbound notifications only.
- Two backends, user picks at onboard time:
  - **Relay (SSH or HTTP)** — generic, relay enforces policy
  - **Telegram bot (direct)** — bot token in `~/.config/superharness/credentials.env`, mode 0600 (machine-level)
- No secrets in any project's `.superharness/` directory.
- `notify.py` prefers relay if configured, falls back to direct bot, then webhook, then desktop.
- Onboarding text: "Inbound commands are not enabled. Approvals happen via the dashboard."

### Phase 2 — feature-flagged, separate PR (see [Open hardening work](#open-hardening-work))

Inbound `GatewayListener` enabled only when the five controls land:

- Forward-origin reject (drop any message with `forward_origin` / `forward_from` set)
- Per-sender rate limit (5 destructive/min, 20 read-only/min)
- Freshness window — `/approve t-X` valid only if the task entered `plan_proposed` within the last 30 min
- Inline-button confirm — bot replies with a `callback_query` inline keyboard; operator taps "Confirm approve t-X". Cannot be forwarded.
- DM-only by default — refuse to operate in groups unless `--allow-group <chat_id>` is set

### Phase 3 — operator UX and multi-channel (builds on Phase 2)

Four tracks, in recommended build order:

#### B: Multi-channel routing (independent — no Phase 2 required)

Add ntfy.sh (self-hosted) and Slack webhooks as direct backends alongside Telegram.
`dispatch_notification` tries backends in priority order; operator configures which are active at onboard time.
ntfy.sh self-hosted is the recommended relay-free fallback — no third party sees notification content.

#### C: Pairing-code flow

One-time 8-char codes (32-char unambiguous alphabet, `secrets.choice`) for adding a new operator device.
1h TTL, 3 pending max, 5 failures → 1h lockout, credentials chmod 0600.
Replaces the current static chat-ID approach for first-contact operator onboarding.
Reference: `hermes-agent/gateway/pairing.py`.

#### A: Inline-button approvals

Plan-proposed notification includes `[Approve] [Reject]` Telegram `callback_query` inline buttons.
Operator acts from phone with one tap — no need to type `/approve t-X`.
Requires Phase 2 inbound path and the inline-button confirm hardening control.

#### D: Smart digest

Low-priority events (`plan_approved`, `task_closed`) batched into a configurable digest interval.
High-priority events (`task_failed`, `plan_proposed`) always break through immediately.
Reduces notification noise without losing signal.

---

## What to copy from hermes-agent

- **Pairing-code flow** (`gateway/pairing.py`) — one-time 8-char codes from a 32-char unambiguous alphabet via `secrets.choice`, 1h TTL, 3 pending max, 5 failures → 1h lockout, files chmod 0600. Strong design for first-contact when adding a new operator.
- **File-mode discipline** — credentials file 0600, parent dir 0700.
- **Polling-only for Telegram** — never expose a webhook endpoint.
- **Approval TTL** — 5-min default on pending approvals.

## What not to copy from hermes-agent

- `GATEWAY_ALLOW_ALL_USERS=true` / `HERMES_YOLO_MODE=1` escape hatches. They get set in `.env` files and forgotten.
- Full LLM output streamed over the chat channel. Keep superharness sending IDs + statuses only.
- Polling without `update_id` / `message_id` dedup. `drop_pending_updates=False` plus no dedup means buffered updates re-execute across restarts.

---

## Open hardening work

Tracked as deferred. Do not enable inbound `GatewayListener` until each item lands with regression tests:

1. **forward-origin reject** — `tests/unit/test_telegram_gateway.py::test_forwarded_message_rejected`
2. **per-sender rate limit** — `tests/unit/test_telegram_gateway.py::test_rate_limit_per_sender`
3. **freshness window** — `tests/unit/test_telegram_gateway.py::test_approve_rejected_when_stale`
4. **inline-button confirm** — `tests/unit/test_telegram_gateway.py::test_destructive_op_requires_callback_query`
5. **DM-only default** — `tests/unit/test_telegram_gateway.py::test_group_chat_rejected_when_not_allowlisted`

When all five land, document the activation flag (e.g. `gateway.inbound.enabled: true` in `profile.yaml`) and the operator runbook for incident response (revoke bot token, rotate relay bearer token, clear allowed_senders).

---

## References

- `~/DevOpsSec/hermes-agent/` (Nous Research, MIT)
- `gateway/run.py:1247-4112` — auth, approval, rate-limit posture in hermes
- `gateway/pairing.py` — pairing-code design worth borrowing
- `src/superharness/modules/gateway/telegram_gateway.py` — current `GatewayListener` (inbound, not enabled in Phase 1)
- `src/superharness/engine/relay_client.py` — relay-based outbound (Phase 1)
- Atlantis Terraform PR-comment apply model — similar `/apply <id>` semantics, similar threat shape
