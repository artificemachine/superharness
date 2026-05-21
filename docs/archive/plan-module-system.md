---
title: "Plan: Superharness Module System"
date: 2026-03-20
status: planned
approach: TDD (RED → GREEN → REFACTOR per iteration)
---

# Plan: Superharness Module System

> Core product: session memory for solo devs using AI coding agents.
> Modules: opt-in enhancements that plug into the task lifecycle.

## Design Principles

1. **Zero-config core** — `shux init` + `shux close` works with nothing installed
2. **Progressive discovery** — users find modules when they need them, not during setup
3. **Auto-detection** — modules detect their dependencies, no manual config
4. **Enable/disable, never install/uninstall** — modules are YAML templates, not packages
5. **Each module is independently testable** — no module depends on another module

## Security Rules (STRICT)

**NEVER include in source code, templates, tests, or examples:**
- SSH keys, API keys, tokens, passwords, or credentials of any kind
- Real IP addresses (private or public) — use `<YOUR_IP>`, `10.0.0.1`, or env var references
- Real hostnames, VM names, or infrastructure details (Proxmox, OPNsense, etc.)
- Real usernames, paths with real usernames, or personal identifiers
- Real Telegram/Discord bot tokens or user IDs — use `<YOUR_TOKEN>`, `123456789`
- Real ntfy topics or URLs pointing to live servers

**All secrets must come from:**
- Environment variables (referenced by name only: `TELEGRAM_BOT_TOKEN`, not the value)
- Config files excluded from git (`.env`, `config.yaml` in `.gitignore`)
- User input at runtime

**Module templates must use only:**
- `_env` suffix for secret references (e.g., `token_env: TELEGRAM_BOT_TOKEN`)
- Placeholder values in examples (e.g., `url: "https://ntfy.example.com"`)
- Generic test data (e.g., `allowed_user_ids: [123456789]`)

---

## Iteration 0: Module Loader Foundation

### RED — Write failing tests first

```python
# tests/unit/test_module_loader.py

class TestModuleLoader:
    def test_no_modules_dir_returns_empty(self, tmp_path):
        """No .superharness/modules/ → empty list, no error."""

    def test_loads_enabled_module(self, tmp_path):
        """YAML with enabled: true → module in loaded list."""

    def test_skips_disabled_module(self, tmp_path):
        """YAML with enabled: false → not in loaded list."""

    def test_invalid_yaml_skipped_with_warning(self, tmp_path):
        """Malformed YAML → skipped, logged, no crash."""

    def test_module_has_name_and_hooks(self, tmp_path):
        """Loaded module exposes name, enabled, hooks dict."""
```

### GREEN — Minimal implementation

```python
# src/superharness/modules/loader.py

@dataclass
class Module:
    name: str
    enabled: bool
    hooks: dict        # {"on_close": {...}, "on_verify": {...}}
    settings: dict
    detect: dict
    file_path: Path

def load_modules(project_dir: Path) -> list[Module]:
    """Load all enabled modules from .superharness/modules/*.yaml"""
```

### REFACTOR

- Extract YAML parsing into safe helper (reuse existing `_safe_yaml_load` pattern)
- Add `Module.is_available()` method that runs detection checks

---

## Iteration 1: Module Runner (Lifecycle Hooks)

### RED

```python
# tests/unit/test_module_runner.py

class TestModuleRunner:
    def test_on_close_fires_for_enabled_module(self, tmp_path):
        """Module with on_close hook → action called when close runs."""

    def test_on_close_skips_disabled_module(self, tmp_path):
        """Disabled module → on_close not called."""

    def test_on_verify_fires(self, tmp_path):
        """Module with on_verify hook → action called when verify runs."""

    def test_on_continue_fires(self, tmp_path):
        """Module with on_continue hook → action called when continue runs."""

    def test_module_failure_does_not_block_close(self, tmp_path):
        """If module action fails → warning logged, close still succeeds."""

    def test_multiple_modules_all_fire(self, tmp_path):
        """Two enabled modules with on_close → both fire."""

    def test_hook_receives_context(self, tmp_path):
        """Hook action receives task_id, summary, project_dir, actor."""
```

