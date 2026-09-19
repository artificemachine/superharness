# BUG 2026-09-18 — the auto-review tier gate is not enforced, and the function written to enforce it cannot be imported

**Severity:** medium — nothing crashes on the live path and no data is lost, but an
invariant the code states in a comment silently does not hold, reviewers are picked
arbitrarily, and a latent `ImportError` waits for the first caller.
**Status:** open. Measured 2026-09-18 on macOS at revision `408936c8`.

## How this was found

Incidentally. Editing `engine/state_reader.py` for
`BUG-2026-09-18-state-db-skeleton-leak.md` caused type-checking to re-examine
`commands/inbox_watch.py`, which imports that module. The reporting was a
one-line import complaint; the investigation below is what it turned into. None
of this was introduced by that change.

## Summary

`inbox_watch`'s auto-review path states, in a comment, that *"Reviewer must use a
higher or equal model tier than the author."* Three distinct defects sit behind
that statement.

### 1. The code that would enforce the gate is dead and cannot be imported

`src/superharness/commands/inbox_watch.py:985` defines `_select_reviewers`, whose
whole purpose is the cross-pollination guard plus the model-tier gate:

```python
def _select_reviewers(task: dict, candidates: list[str], profile: dict) -> list[str]:
    """Filter candidate reviewers based on cross-pollination and model-tier gates."""
    from superharness.engine.model_budget import (
        reviewer_meets_tier,
        AGENT_DEFAULT_TIERS,
    )
```

Neither symbol exists in `engine/model_budget.py`, and neither ever has: the
module's public surface is `check_budget`, `check_agent_budget`, `_WARN_THRESHOLD`,
`_load_budget_config`, `_today_spend` and `_today_spend_by_agent`. Checked at the
commit that introduced the import, `61353ba4` ("feat(hermes): Phases 2-4",
2026-04-28) — the same commit that added these 22 lines to `inbox_watch.py`. The
import was written against an API that was never implemented.

Reproduced verbatim:

```
$ uv run python -c "from superharness.commands.inbox_watch import _select_reviewers; _select_reviewers({'owner':'x'}, ['a'], {})"
ImportError: cannot import name 'reviewer_meets_tier' from 'superharness.engine.model_budget' (~/DevOpsSec/superharness/src/superharness/engine/model_budget.py)
```

The message is reproduced exactly except for the maintainer home path, which is
abbreviated to `~` in the interpreter's output as
`tests/contract/test_no_infra_topology_leaks.py` requires of tracked files (the
same abstraction `HANDOFF.md` uses). The exception type, symbol name and source
module are verbatim.

`_select_reviewers` has no caller anywhere in `src/`, `tests/` or `docs/`, so the
failure is latent rather than live. `_trigger_auto_review`, defined immediately
after it at `inbox_watch.py:1007`, *is* live — it is called at
`inbox_watch.py:1371`.

### 2. The live path does not enforce the tier gate it claims

`_auto_close_report_ready` implements the reviewer decision inline instead, at
`inbox_watch.py:1364`:

```python
# Reasoning: Reviewer must use a higher or equal model tier than the author
author_tier = str(task.get("model_tier") or "standard")
if author_tier == "mini":
    task["model_tier"] = (
        "standard"  # Upgrade to at least standard for review
    )

if _trigger_auto_review(project_dir, task_id, peer_reviewers):
```

The comment announces a constraint between two agents. The code compares nothing
between them: it rewrites the **author's** `model_tier` from `mini` to
`standard`. The reviewer's own tier is never read, so a `mini` reviewer can be
dispatched against a `max` author and the invariant is quietly false. The tier
order that this would need already exists and is unused here:
`engine/model_fallback.py:42` defines `_TIER_ORDER = ["max", "standard", "mini"]`.

### 3. The live candidate list has drifted from the canonical registry

`inbox_watch.py:1353` hardcodes the harness list:

```python
known_agents = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
```

The canonical, registry-derived list is `superharness.harnesses.KNOWN_HARNESSES`,
which is `['claude-code', 'codex-cli', 'gemini-cli', 'opencode', 'pi']`. `pi` is
missing. A project whose only available peer is `pi` therefore gets no
auto-reviewer, and `pi` can never be selected as a peer.

The same file shows this done correctly 1,955 lines later:
`_cancel_undispatchable_agents` (`inbox_watch.py:5308`) documents that it "Uses
the adapter registry as the canonical source of valid agent names" and calls
`adapter_registry.list_adapters()`. The auto-review path should not be the one
place that hardcodes it.

Selection is also arbitrary: `inbox_watch.py:1357` takes `peer_reviewers =
[peers[0]]`, the first peer in list order, rather than any filtered ranking.

Taken together, defects 1 and 2 mean the reviewer-selection logic that was
designed — guard plus tier gate, returning a filtered list — is not what runs.
Wiring `_select_reviewers` in would not be a pure repair either: it changes which
agents get picked.

