Task: Onboarding: command-first shux help/demo + Windows docs (feat.onboarding-command-first)

## Plan (from docs/)
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

## Acceptance Criteria
- shux --help shows a clear first-commands quickstart
- shux demo guides a new user through command-first flow
- docs include Windows + pipx copy-paste onboarding
- focused tests/docs checks updated for new onboarding flow

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done