### GREEN

```python
# src/superharness/modules/runner.py

LIFECYCLE_EVENTS = ["on_close", "on_verify", "on_continue", "on_delegate", "on_watcher_tick"]

def run_hooks(event: str, context: dict, project_dir: Path) -> list[dict]:
    """Load modules, fire all hooks for the given lifecycle event."""
```

### REFACTOR

- Wire into `close.py`: after close logic, call `run_hooks("on_close", ...)`
- Wire into `verify.py`: after verify logic, call `run_hooks("on_verify", ...)`
- Wire into `continue` command: call `run_hooks("on_continue", ...)`

---

## Iteration 2: Module Registry + `shux enhance`

### RED

```python
# tests/unit/test_module_registry.py

class TestModuleRegistry:
    def test_list_available_modules(self):
        """Lists all built-in module templates."""

    def test_list_enabled_modules(self, tmp_path):
        """Lists only modules enabled in .superharness/modules/."""

    def test_enable_copies_template(self, tmp_path):
        """shux enhance enable obsidian → copies obsidian.yaml to modules/."""

    def test_enable_already_enabled_is_noop(self, tmp_path):
        """Enabling an already-enabled module → no-op, idempotent."""

    def test_disable_sets_enabled_false(self, tmp_path):
        """shux enhance disable obsidian → sets enabled: false in YAML."""

    def test_disable_already_disabled_is_noop(self, tmp_path):
        """Disabling already-disabled → no-op, idempotent."""

    def test_enable_unknown_module_fails(self, tmp_path):
        """shux enhance enable nonexistent → error with available list."""

    def test_info_shows_module_details(self, tmp_path):
        """shux enhance info obsidian → shows description, detection, settings."""
```

### GREEN

```python
# src/superharness/modules/registry.py

TEMPLATE_DIR = Path(__file__).parent.parent / "module_templates"

def available_modules() -> list[str]:
def enabled_modules(project_dir: Path) -> list[str]:
def enable_module(name: str, project_dir: Path) -> bool:
def disable_module(name: str, project_dir: Path) -> bool:
def module_info(name: str, project_dir: Path) -> dict:
```

### CLI

```python
# Add to cli.py
@main.group()
def enhance():
    """Module marketplace — enable, disable, list integrations."""

@enhance.command("list")    # shux enhance / shux enhance list
@enhance.command("enable")  # shux enhance enable <name>
@enhance.command("disable") # shux enhance disable <name>
@enhance.command("info")    # shux enhance info <name>
```

### REFACTOR

- `shux enhance` with no args → same as `shux enhance list`
- Add color coding: ✓ enabled, ◻ available, ✗ missing dependency
- Add `--json` output for scripting

---

## Iteration 3: Obsidian Module (first real module)

### RED

```python
# tests/unit/test_module_obsidian.py

class TestObsidianModule:
    def test_detect_vault_path(self, tmp_path):
        """Finds vault at known paths."""

    def test_detect_no_vault(self, tmp_path):
        """No vault found → level 1 only (local handoffs)."""

    def test_detect_mcp_available(self, tmp_path):
        """MCP server running → level 3."""

    def test_on_close_writes_vault_note(self, tmp_path):
        """Close fires → markdown note written to vault."""

    def test_on_close_no_vault_is_silent(self, tmp_path):
        """No vault → no error, no write, warning logged."""

    def test_vault_note_has_frontmatter(self, tmp_path):
        """Written note has YAML frontmatter with tags, date, title."""

    def test_vault_path_uses_project_name(self, tmp_path):
        """Note saved to 1_ai/{project_name}/{project}-{date}-{title}.md."""

    def test_no_secrets_in_vault_note(self, tmp_path):
        """API keys, tokens, private IPs redacted from note."""
```

