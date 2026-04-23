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
    hb_file = sh_dir / "agent-pulse.yaml"
    
    op = Operator(project_dir)
    
    # 1. Test: Missing file
    status = op.check_watcher_health()
    assert not status.is_healthy
    assert "missing" in status.message.lower()
    
    # 2. Test: Healthy heartbeat (just now)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    hb_file.write_text(yaml.dump({"timestamp": now_iso}))
    
    status = op.check_watcher_health()
    assert status.is_healthy
    assert "healthy" in status.message.lower()
    
    # 3. Test: Stale heartbeat (2 minutes ago)
    stale_dt = datetime.now(timezone.utc) - timedelta(minutes=2)
    stale_iso = stale_dt.isoformat().replace("+00:00", "Z")
    hb_file.write_text(yaml.dump({"timestamp": stale_iso}))
    
    status = op.check_watcher_health(stale_threshold_sec=60)
    assert not status.is_healthy
    assert "stale" in status.message.lower()
    assert "120s" in status.message # approximately

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
    assert len(summary["components"]["conflicts"]) == 1
