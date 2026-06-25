# ANALYSIS — How the SQLite Doctrine Drifted (and How to Make It Un-driftable)

**Date:** 2026-05-22
**Context:** During the SQLite source-of-truth audit (`PLAN-sqlite-source-of-truth-refactor.md`) we found `engine/sqlite_only.py` asserting *"the migration is complete; YAML is no longer read or written operationally"* — while ~19 code sites still read YAML state. This documents **why** that contradiction could exist and **how to prevent the entire class of drift.**

---

## Part 1 — How the drift happened (post-mortem)

The claim and the reality coexisted because the claim was **prose, not an enforced invariant.** Five compounding mechanisms:

### 1. The flag gates writes, not reads
`is_sqlite_only()` is checked on the **write** side only — e.g. `state_writer._export_contract_yaml` short-circuits so it stops dual-writing YAML. There is **no read-side gate.** Nothing says "in sqlite_only mode, refuse to read YAML state." Old reader code was never forced to comply; it just kept working.

### 2. "Complete" was declared per-entity, then over-generalized
Tasks and inbox were fully migrated (writers **and** readers → SQLite). Those are the heavy entities, so once done it *felt* complete, and the blanket docstring was written covering **all** state. The tail — handoffs, ledger, discussion readers — was never finished. The claim generalized from "the important entities are done" to "everything is done."

### 3. For handoffs, even the write side was never migrated
The sharpest fact: handoff writers still emit **YAML-only** (`upsert_handoff`, `handoff_write.py`, MCP `write_handoff` — none call `handoffs_dao.append`). For handoffs, "YAML is no longer written operationally" is simply false. The YAML *is* the store.

### 4. The contradiction is invisible because it produces correct output
This is why it was never caught. The YAML files are still written (labeled "exports"), so when recall/context/dashboard glob them they get real data and return correct results. Nothing crashes, nothing returns empty.
- For tasks/inbox: the YAML is a redundant export, readers use the DB → harmless.
- For handoffs: the "export" is the **only** copy → reading it is **accidentally correct.**

A bug that returns the right answer never gets reported.

### 5. No test or lint enforces the doctrine
No guard fails when code globs `.superharness/handoffs/*.yaml`. So the drift was free to persist indefinitely.

### One-line root cause
> The docstring asserts an *outcome*; the code only half-implemented it (write-side, some entities); and because YAML kept being written, the unmigrated readers silently kept working — so the lie never surfaced as a failure.

This is the canonical way "we finished the migration" becomes false without anyone noticing.

---

## Part 2 — Bulletproof prevention (defense in depth)

### The principle
An architectural invariant survives only if it is **mechanical, loud, and checked** — never if it depends on documentation, memory, or discipline. Three failure modes to design against:
1. **Bypassable** — the wrong action is reachable (you can glob the path).
2. **Silent** — the wrong action still "works" (reading the export returns data).
3. **Unchecked** — nothing fails when someone does it.

Kill all three. Each layer below targets one failure mode; together they make the drift class structurally impossible, not just discouraged.

### Layer 1 — Encapsulation chokepoint (kills *bypassable*)
Make the invalid action **unreachable**, not just forbidden.
- All state access goes through one facade (`state_reader` / the DAOs). That facade is the *only* module that knows the on-disk paths or opens the DB.
- Callers in `commands/`, `mcp/`, `scripts/` receive a `StateStore` handle; they are never handed a `project_dir` they can use to construct `.superharness/handoffs/`.
- Concretely: the path constants for state dirs live in the export module + DAOs only; readers can't import them. **You can't glob a path you can't name.**

### Layer 2 — Remove the invisible-success crutch (kills *silent*)
The bug hid because reading the export "accidentally worked." Take that away so a wrong path **fails loud**.
- In sqlite_only mode, operational YAML state files **do not exist at rest.** `shux export-yaml` writes snapshots into a separate `exports/` dir (or generates then cleans). The live `.superharness/handoffs/` etc. either don't exist or hold only DB-backed data.
- Result: a stale reader that globs the old path gets **empty / FileNotFound**, breaks in dev and tests immediately, and the divergence surfaces as a failure instead of limping along returning correct data.
- Design rule to adopt project-wide: **"If the wrong path is taken, it must break — never limp."**

### Layer 3 — CI fitness function (kills *unchecked*)
An executable architecture test that fails the build on violation. Two checks:
- **Forbidden-path grep:** scan `commands/ engine/ mcp/ scripts/` for state-file access patterns (`.superharness/handoffs`, `.superharness/discussions`, `ledger.md`, `contract.yaml`, `inbox.yaml`, `glob("*.yaml")` under a state dir). Fail if found outside an explicit allowlist (export writer + config readers + the discussion ingest bridge).
- **Forbidden-import / dependency-direction test:** assert that only `engine/*_dao.py` and the export module import `sqlite3` or touch state paths. `commands/`, `mcp/`, `scripts/` may depend only on `state_reader`. This catches the layering violation that allowed direct reads in the first place.

