def _get_health(project_dir: str) -> dict:
    """Return per-agent health stats for the dashboard."""
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            agents = []
            hb_rows = conn.execute(
                "SELECT agent, status, updated_at FROM agent_heartbeats ORDER BY agent"
            ).fetchall()
            for hb in hb_rows:
                agent = hb["agent"]
                # Count completed/failed tasks in last 24h
                done = conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE target_agent=? AND status='done'",
                    (agent,),
                ).fetchone()[0]
                failed = conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE target_agent=? AND status='failed'",
                    (agent,),
                ).fetchone()[0]
                total = done + failed
                accuracy = round(done / total * 100, 1) if total > 0 else 100.0
                agents.append({
                    "agent": agent,
                    "status": hb["status"],
                    "last_seen": hb["updated_at"],
                    "tasks_done": done,
                    "tasks_failed": failed,
                    "accuracy_pct": accuracy,
                })
            return {"agents": agents, "total_agents": len(agents)}
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e)}
