# Observability Specification (D2)

**Status:** draft — generated from multi-agent discussion consensus
**Date:** 2026-05-25
**Source:** Production readiness discussion (discuss-20260525T114727Z)

## Purpose

Define the metrics engine and health dashboard for superharness. When implementation starts on self-learning (Level 7), the Metrics Engine is built to this spec.

## 1. Data integrity — `learning_metrics` table

```sql
CREATE TABLE IF NOT EXISTS learning_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent           TEXT NOT NULL,           -- claude-code, codex-cli, etc.
    task_id         TEXT,                    -- task this metric belongs to
    metric_type     TEXT NOT NULL,           -- latency, accuracy, completion, retry
    value           REAL NOT NULL,           -- numeric value
    unit            TEXT,                    -- ms, percent, count
    recorded_at     TEXT NOT NULL,           -- ISO timestamp
    context         TEXT                     -- additional JSON context
);
CREATE INDEX IF NOT EXISTS idx_metrics_agent ON learning_metrics(agent);
CREATE INDEX IF NOT EXISTS idx_metrics_type  ON learning_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_metrics_time  ON learning_metrics(recorded_at);
```

**Metric types:**

| Type | Unit | Description |
|------|------|-------------|
| `latency_ms` | ms | Time from dispatch to completion |
| `accuracy_rate` | percent | Tasks completed without retry vs total dispatched |
| `completion_rate` | percent | Tasks reaching `done` vs total dispatched |
| `retry_count` | count | Total retries per task |
| `cost_usd` | USD | Actual cost per task |
| `uptime` | percent | Agent heartbeat uptime over last 24h |

## 2. Dashboard — Health & Performance panel

New dashboard panel at `/api/health`:

```json
{
  "agents": [
    {
      "agent": "claude-code",
      "uptime_pct": 98.5,
      "accuracy_rate": 87.2,
      "avg_latency_ms": 45000,
      "tasks_completed_24h": 12,
      "tasks_failed_24h": 2,
      "cost_24h_usd": 3.45
    }
  ],
  "system": {
    "watcher_uptime_pct": 99.9,
    "total_tasks_24h": 34,
    "total_cost_24h_usd": 8.92,
    "gc_last_run": "2026-05-25T16:00:00Z"
  }
}
```

## 3. KPIs

### Primary
- **Accuracy Rate** = `done / (done + failed)` over 24h rolling window
- **AI Latency** = avg time from `launched` to `done` per agent

### Secondary  
- **Cost Efficiency** = `total_cost / tasks_completed`
- **Retry Rate** = `retried_tasks / total_tasks`
- **Watcher Uptime** = heartbeat continuity over 24h

## 4. Alert thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Agent uptime | < 95% | < 80% |
| Accuracy rate | < 80% | < 60% |
| Avg latency | > 120s | > 300s |
| Retry rate | > 20% | > 40% |
| GC last run | > 10 min | > 30 min |

## 5. Implementation steps

1. Migration: add `learning_metrics` table (schema v27)
2. DAO: `learning_metrics_dao.py` with `record()`, `get_agent_stats()`, `get_system_stats()`
3. Capture: record metrics on task completion, retry, failure
4. Dashboard: `GET /api/health` endpoint
5. Status: `shux status` shows per-agent health section
6. Alerting: `shux notify` fires on critical thresholds
