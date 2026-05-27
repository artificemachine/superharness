import time
import yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta
from superharness.engine.operator import Operator

def test_operator_watchdog_detects_stale_heartbeat(tmp_path):
    # Setup project structure
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    
    # New canonical path
    hb_file = sh_dir / "watcher.heartbeat.yaml"
    
    op = Operator(project_dir)
    
    # 1. Test: Missing file
    status = op.check_watcher_health()
    assert not status.is_healthy
    assert "missing" in status.message.lower()
    
    # 2. Test: Healthy heartbeat (just now)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    hb_file.write_text(yaml.dump({"written_at": now_iso})) # Using correct field name
    
    status = op.check_watcher_health()
    assert status.is_healthy
    assert "healthy" in status.message.lower()
    
    # 3. Test: Stale heartbeat (3 minutes ago)
    stale_dt = datetime.now(timezone.utc) - timedelta(minutes=3)
    stale_iso = stale_dt.isoformat().replace("+00:00", "Z")
    hb_file.write_text(yaml.dump({"written_at": stale_iso}))
    
    status = op.check_watcher_health(stale_threshold_sec=120)
    assert not status.is_healthy
    assert "stale" in status.message.lower()

def test_operator_detects_zombie_lock(tmp_path):
    project_dir = tmp_path / "zombie_proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    lock_file = sh_dir / "inbox.lock"
    
    op = Operator(project_dir)
    
    # 1. Test: No lock = no conflicts
    assert len(op.check_resource_conflicts()) == 0
    
    # 2. Test: Dead PID in lock file
    lock_file.write_text("999999") # Assuming this PID doesn't exist
    conflicts = op.check_resource_conflicts()
    assert len(conflicts) == 1
    assert "dead" in conflicts[0].message.lower()
    
    # 3. Test: Summary reflects unhealthy state
    summary = op.get_summary()
    assert not summary["healthy"]


def test_operator_start_no_daemon_flag_exists(tmp_path):
    """operator_start must accept --no-daemon flag (foreground debugging mode)."""
    # operator_start is a Click Command — read the source file directly
    import inspect, pathlib
    src = (pathlib.Path(__file__).parent.parent.parent /
           "src" / "superharness" / "cli.py").read_text()
    # Find the operator_start function and check for --no-daemon
    assert "'--no-daemon'" in src or '"--no-daemon"' in src, (
        "operator_start must have @click.option with --no-daemon"
    )


def test_monitor_and_recover_docstring_updated(tmp_path):
    """monitor_and_recover docstring must reflect daemonization, not daemon thread."""
    from superharness.engine.operator import Operator
    import inspect

    op = Operator(str(tmp_path))
    doc = inspect.getdoc(op.monitor_and_recover) or ""
    assert "fork" in doc.lower() or "daemoniz" in doc.lower(), (
        f"monitor_and_recover docstring must mention daemonization, got: {doc[:80]}"
    )