### GREEN

```python
# src/superharness/module_templates/obsidian.yaml
name: obsidian
description: "Save task handoffs to Obsidian vault — auto-detected, no config needed"
enabled: false
detect:
  any_path:
    - ~/Documents/OBSIDIAN_ICLOUD/coredev/
    - ~/Documents/Obsidian/
  optional_bin: osm
  optional_mcp: obsidian-semantic
hooks:
  on_close:
    action: obsidian_write_note
settings:
  vault_subfolder: "1_ai/{project_name}/"
  filename_pattern: "{project_name}-{date}-{title}.md"
  redact_secrets: true
```

```python
# src/superharness/modules/actions/obsidian.py

def obsidian_write_note(context: dict, settings: dict) -> bool:
    """Write task handoff as Obsidian vault note. Returns True if written."""
```

### REFACTOR

- Extract redaction logic from /upvault command into shared utility
- MCP detection: check if `mcp__obsidian-semantic__write_file` is callable

---

## Iteration 4: Security Module

### RED

```python
# tests/unit/test_module_security.py

class TestSecurityModule:
    def test_detect_shipguard(self, tmp_path):
        """shipguard binary found → module available."""

    def test_on_verify_runs_shipguard(self, tmp_path):
        """Verify fires → shipguard scan runs, result included in verification."""

    def test_on_verify_critical_blocks(self, tmp_path):
        """Critical finding → verify returns fail."""

    def test_on_verify_no_shipguard_skips(self, tmp_path):
        """shipguard not found → skip silently."""
```

### GREEN

```python
# src/superharness/module_templates/security.yaml
name: security
description: "Auto-run shipguard SAST on verify — blocks on critical findings"
enabled: false
detect:
  any_bin: [shipguard, gitleaks]
hooks:
  on_verify:
    action: security_scan
    block_on: critical
settings:
  severity_threshold: high
```

---

## Iteration 5: Ship Module

### RED

```python
# tests/unit/test_module_ship.py

class TestShipModule:
    def test_on_close_runs_ship(self, tmp_path):
        """Close fires → git add, commit, push."""

    def test_on_close_no_changes_skips(self, tmp_path):
        """No uncommitted changes → ship skipped."""

    def test_on_close_ship_failure_warns(self, tmp_path):
        """Ship fails → warning, close still succeeds."""
```

### GREEN

```python
# src/superharness/module_templates/ship.yaml
name: ship
description: "Auto-commit and push on task close"
enabled: false
detect:
  bin: git
hooks:
  on_close:
    action: git_ship
settings:
  auto_push: false    # default: commit only, ask before push
```

---

## Iteration 6: Remember Module

### RED

```python
# tests/unit/test_module_remember.py

class TestRememberModule:
    def test_on_continue_refreshes_context(self, tmp_path):
        """Continue fires → reads CLAUDE.md, last handoff, contract."""

    def test_on_continue_no_handoff_still_works(self, tmp_path):
        """No previous handoff → just reads CLAUDE.md."""
```

### GREEN

```python
# src/superharness/module_templates/remember.yaml
name: remember
description: "Auto-refresh context from CLAUDE.md and last handoff on continue"
enabled: false
hooks:
  on_continue:
    action: refresh_context
```

---

## Iteration 7: Notification Module (ntfy)

### RED

```python
# tests/unit/test_module_ntfy.py

class TestNtfyModule:
    def test_on_close_sends_notification(self, tmp_path):
        """Close fires → ntfy push with task summary."""

    def test_on_verify_fail_sends_alert(self, tmp_path):
        """Verify fail → high-priority ntfy alert."""

    def test_ntfy_unavailable_skips(self, tmp_path):
        """ntfy server unreachable → skip, no crash."""
```

### GREEN

