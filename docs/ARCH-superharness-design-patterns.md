# Superharness Design Patterns

## Current architecture

```mermaid
flowchart TB
    CLI["Click CLI\nFacade + Command"] --> Commands["commands/*"]
    Commands --> Watcher["inbox_watch.py\n5,594 LOC\nreconcile · dispatch · liveness\ndiscussions · telemetry"]
    Commands --> StateMachine["next_action.py\nState Machine"]
    Commands --> Adapters["harnesses + adapter_manifests\nStrategy + Registry"]
    Commands --> Supervisor["operator.py + daemon.py\nSupervisor"]
    Commands -. direct SQL .-> DB["engine/db.py"]
    Watcher -. 77 direct connections .-> DB
    StateMachine --> ReaderWriter["state_reader.py + state_writer.py"]
    ReaderWriter --> DAOs["*_dao.py\nRepository layer"]
    DAOs --> DB
    DB --> SQLite[(SQLite)]
```

## Target architecture

```mermaid
flowchart TB
    subgraph Inbound["Inbound adapters"]
        CLI["CLI"]
        Hooks["Hooks"]
        MCP["MCP"]
        Dashboard["Dashboard"]
    end

    subgraph Application["Application services"]
        Reconcile["Reconciliation service"]
        Dispatch["Dispatch service"]
        Liveness["Liveness service"]
        Discussion["Discussion service"]
        Telemetry["Telemetry service"]
    end

    subgraph Domain["Domain"]
        Lifecycle["next_action.py\nState Machine"]
        Schemas["schemas.py"]
        Rules["lifecycle_rules.py"]
    end

    subgraph Ports["Ports"]
        TaskStore["TaskStore"]
        InboxStore["InboxStore"]
        EventSink["EventSink"]
    end

    subgraph Outbound["Outbound adapters"]
        DAOs["DAOs"]
        SQLite[(SQLite)]
        Launchers["Harness launchers"]
    end

    Inbound --> Application --> Domain --> Ports --> DAOs --> SQLite
    Application --> Launchers
```

Keep Command, State Machine, Repository/DAO, Strategy/Registry, and Supervisor.

Start by extracting `reconcile` from `inbox_watch.py`; do not introduce a heavy clean-architecture framework.
