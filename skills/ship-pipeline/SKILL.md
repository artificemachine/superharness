---
name: ship-pipeline
description: Security-first ship pipeline — security scan, test, build, commit, deploy
triggers:
  - ship
  - deploy
  - commit
  - ready to ship
  - "/ship"
---

# Ship Pipeline

Every ship follows this exact sequence. No steps skipped.

## Pipeline Stages

### 1. Security Scan (BLOCKING)
```bash
# Run RepoSec SAST if available
reposec scan . --format=table 2>/dev/null || echo "WARN: reposec not installed"

# Check for secrets
git diff --cached | grep -iE "(api_key|secret|token|password|credential)" && echo "BLOCKED: Possible secret in staged files" && exit 1
```
**Rule:** Never skip security scan. If reposec is not installed, at minimum run the grep check.

### 2. Rules Verify
Confirm the code follows project CLAUDE.md conventions:
- Naming conventions
- File structure
- Import ordering
- Error handling patterns

### 3. Branch Check
```bash
# Ensure you're not on main
BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  echo "BLOCKED: Cannot ship directly to $BRANCH. Create a feature branch."
  exit 1
fi
```

### 4. Pre-commit Hooks
```bash
# Let pre-commit hooks run (linting, formatting)
git add -A
git commit -m "feat: [description]"
# If hooks fail, fix and retry. Never --no-verify.
```

### 5. Test
```bash
# Python
pytest -x --tb=short 2>/dev/null

# C++
cmake --build build --target test 2>/dev/null

# JS/TS
npm test 2>/dev/null
```
**Rule:** If tests fail, stop. Fix before shipping.

### 6. Build
```bash
# Verify clean build
cmake --build build 2>/dev/null || npm run build 2>/dev/null || echo "No build step configured"
```

### 7. Hygiene
```bash
# Clean up debug artifacts
find . -name "*.pyc" -delete 2>/dev/null
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
find . -name ".DS_Store" -delete 2>/dev/null
```

### 8. Final Commit
```bash
git status
git log --oneline -3
echo "Ship complete. Ready to push."
```

## Rules

- Security scan is ALWAYS step 1. Non-negotiable.
- Never use `--no-verify` on commits.
- Never push directly to main/master.
- If any stage fails, stop and fix before continuing.
- Cross-agent review should happen before ship when possible.

## Quick Ship (for trivial changes)
For typos, docs, or config-only changes:
```
security scan → commit → push
```
Skip test/build only if no code changed.
