# superharness Architecture Diagram

```mermaid
graph TB
    subgraph User["User / Operator"]
        CLI["superharness CLI wrapper"]
        MonitorBrowser["Browser :8787"]
    end

    subgraph CLI_Shims["cli/ shims"]
        delegate_cli["delegate.sh"]
        task_cli["task.sh"]
        dispatch_cli["dispatch.sh"]
        watch_cli["watch.sh"]
        contract_cli["contract-today.sh"]
        other_cli["init / doctor / enqueue<br/>recover / normalize / hygiene"]
    end

    subgraph Scripts["scripts/ implementations"]
        delegate_to_claude["delegate-to-claude.sh"]
        delegate_to_codex["delegate-to-codex.sh"]
        inbox_dispatch["inbox-dispatch.sh"]
        inbox_watch["inbox-watch.sh"]
        inbox_enqueue["inbox-enqueue.sh"]
        inbox_deadline["inbox-deadline-check.sh"]
        inbox_recover["inbox-recover-stale.sh"]
        task_sh["task.sh"]
        monitor_ui["monitor-ui.py"]
        install_launchd["install-launchd-inbox-watcher.sh"]
    end

    subgraph Engine["engine/ Ruby core"]
        inbox_rb["inbox.rb"]
        contract_rb["contract.rb"]
        validate_rb["validate.rb"]
    end

    subgraph State[".superharness/ project state"]
        contract_yaml["contract.yaml"]
        inbox_yaml["inbox.yaml"]
        ledger_md["ledger.md"]
        handoffs["handoffs/*.yaml"]
        failures["failures.yaml"]
        decisions["decisions.yaml"]
    end

    subgraph Agents["Agent Runtimes"]
        claude["Claude Code<br/>-p --dangerously-skip-permissions"]
        codex["Codex CLI<br/>--full-auto"]
    end

    subgraph System["macOS System"]
        launchd["launchd<br/>com.superharness.inbox.*"]
        logs["~/Library/Logs/superharness/<br/>*.out.log / *.err.log"]
    end

    subgraph Hooks["adapters/claude-code/hooks/"]
        session_start["session-start.sh"]
        scope_guard["scope-guard.sh"]
        branch_guard["branch-guard.sh"]
    end

    %% User flows
    CLI --> CLI_Shims
    MonitorBrowser -->|HTTP GET/POST| monitor_ui

    %% CLI shim routing
    CLI_Shims --> Scripts

    %% Watcher pipeline
    launchd -->|every 30s| inbox_watch
    inbox_watch --> inbox_deadline
    inbox_watch --> inbox_recover
    inbox_watch --> inbox_dispatch

    %% Dispatch flow
    inbox_dispatch -->|next_pending| inbox_rb
    inbox_dispatch -->|claude-code| delegate_to_claude
    inbox_dispatch -->|codex-cli| delegate_to_codex
    inbox_dispatch -->|set_status / set_field| inbox_rb
    delegate_to_claude --> claude
    delegate_to_codex --> codex

    %% Enqueue flow
    inbox_enqueue --> inbox_rb

    %% Engine reads/writes state
    inbox_rb --> inbox_yaml
    contract_rb --> contract_yaml
    task_sh --> contract_rb
    inbox_deadline --> contract_rb
    inbox_deadline --> inbox_rb

    %% Monitor UI
    monitor_ui -->|tail| logs
    monitor_ui -->|read| inbox_yaml
    monitor_ui -->|read| ledger_md
    monitor_ui -->|read| contract_yaml
    monitor_ui -->|pause/resume/stop/retry| inbox_rb
    monitor_ui -->|launchctl print| launchd

    %% Agent hooks
    claude -->|on session start| session_start
    claude -->|on tool call| scope_guard
    claude -->|on tool call| branch_guard

    %% Agents write state
    claude -->|update| contract_yaml
    claude -->|append| ledger_md
    claude -->|write| handoffs
    codex -->|update| contract_yaml
    codex -->|append| ledger_md
    codex -->|write| handoffs

    %% Launchd setup
    install_launchd --> launchd
    inbox_watch -->|stdout/stderr| logs

    %% Styling
    classDef ruby fill:#cc342d,color:#fff,stroke:#8b0000
    classDef python fill:#3776ab,color:#fff,stroke:#2b5ea1
    classDef shell fill:#4eaa25,color:#fff,stroke:#2d6a13
    classDef state fill:#f5a623,color:#000,stroke:#d48b06
    classDef agent fill:#7b68ee,color:#fff,stroke:#5b48ce
    classDef system fill:#708090,color:#fff,stroke:#4a5568

    class inbox_rb,contract_rb,validate_rb ruby
    class monitor_ui python
    class inbox_dispatch,inbox_watch,inbox_enqueue,inbox_deadline,inbox_recover,task_sh,delegate_to_claude,delegate_to_codex,install_launchd,session_start,scope_guard,branch_guard shell
    class contract_yaml,inbox_yaml,ledger_md,handoffs,failures,decisions state
    class claude,codex agent
    class launchd,logs system
```

## Legend

| Color | Language/Type | Count |
|-------|--------------|-------|
| Green | Shell scripts | 39 files |
| Red | Ruby engine | 3 files |
| Blue | Python | 1 file (monitor-ui) |
| Orange | State files | YAML/MD (contract, inbox, ledger, handoffs) |
| Purple | Agent runtimes | Claude Code, Codex CLI |
| Gray | System | launchd, log files |

## Key Flows

### 1. Dispatch Pipeline
```
launchd (every 30s)
  -> inbox-watch.sh
    -> inbox-deadline-check.sh (fail expired tasks)
    -> inbox-recover-stale.sh (retry stale items)
    -> inbox-dispatch.sh
      -> inbox.rb next_pending (pick highest priority)
      -> delegate-to-claude.sh | delegate-to-codex.sh
        -> Claude Code | Codex CLI (agent runs task)
      -> inbox.rb set_status (launched -> done/failed)
```

### 2. Monitor UI
```
Browser :8787
  -> GET /api/status (watcher state, inbox counts, log tails)
  -> GET /api/inbox?status=X (filtered items with detail)
  -> POST /api/action (pause/resume/stop/retry/dispatch)
    -> inbox.rb set_status | set_field | os.kill(PID)
```

### 3. Agent Hooks (Claude Code)
```
Claude session start
  -> session-start.sh (load contract context)
Claude tool call
  -> scope-guard.sh (enforce contract scope)
  -> branch-guard.sh (enforce branch policy)
```

### 4. Task Lifecycle
```
todo -> in_progress -> done       (happy path)
todo -> in_progress -> failed     (agent failure, requires --reason)
todo -> in_progress -> stopped    (manual stop, requires --reason)
pending -> paused -> pending      (monitor-ui pause/resume)
launched -> stopped               (monitor-ui stop via SIGTERM)
stale/failed/stopped -> pending   (monitor-ui retry)
```
