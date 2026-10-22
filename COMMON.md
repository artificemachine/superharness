<!-- COMMON.md: agent-agnostic loader content shared by CLAUDE.md/AGENTS.md/GEMINI.md
     (rules pointer + safety block) only. If this grows beyond a pointer plus
     safety-style boilerplate, that content belongs in RULES.md, not here. -->

## Rules
**All project doctrine lives in `RULES.md`. Read it before any work.**
It covers: Task Lifecycle, CHANGELOG Policy, Strict Rules, Branching Convention,
Spec / Decision / Verification, Doctrine Guard usage, the superharness cross-agent protocol.
New rules land in `RULES.md`, never here.

## Safety (verbatim, survives any skipped read)
- Never commit directly to `main`
- No hardcoded secrets or local paths in committed files
- Repo visibility is **private by default**: never create or flip the remote to public without the owner's explicit confirmation in that session. A repo that is public by design declares it with a non-empty `.public-repo` marker holding the reason