This is the same defense-in-depth pattern as the existing `~/.githooks/pre-commit` and ship-gate hooks — an enforcement layer, not a hope.

### Layer 4 — Executable doctrine / migration manifest (kills *over-generalized "complete"*)
The false "complete" claim came from a human asserting a per-entity status without tracking it. Make completeness a **computed fact**.
- A manifest enumerates each state entity with three booleans: `writer_uses_db`, `reader_uses_db`, `no_yaml_reader`.
- A test iterates the manifest and asserts each is true (or explicitly waived with a reason). "Migration complete" is then **derived from passing tests**, not written in a docstring.
- Adding a new state entity without wiring it fails the manifest test.

### Layer 5 — Doctrine points to its enforcement
The `sqlite_only.py` docstring (and `CLAUDE.md`) must **reference the guard test by name** rather than restating the claim in prose. The claim and its proof live together; you can't read the doctrine without seeing what enforces it. Prose claims with no link to enforcement are how this started.

---

## Part 3 — How each layer would have caught *this* bug

| Layer | Would it have caught the handoff drift? |
|---|---|
| L1 Chokepoint | Yes — recall/context/dashboard couldn't construct the `handoffs/` glob path |
| L2 Fail-loud | Yes — with no operational YAML at rest, recall would return empty and tests would scream |
| L3 Fitness function | Yes — the forbidden-path grep flags every one of the 19 sites today |
| L4 Manifest | Yes — `handoffs.writer_uses_db = false` fails the completeness test; "complete" claim becomes impossible to make falsely |
| L5 Doctrine link | Indirect — forces the claim to be backed by L3/L4 |

Any **one** of L1–L4 alone would have surfaced the drift. Layered, they make it structurally impossible.

---

## Part 4 — Pragmatic adoption (given limited bandwidth)

You do not need all five at once. Ranked by leverage-per-effort:

1. **L3 (CI fitness function) — do this first.** Cheapest, catches all current + future violations immediately, no refactor required. It's a single test file. This alone converts the doctrine from prose to enforced.
2. **L4 (migration manifest) — cheap and high-value.** A small table + a loop test. Makes "complete" honest and gates future entities.
3. **L2 (fail-loud / move exports to a separate dir) — medium effort, high payoff.** Removes the crutch that hid the bug. Pairs naturally with the Phase 1–2 refactor.
4. **L1 (chokepoint encapsulation) — highest effort.** Worth it long-term but it *is* the refactor; treat it as the end-state, not a prerequisite.
5. **L5 (doctrine link) — trivial, do it alongside L3.**

**Minimum bulletproof set: L3 + L4 + L5.** Three small test/doc additions that would have made today's drift impossible to merge, with zero large refactor. Add L2 and L1 as the refactor lands.

### Reusability beyond superharness
This pattern generalizes to any "X is the source of truth" invariant in your stack (e.g. "SQLite is truth in nocture", "the vault is truth for notes"). The L3 fitness-function + L4 manifest approach is a portable template — a forbidden-pattern guard plus a computed-completeness test — that you could drop into any repo where a stated architectural rule needs teeth.

---

## Part 5 — Maximum bulletproofing (the full system)

L1–L5 make *this* drift impossible. This section is the maximal architecture against the **whole class**: doctrine drift, doc rot, dead-code-that-looks-live, silent-success bugs, and false stored knowledge.

### The honest ceiling (read this first)
"Never" is not reachable, and chasing it has its own failure mode: armor nobody maintains rusts, and then the guards themselves become false claims. Three hard limits:
1. **Generated artifacts inherit the generator's bugs** — a generated doc can still be wrong if the generator is.
2. **World-truth can't be proven statically** — whether a stored *fact* is still true (an IP, a deadline, a deployment state) is only knowable by re-checking reality. Static analysis cannot help here.
3. **Every layer has a maintenance cost** — over-armoring a low-traffic invariant is waste, and the complexity can itself become a source of error.

So the real target is precise: **make every drift expressible as a static pattern or testable property structurally impossible to merge, and make the residual (data/world truth) continuously self-correcting and self-expiring.** Everything below serves that target.

### The unifying principle: no unbacked claim
> Anything that *describes* the system must be **generated from**, **tested against**, or **continuously verified against** the system. A hand-authored claim that runs in parallel to reality will always drift. Eliminate parallel descriptions; where you can't, bind the claim to an assertion.

The misconfigured `handoffs_fts` is the perfect example: its column list (`agent`, `summary`) was hand-authored *separately* from the `handoffs` table definition (`from_agent`, `to_agent`). Two parallel descriptions of the same shape → one drifted. A generated schema makes that impossible.

### The maximal layer stack (superset of L1–L5)

