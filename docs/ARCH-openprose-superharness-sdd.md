# OpenProse and Superharness as an SDD System

OpenProse and Superharness form a spec-driven development system only when the OpenProse contract drives and gates Superharness work. Installing Reactor beside Superharness is not sufficient.

```text
.prose.md specification
        ↓ compile
Reactor detects unmet responsibility/postcondition
        ↓
Superharness receives a finite implementation task
        ↓
TDD: RED → GREEN → REFACTOR
        ↓
Superharness verifies tests and evidence
        ↓
Reactor verifies the maintained truth
        ↓
Spec → task → diff → tests → receipts
```

The integration requires:

- `.prose.md` is the authoritative desired state.
- Every Shux task links to a responsibility, facet, and spec hash.
- Acceptance criteria derive from the specification.
- Implementation cannot silently change the specification.
- Completion requires Superharness verification and Reactor postconditions.
- Requirement changes modify the specification first.
- Traceability connects specification, task, code diff, tests, and receipts.

This is natural-language or agentic SDD. It is weaker than classical formal SDD because OpenProse compilation involves an intelligent agent, but stronger than ordinary prompt-driven development because the specification is persistent, versioned, executable, and verified.

OpenProse defines what must remain true, Reactor detects drift, and Superharness delivers and verifies finite code changes.
