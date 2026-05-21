# Release TODO — v1.62.15

**Date:** 2026-05-21 | **18 releases today (v1.62.7 → v1.62.15)**

## ✅ Done (auto-completed by CI)

- [x] All code committed and pushed to main
- [x] All tags pushed (v1.62.7 through v1.62.15)
- [x] GitHub releases auto-created by CI
- [x] CHANGELOG.md updated (18 entries)
- [x] 72+ new behavioral tests passing
- [x] 103 CLI tests passing (3 broken files fixed)

## 🟡 Pending

### Announcement (should do)
- [ ] Announce inbox.py hotfix — `ai_driven` projects were silently failing to dispatch (ImportError + undefined logger). Fixed in v1.62.8. Affected users need to upgrade.
- [ ] Announce behavioral profile feature — `shux profile show`, zero-touch adaptation, dashboard card

### Docs (nice to have)
- [ ] Add `shux profile` to GUIDE.md command reference
- [ ] Add `shux memory-roots` to GUIDE.md
- [ ] Add behavioral profile section to README.md features list
- [ ] Add Hermes self-improvement section to README.md

### Verification (should do)
- [ ] Full test suite (2,500+ tests) — run end-to-end
- [ ] `shux discuss start` — verify inbox.py hotfix works (was crashing)
- [ ] Dashboard profile card — verify renders at `http://127.0.0.1:8787`

### Cleanup (nice to have)
- [ ] Delete `fix/senior-review-criticals-2026-05-20` branch (already merged to main)
- [ ] Clean up `docs/archive/` — 22 archived files, some may be deletable
- [ ] Remove duplicate global memory entries from `~/.config/superharness/memory/` (pre-dedup pollution)

## Summary of what shipped

| Feature | Version | Impact |
|---------|---------|--------|
| Senior review fixes (C1-C6) | v1.62.7 | 392→0 bare except, 3 monoliths decomposed |
| Hotfix: inbox.py enqueue crash | v1.62.8 | ai_driven projects work again |
| CLI passthrough fix | v1.62.9 | profile + memory-roots commands work |
| Hermes I1-I3 (memory + guardrails + promotion) | v1.62.7 | 33 tests, watcher log analyzer |
| Behavioral profile I4 (extraction + CLI) | v1.62.8 | 24 tests, shux profile show |
| Behavioral I5 (hardening) | v1.62.10 | Dedup, watcher refresh, auto-rules, auto-reviews |
| Behavioral I6 (verification loop) | v1.62.11 | A/B test every profile change |
| Behavioral I7 (dashboard card) | v1.62.12 | /api/profile endpoint + UI card |
| Docs cleanup | v1.62.7 | 19 archived, docs/README.md index |
| Test fixes (dashboard imports) | v1.62.14 | 103 pass, 3 files fixed |
| Onboarding bootstrap + watcher wiring | v1.62.15 | Zero-touch profile + memory auto-promotion |