## What must be decided before this is fixed

Each of these is a policy question, not an implementation detail, so a fix must
not invent an answer:

1. **Which directory holds the reviewee's tier?** `_select_reviewers` expects
   `AGENT_DEFAULT_TIERS` mapping an owner to a default tier, with `"standard"` as
   the fallback. Nothing defines that mapping, and profile-driven tiers
   (`engine/behavioral.py`, `.superharness/profile.yaml`) are a separate source.
2. **Should the author's `model_tier` be mutated at all?** The live path upgrades
   `mini` to `standard` and persists it. That is a write to the author's record
   during what is otherwise a review action. Whether that is intended, or a
   substitute for a gate that was never wired, needs its owner.
3. **When no peer satisfies the tier gate, is auto-review skipped, or is the
   lowest qualifying tier upgraded?** `_select_reviewers` returns an empty list;
   the live path always picks one peer. These differ in behaviour.
4. **Should `pi` be a peer-review candidate?** It is a registered harness today.

## Impact

- A review dispatched to a lower-tier reviewer than the author, while the code
  claims the opposite — the kind of silent divergence a reviewer of this file
  cannot see without reading `model_budget.py`.
- `pi`-only or `pi`-majority projects cannot use autonomous peer review.
- The next person to call `_select_reviewers` — plausibly while "fixing" defect 2
  — gets an `ImportError`, not a wrong answer, which is at least loud.

## Verification performed

- `grep -rn 'reviewer_meets_tier\|AGENT_DEFAULT_TIERS' src/ tests/ docs/` — only
  `inbox_watch.py:988,989,996,1002`; nowhere else, including tests.
- `git show 61353ba4:src/superharness/engine/model_budget.py | grep -n 'meets_tier\|DEFAULT_TIERS'`
  — empty, so the module never defined them.
- `grep -rn '_select_reviewers\|_trigger_auto_review'` over the whole tree — the
  first has no caller, the second is called at `inbox_watch.py:1371`.
- The `ImportError` above, reproduced.
- `uv run python -c "from superharness.harnesses import KNOWN_HARNESSES; print(KNOWN_HARNESSES)"`
  compared against the hardcoded list: exactly one difference, `pi`.

## Not claimed

No behaviour change is asserted for a fixed version, and no fix is proposed here
beyond the policy questions above. The `mini` → `standard` mutation may be
deliberate operator policy; what is demonstrable is that it is not the gate its
comment describes.
## Progress 2026-09-18 — defect 3 fixed; the reviewer pool now follows the registry

`_auto_close_report_ready` no longer builds its candidate list by hand. The list
comes from `harnesses.KNOWN_HARNESSES` through a new `_peer_reviewer_candidates()`
helper — the same canonical source this file already documents using at
`_cancel_undispatchable_agents`, which is what made the drift here a defect rather
than a design choice.

**Why this was safe to fix without the owner's policy call.** Policy question 4
above asked whether `pi` should be a reviewer candidate; the registry already
answers it, because `pi` is registered. The change is also behaviour-preserving
for every case that worked: `KNOWN_HARNESSES` is sorted and `pi` sorts last, so
the first candidate — which is the one the live path picks — is identical for all
four owners that previously produced a reviewer. The only behaviour that changes is
the broken one: a `pi`-owned task went from *no reviewer at all* to a reviewer.

**The path had no test coverage whatsoever.** `grep -rln
'auto_review\|peer_reviewers\|_auto_close_report_ready\|_trigger_auto_review'
tests/` returned nothing before this change; the existing
`tests/integration/test_review_autonomous.py` covers `_auto_close_review_passed`,
a different function. `tests/unit/test_peer_reviewer_candidates.py` now adds seven
cases, including a wiring guard that inspects `_auto_close_report_ready`'s source
and fails if it rebuilds a harness list inline again. That guard matters more than
the helper's own tests: the drift survived because no test could observe a caller
choosing not to use the correct API.

**Still open, unchanged by this fix.** Defect 1 (the `_select_reviewers`
`ImportError` in dead code) and defect 2 (the live path's tier gate not being
enforced) both stand, along with policy questions 1-3: which directory holds
reviewer tiers, whether mutating the author's `model_tier` from `mini` to
`standard` is intended policy, and whether an empty qualifying set should skip
auto-review. `peers[0]` remains an arbitrary pick; this change makes the pool
correct, not the selection.

Verified: the new tests were RED first (`ImportError: cannot import name
'_peer_reviewer_candidates'`); `tests/unit/` + `tests/contract/` +
`tests/integration/test_review_autonomous.py` 4477 passed / 15 skipped / 2 xfailed;
ruff on `inbox_watch.py` reports 133 findings at HEAD and 133 after, so this
change added none.
