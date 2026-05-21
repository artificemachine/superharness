"""Auto-generated daemon monitor — do not edit."""
import os, sys, time, json, subprocess, signal

import logging
logger = logging.getLogger(__name__)
project_dir = sys.argv[1]
interval = int(sys.argv[2])
out_log = sys.argv[3]
err_log = sys.argv[4]
watcher_pid = int(sys.argv[5])

python = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/python3")
if not os.path.isfile(python):
    python = sys.executable

def spawn():
    cmd = [python, "-m", "superharness.commands.inbox_watch",
           "--project", project_dir, "--interval", str(interval), "--once"]
    env = os.environ.copy()
    src_root = os.path.join(project_dir, "src")
    if os.path.exists(src_root):
        env["PYTHONPATH"] = src_root
    return subprocess.Popen(cmd, stdout=open(out_log, "a"),
                            stderr=open(err_log, "a"),
                            start_new_session=True, cwd=project_dir, env=env)

def write_state(watcher_proc):
    sf = os.path.join(project_dir, ".superharness", "daemon-state.json")
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    with open(sf, "w") as f:
        json.dump({"pid": os.getpid(), "watcher_pid": watcher_proc.pid,
                     "project": project_dir, "interval": interval,
                     "log_out": out_log, "log_err": err_log}, f)

proc = spawn()
write_state(proc)

while True:
    exit_code = proc.wait()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = os.path.join(project_dir, ".superharness", "watcher-errors.log")
    if exit_code == 0:
        msg = "watcher exited cleanly (rc=0), restarting in 5s"
    else:
        msg = f"watcher crashed (rc={exit_code}), restarting in 5s"
    try:
        with open(log_path, "a") as lf:
            lf.write(f"[{ts}] daemon: {msg}\n")
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
        pass
    time.sleep(5)
    proc = spawn()
    write_state(proc)
