Task: Telegram + Discord modules (mod.10-telegram)

## Plan (from docs/)
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

## Acceptance Criteria
- 3 tests pass in test_module_telegram.py

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done