**L6 — Single definition, generate the rest.**
Define each state entity **once** (a schema/model). Generate the SQLite table, the DAO types, the validator, AND the docs from that one definition. No parallel hand-authored shapes → the FTS-column-mismatch class cannot occur. *Closes: dead-code-that-looks-live, schema/doc divergence.*

**L7 — Generated + doctest-bound documentation.**
Docs describing schema/API/state are generated and diffed in CI (stale doc = failed build). Prose claims that assert an invariant must embed an executable reference (doctest-style) that runs in CI. *Closes: doc rot, prose claims with no teeth.*

**L8 — Property-based & metamorphic tests.**
Beyond example tests: assert invariants over *generated* inputs.
- Property: "for any write through the API, a read returns it with **zero** file reads" (instrument the FS layer; fail if a state file is opened).
- Metamorphic: "recall results are byte-identical with and without export files present" — the generalized L2 parity test, run over random corpora. *Closes: silent-success bugs, the exact class that hid this for months.*

**L9 — Poison/canary values in tests.**
Seed export YAML with a `POISON_DO_NOT_READ` marker during tests. If any reader's output ever contains the poison, it read the export → instant, unambiguous failure. A trap specifically for "accidentally correct" reads. *Closes: silent success, even when DB and export happen to agree.*

**L10 — Runtime invariant assertions + a reconciler.**
Static analysis can't see *data-level* divergence. So:
- Critical paths assert their invariants at runtime (dev/staging), failing loud.
- A periodic **reconciler job** diffs the DB against any export and alerts on divergence — the same shape as the watcher you already run. *Closes: data drift that escapes static checks.*

**L11 — Append-only audit log as ground truth (event sourcing-lite).**
Every state mutation flows through one chokepoint that appends to an immutable log; the DB is rebuildable from it. You already have `ledger` — promote it to authoritative audit. Now "what is true and how it got that way" is reconstructable and tamper-evident. *Closes: "we don't know why state is X", undetected out-of-band writes.*

**L12 — Mutation-test the guards (who watches the watchmen).**
Guards can be false too — a test that passes regardless protects nothing. Mutation testing injects a violation (e.g. add a YAML glob to a command) and confirms the L3 guard **fails**. If the guard doesn't catch the injected violation, the guard is broken. This is the layer that keeps the bulletproofing itself honest. *Closes: rotting/ineffective guards — the meta-failure.*

### The knowledge / false-information layer (ties to the memory thread)
Code invariants are only half. For *stored knowledge* (memory files, vault notes, docs asserting facts about deployments) the world-truth limit (#2 above) applies, so the mechanism is different: **provenance + verification expiry.**
- Every stored claim carries **provenance** (where it came from) and a **last-verified timestamp**.
- Claims re-verify against reality on a schedule or **expire** (this is exactly the active-forgetting design from the ARCH-memory-architecture-extractions-2026-05-22.md design doc, generalized).
- A claim with no source or stale verification is **flagged, not trusted**.
- "Verify before recommend" becomes mechanical, not a habit.

This is why the earlier active-forgetting discussion and this drift analysis are the **same problem** at two layers: a stored assertion (a memory, or a docstring) that nobody re-checks against reality silently becomes false. The fix is identical in shape — bind the claim to continuous verification or let it expire.

### How the maximal stack maps to failure modes

| Failure mode | Layers that close it |
|---|---|
| Bypassable invalid action | L1 (chokepoint), L6 (single definition) |
| Silent success ("accidentally correct") | L2, L8, L9 |
| Unchecked violation | L3, L12 |
| False "complete" / over-generalized claim | L4 |
| Dead code that looks live / schema mismatch | L6, L7 |
| Doc rot | L7 |
| Data-level drift (DB ≠ export) | L10, L11 |
| Guards that silently stop working | L12 |
| Stale stored facts / false knowledge | provenance + expiry (knowledge layer) |

### Realistic maximal target & cost warning
Adopting **L1–L12 + the knowledge layer** makes every *statically expressible* drift impossible to merge and every *data/world* drift self-correcting within one reconcile/verify cycle. That is the practical maximum.

But heed the ceiling: this is a lot of machinery. Recommended escalation, not big-bang —
- **Tier 1 (must, cheap):** L3 + L4 + L5 + L12. Guards + manifest + mutation-tested guards. Small, and self-protecting.
- **Tier 2 (high payoff):** L2 + L9 + L8. Kill silent success three ways.
- **Tier 3 (structural):** L1 + L6 + L7. The single-definition refactor — eliminates parallel descriptions at the root.
- **Tier 4 (data truth):** L10 + L11 + the knowledge/provenance layer. Continuous reconciliation for what static checks can't see.

Do not build a layer you won't maintain — an unmaintained guard is just another false claim. Add each layer only with L12 covering it, so the armor can't silently rot. **The maximum that survives is the maximum that's self-checking.**
