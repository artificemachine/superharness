#!/bin/bash
# newblacc-superharness session-start hook
# Runs at every Claude Code session startup.
# Loads project context and emits skill availability.

set -euo pipefail

SKILLS_DIR="$(dirname "$0")/../skills"
PROJECT_ROOT="${PWD}"

# --- Detect project context ---
CLAUDE_MD=""
if [ -f "${PROJECT_ROOT}/CLAUDE.md" ]; then
  CLAUDE_MD="${PROJECT_ROOT}/CLAUDE.md"
elif [ -f "${HOME}/.claude/CLAUDE.md" ]; then
  CLAUDE_MD="${HOME}/.claude/CLAUDE.md"
fi

# --- Emit available skills ---
SKILL_LIST=""
for skill_dir in "${SKILLS_DIR}"/*/; do
  if [ -f "${skill_dir}/SKILL.md" ]; then
    skill_name=$(basename "${skill_dir}")
    SKILL_LIST="${SKILL_LIST}${skill_name}, "
  fi
done
SKILL_LIST="${SKILL_LIST%, }"

# --- Output context for agent ---
cat << EOF
## newblacc-superharness v0.1.0

**Project root:** ${PROJECT_ROOT}
**CLAUDE.md:** ${CLAUDE_MD:-"not found"}
**Available skills:** ${SKILL_LIST}

### Auto-loaded rules
- Route tasks before executing (use session-routing skill)
- Cross-agent review after implementation (use cross-agent-review skill)
- Never skip security scan in ship pipeline
- Update vault at session end (/upvault)
EOF
