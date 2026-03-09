# superharness Quickstart

This is the shortest path to run superharness on a project.

## 1) Initialize project protocol

```bash
cd /path/to/your/project
bash /path/to/superharness/superharness init "My Project" "Node/TypeScript" "active"
```

## 2) Add one task to contract

Edit `.superharness/contract.yaml`:

```yaml
tasks:
  - id: demo-task
    title: "Run first delegation"
    owner: codex-cli
    status: todo
    project_path: "/absolute/path/to/your/project"
```

## 3) Enqueue work

```bash
bash /path/to/superharness/superharness enqueue --project . --to codex-cli --task demo-task --priority 1
```

## 4) Preview dispatch prompt (safe)

```bash
bash /path/to/superharness/superharness dispatch --project . --to codex-cli --print-only
```

## 5) Run hygiene + stale recovery

```bash
bash /path/to/superharness/superharness recover --project . --timeout-minutes 20 --action stale
bash /path/to/superharness/superharness hygiene --project .
```

## Notes

- `--print-only` never launches CLI processes.
- Legacy `scripts/*.sh` commands still work.
- For automatic background execution on macOS, use launchd installer scripts.
