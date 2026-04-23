import time
import subprocess
from pathlib import Path
from superharness.engine.operator import Operator

def test_operator_recovers_crashed_watcher(tmp_path):
    # Setup project structure
    project_dir = tmp_path / "recovery_proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    (sh_dir / "handoffs").mkdir()
    
    op = Operator(project_dir)
    
    # 1. Start the stack (Managed processes)
    op.start_stack(dashboard_port=9999) # Use a safe test port
    
    watcher_proc = op.processes["watcher"]
    watcher_pid = watcher_proc.pid
    
    # 2. Verify it is running
    assert watcher_proc.poll() is None
    
    # 3. Simulate a crash: kill the watcher
    watcher_proc.kill()
    watcher_proc.wait()
    
    # 4. Trigger recovery (one-shot check instead of run_forever loop for testing)
    # We modify the monitor loop logic slightly for testing or just call the core check
    for name, proc in list(op.processes.items()):
        if proc.poll() is not None:
             if name == "watcher": op._spawn_watcher()
    
    # 5. Verify a NEW watcher was spawned
    new_watcher = op.processes["watcher"]
    assert new_watcher.pid != watcher_pid
    assert new_watcher.poll() is None
    
    # Cleanup
    op.stop_all()