```python
# src/superharness/module_templates/ntfy.yaml
name: ntfy
description: "Push notifications on task events via ntfy"
enabled: false
detect:
  env: NTFY_TOPIC
hooks:
  on_close:
    action: ntfy_send
    priority: default
  on_verify:
    action: ntfy_send
    priority: high
    only_on: fail
settings:
  url: "https://ntfy.sh"
  topic_env: NTFY_TOPIC
```

---

## Iteration 8: OpenClaw Module

### RED

```python
# tests/unit/test_module_openclaw.py

class TestOpenClawModule:
    def test_on_delegate_routes_to_openclaw(self, tmp_path):
        """Delegate with --to openclaw → sends task via MCP."""

    def test_openclaw_not_available_fails(self, tmp_path):
        """No NemoClaw MCP → clear error with setup instructions."""
```

### GREEN

```python
# src/superharness/module_templates/openclaw.yaml
name: openclaw
description: "Delegate tasks to NemoClaw sandboxed agents"
enabled: false
detect:
  optional_mcp: nemoclaw
hooks:
  on_delegate:
    action: openclaw_send_task
    condition: "target == 'openclaw'"
```

---

## Iteration 9: Telegram + Discord Modules

### RED

```python
# tests/unit/test_module_telegram.py

class TestTelegramModule:
    def test_on_close_sends_summary(self, tmp_path):
        """Close fires → Telegram message with task summary."""

    def test_on_delegate_sends_link(self, tmp_path):
        """Delegate fires → Telegram message with task link."""

    def test_no_token_disables(self, tmp_path):
        """No TELEGRAM_BOT_TOKEN → module auto-disables."""
```

### GREEN

Reuse always-on-agent Telegram bridge code.

```python
# src/superharness/module_templates/telegram.yaml
name: telegram
description: "Telegram notifications and mobile task management"
enabled: false
detect:
  env: TELEGRAM_BOT_TOKEN
hooks:
  on_close:
    action: telegram_send
  on_delegate:
    action: telegram_send
settings:
  token_env: TELEGRAM_BOT_TOKEN
  allowed_user_ids: []
```

---

## Iteration 10: Auto-Schedule Module

### RED

```python
# tests/unit/test_module_auto_schedule.py

class TestAutoScheduleModule:
    def test_scheduled_task_auto_enqueued(self, tmp_path):
        """Task with scheduled_after <= today → auto-enqueued to inbox."""

    def test_future_task_not_enqueued(self, tmp_path):
        """Task with scheduled_after in future → not enqueued."""

    def test_blocked_dependency_not_enqueued(self, tmp_path):
        """Task with unfinished depends_on → not enqueued."""

    def test_already_enqueued_task_skipped(self, tmp_path):
        """Task already in inbox → not enqueued again (idempotent)."""

    def test_done_task_not_enqueued(self, tmp_path):
        """Task with status=done → skipped."""
```

### GREEN

```python
# src/superharness/module_templates/auto-schedule.yaml
name: auto-schedule
description: "Auto-delegate tasks when scheduled_after date arrives and dependencies are met"
enabled: false
hooks:
  on_watcher_tick:
    action: check_scheduled_tasks
settings:
  check_depends_on: true
  auto_target: claude-code    # default delegation target
```

```python
# src/superharness/modules/actions/auto_schedule.py

def check_scheduled_tasks(context: dict, settings: dict) -> list[str]:
    """Scan contract for tasks ready to delegate. Returns list of enqueued task IDs."""
    # For each task where:
    #   - status == "todo"
    #   - scheduled_after <= today (or not set)
    #   - depends_on all done (or not set)
    #   - not already in inbox
    # → auto-enqueue to inbox
```

### REFACTOR

- Add `on_watcher_tick` to LIFECYCLE_EVENTS in runner.py
- Wire into inbox_watch.py: after each poll cycle, call `run_hooks("on_watcher_tick", ...)`

---

## Iteration 11: `shux doctor` Module Health

### RED

