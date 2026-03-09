#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>superharness watcher monitor</title>
  <style>
    :root { --bg:#0b1220; --panel:#131c2e; --text:#e7ecf6; --muted:#9fb0d0; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; --line:#23314d; }
    body { margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:var(--bg); color:var(--text); }
    .wrap { max-width:1100px; margin:24px auto; padding:0 16px; }
    .grid { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px; }
    .k { color:var(--muted); font-size:12px; }
    .v { font-size:18px; margin-top:6px; }
    .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
    h1 { font-size:20px; margin:0 0 12px; }
    h2 { font-size:14px; margin:0 0 8px; color:var(--muted); }
    pre { margin:0; white-space:pre-wrap; word-break:break-word; font-size:12px; line-height:1.3; }
    .logs { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }
    .meta { margin:10px 0 16px; color:var(--muted); font-size:12px; }
    .pill { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; margin-right:6px; margin-top:4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>superharness watcher monitor</h1>
    <div class="meta" id="meta">loading...</div>
    <div class="grid">
      <div class="card"><div class="k">watcher label</div><div class="v" id="label">-</div></div>
      <div class="card"><div class="k">watcher state</div><div class="v" id="state">-</div></div>
      <div class="card"><div class="k">last refresh (UTC)</div><div class="v" id="ts">-</div></div>
    </div>
    <div class="card" style="margin-top:12px;">
      <h2>inbox status counts</h2>
      <div id="counts"></div>
    </div>
    <div class="logs">
      <div class="card">
        <h2>out.log tail</h2>
        <pre id="out">-</pre>
      </div>
      <div class="card">
        <h2>err.log tail</h2>
        <pre id="err">-</pre>
      </div>
    </div>
  </div>
<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('meta').textContent = `project: ${d.project} | refresh: ${d.refresh_seconds}s`;
    document.getElementById('label').textContent = d.label;
    const s = document.getElementById('state');
    s.textContent = d.launchctl_state || 'not-loaded';
    s.className = 'v ' + (d.launchctl_state === 'running' ? 'ok' : (d.launchctl_state ? 'warn' : 'bad'));
    document.getElementById('ts').textContent = d.now_utc;
    const counts = document.getElementById('counts');
    counts.innerHTML = '';
    const keys = Object.keys(d.inbox_counts || {}).sort();
    if (!keys.length) { counts.textContent = 'no inbox rows'; }
    for (const k of keys) {
      const el = document.createElement('span');
      el.className = 'pill';
      el.textContent = `${k}: ${d.inbox_counts[k]}`;
      counts.appendChild(el);
    }
    document.getElementById('out').textContent = (d.out_tail || []).join('\\n');
    document.getElementById('err').textContent = (d.err_tail || []).join('\\n');
  } catch (e) {
    document.getElementById('meta').textContent = 'error: ' + e;
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return [f"(missing) {path}"]
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [ln.rstrip("\n") for ln in lines[-n:]]


def watcher_state(label: str) -> str:
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            return ""
        for ln in out.stdout.splitlines():
            if "state =" in ln:
                return ln.split("=", 1)[1].strip()
    except Exception:
        return ""
    return ""


def inbox_counts(inbox_file: Path) -> dict[str, int]:
    counts = Counter()
    if not inbox_file.exists():
        return {}
    for ln in inbox_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = ln.strip()
        if line.startswith("status:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                counts[parts[1].strip()] += 1
    return dict(counts)


def project_label(project_dir: Path) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in project_dir.name).strip("-")
    if not slug:
        slug = "project"
    return f"com.superharness.inbox.{slug}"


class Handler(BaseHTTPRequestHandler):
    project_dir: Path
    label: str
    refresh_seconds: int

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # silence
        return

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            self._html(HTML)
            return
        if p == "/api/status":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            outlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.out.log"
            errlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.err.log"
            self._json(
                {
                    "project": str(self.project_dir),
                    "label": self.label,
                    "launchctl_state": watcher_state(self.label),
                    "inbox_counts": inbox_counts(inbox),
                    "out_tail": tail_lines(outlog, 16),
                    "err_tail": tail_lines(errlog, 16),
                    "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "refresh_seconds": self.refresh_seconds,
                }
            )
            return

        self.send_response(404)
        self.end_headers()


def main() -> int:
    ap = argparse.ArgumentParser(description="superharness watcher browser monitor")
    ap.add_argument("--project", required=True, help="project directory containing .superharness")
    ap.add_argument("--port", type=int, default=8787, help="HTTP port (default: 8787)")
    ap.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    ap.add_argument("--refresh-seconds", type=int, default=3, help="ui refresh seconds (default: 3)")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    if not (project_dir / ".superharness").is_dir():
        raise SystemExit(f"Missing .superharness in project: {project_dir}")

    Handler.project_dir = project_dir
    Handler.label = project_label(project_dir)
    Handler.refresh_seconds = args.refresh_seconds

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"monitor ui: http://{args.host}:{args.port}")
    print(f"project: {project_dir}")
    print(f"watcher label: {Handler.label}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
