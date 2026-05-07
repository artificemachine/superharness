---
id: changelog-policy
title: CHANGELOG.md is append-only
status: active
since: v1.0
---

CHANGELOG.md is append-only — enforced by `.githooks/pre-commit`.

Never edit, reorder, or delete existing lines. Add new entries at EOF only.
Corrections append a new correction entry (never rewrite history).

Pre-commit runs `check-changelog-append-only.sh --staged`.