```python
# tests/unit/test_doctor_modules.py

class TestDoctorModules:
    def test_doctor_shows_enabled_modules(self, tmp_path):
        """Doctor lists enabled modules with status."""

    def test_doctor_shows_missing_dependencies(self, tmp_path):
        """Module enabled but dependency missing → WARN."""

    def test_doctor_suggests_enhance(self, tmp_path):
        """No modules enabled → INFO with 'shux enhance' suggestion."""
```

### GREEN

Add module health section to existing `doctor.py`:

```
PASS modules: 3 enabled (obsidian, security, ntfy)
WARN module:telegram — TELEGRAM_BOT_TOKEN not set
INFO modules: 10 more available — run 'shux enhance' to browse
```

---

## File Structure (final)

```
superharness/
├── src/superharness/
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── loader.py          # Load YAML modules
│   │   ├── runner.py          # Execute hooks at lifecycle events
│   │   ├── registry.py        # Enable/disable/list modules
│   │   └── actions/           # Module action implementations
│   │       ├── __init__.py
│   │       ├── obsidian.py
│   │       ├── security.py
│   │       ├── ship.py
│   │       ├── remember.py
│   │       ├── ntfy.py
│   │       ├── openclaw.py
│   │       ├── telegram.py
│   │       └── auto_schedule.py
│   └── module_templates/      # Built-in YAML templates
│       ├── obsidian.yaml
│       ├── security.yaml
│       ├── ship.yaml
│       ├── remember.yaml
│       ├── auto-schedule.yaml
│       ├── ntfy.yaml
│       ├── openclaw.yaml
│       ├── telegram.yaml
│       └── discord.yaml
└── tests/unit/
    ├── test_module_loader.py
    ├── test_module_runner.py
    ├── test_module_registry.py
    ├── test_module_obsidian.py
    ├── test_module_security.py
    ├── test_module_ship.py
    ├── test_module_remember.py
    ├── test_module_auto_schedule.py
    ├── test_module_ntfy.py
    ├── test_module_openclaw.py
    ├── test_module_telegram.py
    └── test_doctor_modules.py
```

---

## Execution Order

| Iteration | What | Tests | Effort | Priority |
|-----------|------|-------|--------|----------|
| **Foundation** | | | | |
| 0 | Module loader (YAML → dataclass) | 5 | 1 hr | Must have |
| 1 | Module runner (lifecycle hooks + on_watcher_tick) | 7 | 2 hr | Must have |
| 2 | Registry + `shux enhance` CLI | 8 | 2 hr | Must have |
| **High value** | | | | |
| 3 | Obsidian module (vault integration) | 8 | 3 hr | High — closes the knowledge loop |
| 4 | Auto-schedule module (auto-delegate on date/deps) | 5 | 2 hr | High — enables unattended task execution |
| 5 | Security module (shipguard gate on verify) | 4 | 2 hr | High — enforces quality |
| 6 | Remember module (context refresh on continue) | 2 | 1 hr | High — reduces context loss |
| **Medium value** | | | | |
| 7 | ntfy module (push notifications) | 3 | 1 hr | Medium — nice for mobile awareness |
| 8 | Ship module (auto-commit on close) | 3 | 1 hr | Medium — convenience |
| **Low value (defer)** | | | | |
| 9 | OpenClaw module (NemoClaw delegation) | 2 | 2 hr | Low — NemoClaw not stable yet |
| 10 | Telegram + Discord modules | 3 | 3 hr | Low — reuse always-on-agent later |
| 11 | Doctor module health | 3 | 1 hr | Low — polish |
| **Total** | | **~53 tests** | **~21 hr** | |

**Recommended build order:** 0 → 1 → 2 → 3 → 4 → 6 → 5 → 7 → 8 → 11 → 9 → 10

Iterations 0-2 are the foundation (~5 hr). Iterations 3-6 deliver the highest user value (~8 hr). Iterations 7-11 are nice-to-have and can be deferred or community-contributed.
