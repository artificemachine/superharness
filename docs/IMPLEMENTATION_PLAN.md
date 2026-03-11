# superharness Refactor Implementation Plan

## Goal
Refactor the codebase into clear layers without changing runtime behavior:
- `protocol/` for shared rules/templates
- `engine/` for Ruby logic
- `cli/` for user-facing shell entrypoints
- `adapters/` for integrations

## Non-Goals
- No lifecycle semantic changes.
- No breaking CLI behavior for existing users.
- No immediate deletion of historical/reference docs without migration path.

## Constraints
- Keep current workflow functional at every step.
- Ship in small, reversible commits.
- Preserve backwards-compatible script entrypoints while migrating.

## Target Architecture
```text
superharness/
├── protocol/
│   ├── spec.md
│   ├── templates/
│   └── schema/ (optional later)
├── engine/
│   ├── inbox.rb
│   ├── contract.rb
│   └── validate.rb
├── cli/
│   ├── init.sh
│   ├── enqueue.sh
│   ├── dispatch.sh
│   ├── normalize.sh
│   ├── delegate.sh
│   ├── hygiene.sh
│   └── watch.sh
├── adapters/
├── tests/
├── docs/
└── README.md
```

## Phase Plan

### Phase 0: Baseline and Safety
1. Freeze behavior with tests:
- Add/confirm tests for enqueue/dispatch/delegate/hygiene paths.
- Add contract query unit tests for task existence/path lookup.
2. Add compatibility rule:
- Existing script names remain callable during migration.

Acceptance:
- Test suite green.
- Existing commands still work from README examples.

### Phase 1: Engine Extraction
1. Create `engine/contract.rb`:
- `task_exists`
- `task_project_path`
- `contract_id`
2. Create `engine/validate.rb`:
- Move embedded Ruby logic from `check-contract-hygiene.sh`.
3. Move/rename `scripts/inbox-yaml.rb` -> `engine/inbox.rb` (or wrapper to it).

Acceptance:
- No shell script parses YAML directly.
- Same outputs/errors as before on key workflows.

### Phase 2: CLI Unification
1. Add `cli/delegate.sh --to claude-code|codex-cli`.
2. Replace duplicate delegate scripts with wrappers:
- `scripts/delegate-to-claude.sh` -> wrapper calling `cli/delegate.sh --to claude-code`
- `scripts/delegate-to-codex.sh` -> wrapper calling `cli/delegate.sh --to codex-cli`
3. Move enqueue/dispatch/normalize/watch wrappers to `cli/` and keep legacy script shims.

Acceptance:
- One delegate implementation path.
- `--print-only` behavior consistent regardless of target.

### Phase 3: Protocol Source of Truth
1. Create `protocol/spec.md`:
- lifecycle
- contract/handoff/ledger expectations
- delegation prompts (minimal + advanced reference)
2. Create `protocol/templates/` for:
- `contract.yaml`
- handoff template
- minimal generated snippets for CLAUDE/AGENTS
3. Update `init-project.sh` to generate minimal files referencing spec/docs.

Acceptance:
- No duplicated long protocol rules in generated files.
- Generated files are shorter and onboarding-focused.

### Phase 4: Docs and Repository Shape
1. Update README to reflect final runtime architecture.
2. Move personal/reference-heavy content to `_reference/` or separate repo.
3. Keep `docs/ARCHITECTURE.md` concise and runtime-oriented.

Acceptance:
- New users can identify runnable parts in <30 seconds.
- Runtime repo no longer mixes notebook content with operational code.

## Backward Compatibility Strategy
- Maintain old entrypoints as shims for at least one minor version.
- Print deprecation warnings from legacy scripts with migration hints.
- Keep command flags stable where possible.

## Risk Register
1. Path breakage from script moves
- Mitigation: wrappers + integration tests.
2. Prompt drift after template consolidation
- Mitigation: snapshot tests for generated files.
3. Platform-specific behavior regressions
- Mitigation: keep launchd scripts unchanged until final phase.

## Test Strategy
- Unit:
  - engine contract queries
  - engine inbox transitions
  - engine hygiene validation
- Integration:
  - enqueue -> dispatch -> failure/retry paths
  - delegate print-only/non-interactive flows
- E2E:
  - init project -> contract setup -> delegate -> hygiene checks

## Proposed Commit Sequence
1. `test: add contract query and delegate behavior coverage`
2. `refactor: extract contract YAML queries to engine/contract.rb`
3. `refactor: move hygiene Ruby logic to engine/validate.rb`
4. `refactor: unify delegate scripts under cli/delegate.sh`
5. `refactor: add cli wrappers and retain legacy script shims`
6. `docs: add protocol/spec.md and protocol/templates`
7. `refactor: slim init-generated CLAUDE/AGENTS to minimal defaults`
8. `docs: separate operational architecture from reference content`

## Definition of Done
- All current workflows pass tests and manual smoke checks.
- No direct YAML parsing in shell scripts.
- Single delegate implementation.
- Minimal generated agent files with references to protocol spec.
- Clear runtime architecture visible in README and `docs/ARCHITECTURE.md`.
