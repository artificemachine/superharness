#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import shlex
import shutil
import subprocess
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>superharness monitor</title>
  <style>
    :root { --bg:#0b1220; --panel:#131c2e; --text:#e7ecf6; --muted:#9fb0d0; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; --line:#23314d; --btn:#1b2a46; --btn2:#334e7d; }
    body { margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:var(--bg); color:var(--text); }
    .wrap { max-width:100%; margin:12px 0; padding:0 8px; }
    .grid { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px; }
    .k { color:var(--muted); font-size:12px; }
    .v { font-size:13px; margin-top:6px; word-break:break-all; overflow-wrap:anywhere; }
    .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
    h1 { font-size:20px; margin:0 0 12px; }
    h2 { font-size:14px; margin:0 0 8px; color:var(--muted); }
    pre { margin:0; white-space:pre-wrap; word-break:break-word; font-size:12px; line-height:1.3; }
    .logs { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
    .meta { margin:8px 0 12px; color:var(--muted); font-size:12px; }
    .pill { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; margin-right:6px; margin-top:4px; font-size:13px; cursor:pointer; user-select:none; }
    .pill:hover { background:var(--btn); }
    .pill.sel { background:var(--btn2); border-color:#4a6fa5; color:#fff; }
    .inbox-detail { margin-top:10px; overflow-x:auto; }
    .inbox-detail table { width:100%; border-collapse:collapse; font-size:12px; }
    .inbox-detail th { text-align:left; color:var(--muted); border-bottom:1px solid var(--line); padding:4px 8px; }
    .inbox-detail td { padding:4px 8px; border-bottom:1px solid var(--line); word-break:break-all; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
    button { background:var(--btn); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; cursor:pointer; }
    button:hover { background:var(--btn2); }
    .small { font-size:11px; color:var(--muted); }
    .status { margin-top:8px; font-size:12px; color:var(--muted); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>superharness monitor</h1>
    <div class=\"meta\" id=\"meta\">loading...</div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"k\">watcher label</div><div class=\"v\" id=\"label\">-</div></div>
      <div class=\"card\"><div class=\"k\">watcher state</div><div class=\"v\" id=\"state\">-</div></div>
      <div class=\"card\"><div class=\"k\">contract id</div><div class=\"v\" id=\"contract\">-</div></div>
      <div class=\"card\"><div class=\"k\">last refresh (UTC)</div><div class=\"v\" id=\"ts\">-</div></div>
    </div>

    <div class=\"card\" style=\"margin-top:10px;\">
      <h2>inbox status counts</h2>
      <div id=\"counts\"></div>
      <div class=\"inbox-detail\" id=\"inboxDetail\" style=\"display:none\">
        <table><thead><tr><th>id</th><th>task</th><th>to</th><th>priority</th><th>launched_at</th><th>timer</th><th></th></tr></thead>
        <tbody id=\"inboxRows\"></tbody></table>
      </div>
      <div class=\"actions\">
        <button onclick=\"act('dispatch_print_codex')\">Dispatch preview codex</button>
        <button onclick=\"act('dispatch_print_claude')\">Dispatch preview claude</button>
        <button onclick=\"act('recover_retry')\">Recover stale -> retry</button>
        <button onclick=\"act('normalize_stale')\">Normalize stale</button>
      </div>
      <div class=\"status\" id=\"actionStatus\">ready</div>
    </div>

    <div class=\"logs\">
      <div class=\"card\"><h2>ledger tail</h2><pre id=\"ledger\">-</pre></div>
      <div class=\"card\"><h2>action output</h2><pre id=\"actionOut\">-</pre></div>
    </div>

    <div class=\"logs\">
      <div class=\"card\"><h2>watcher out.log tail</h2><pre id=\"out\">-</pre></div>
      <div class=\"card\"><h2>watcher err.log tail</h2><pre id=\"err\">-</pre></div>
    </div>
  </div>
<script>
let lastActionText = '-';
let selectedStatus = null;
const AUTH_TOKEN = __AUTH_TOKEN__;

async function api(path, init) {
  const r = await fetch(path, init);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || ('http ' + r.status));
  return d;
}

async function refresh() {
  try {
    const d = await api('/api/status');
    document.getElementById('meta').textContent = `project: ${d.project} | refresh: ${d.refresh_seconds}s`;
    document.getElementById('label').textContent = d.label;
    const s = document.getElementById('state');
    s.textContent = d.launchctl_state || 'not-loaded';
    s.className = 'v ' + (d.launchctl_state === 'running' ? 'ok' : (d.launchctl_state ? 'warn' : 'bad'));
    document.getElementById('contract').textContent = d.contract_id || '-';
    document.getElementById('ts').textContent = d.now_utc;
    document.getElementById('ledger').textContent = (d.ledger_tail || []).join('\\n');
    document.getElementById('out').textContent = (d.out_tail || []).join('\\n');
    document.getElementById('err').textContent = (d.err_tail || []).join('\\n');
    document.getElementById('actionOut').textContent = lastActionText;

    const counts = document.getElementById('counts');
    counts.innerHTML = '';
    const keys = Object.keys(d.inbox_counts || {}).sort();
    if (!keys.length) { counts.textContent = 'no inbox rows'; selectedStatus = null; }
    for (const k of keys) {
      const el = document.createElement('span');
      el.className = 'pill' + (k === selectedStatus ? ' sel' : '');
      el.textContent = `${k}: ${d.inbox_counts[k]}`;
      el.onclick = () => selectStatus(k);
      counts.appendChild(el);
    }
    if (selectedStatus) await loadInboxDetail(selectedStatus);

  } catch (e) {
    document.getElementById('meta').textContent = 'error: ' + e;
  }
}

async function selectStatus(k) {
  selectedStatus = (selectedStatus === k) ? null : k;
  if (!selectedStatus) {
    document.getElementById('inboxDetail').style.display = 'none';
    document.querySelectorAll('.pill').forEach(p => p.classList.remove('sel'));
    return;
  }
  document.querySelectorAll('.pill').forEach(p => {
    p.classList.toggle('sel', p.textContent.startsWith(k + ':'));
  });
  await loadInboxDetail(selectedStatus);
}

async function loadInboxDetail(status) {
  try {
    const d = await api('/api/inbox?status=' + encodeURIComponent(status));
    const tbody = document.getElementById('inboxRows');
    tbody.innerHTML = '';
    if (!d.items.length) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="7" style="color:var(--muted)">no items</td>';
      tbody.appendChild(tr);
    }
    const now = new Date(d.now_utc);
    for (const item of d.items) {
      let timer = '';
      const la = (item.launched_at || '').replace(/^'|'$/g, '');
      if (la) {
        const diff = Math.max(0, Math.floor((now - new Date(la)) / 1000));
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        const s = diff % 60;
        timer = h > 0 ? `${h}h${m}m` : m > 0 ? `${m}m${s}s` : `${s}s`;
      }
      let btn = '';
      const st = item.status || '';
      const eid = (item.id || '').replace(/'/g, "\\\\'");
      if (st === 'pending') btn = `<button onclick="act('pause_item:${eid}')" style="font-size:11px;padding:2px 6px">Pause</button>`;
      else if (st === 'paused') btn = `<button onclick="act('resume_item:${eid}')" style="font-size:11px;padding:2px 6px">Resume</button>`;
      else if (st === 'launched' || st === 'running') btn = `<button onclick="act('stop_item:${eid}')" style="font-size:11px;padding:2px 6px;color:var(--bad)">Stop</button>`;
      else if (st === 'stale' || st === 'failed' || st === 'stopped') btn = `<button onclick="act('retry_item:${eid}')" style="font-size:11px;padding:2px 6px;color:var(--warn)">Retry</button>`;
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${item.id||''}</td><td>${item.task||''}</td><td>${item.to||''}</td><td>${item.priority||''}</td><td>${la}</td><td>${timer}</td><td>${btn}</td>`;
      tbody.appendChild(tr);
    }
    document.getElementById('inboxDetail').style.display = 'block';
  } catch(e) {}
}

async function act(action) {
  const st = document.getElementById('actionStatus');
  st.textContent = 'running ' + action + ' ...';
  try {
    const d = await api('/api/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Superharness-Token': AUTH_TOKEN},
      body: JSON.stringify({action})
    });
    lastActionText = (d.stdout || '') + (d.stderr ? ('\\n' + d.stderr) : '');
    st.textContent = `ok: ${action} (exit=${d.exit_code})`;
  } catch (e) {
    st.textContent = 'error: ' + e;
  }
  await refresh();
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
            timeout=3,
        )
        if out.returncode != 0:
            return ""
        for ln in out.stdout.splitlines():
            if "state =" in ln:
                return ln.split("=", 1)[1].strip()
    except Exception:
        return ""
    return ""


def inbox_items(inbox_file: Path) -> list[dict]:
    if not inbox_file.exists():
        return []
    items: list[dict] = []
    current: dict = {}
    for raw in inbox_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("- id:"):
            if current:
                items.append(current)
            current = {"id": line[5:].strip()}
        elif ":" in line and current:
            k, _, v = line.partition(":")
            k = k.strip()
            if k and k not in current:
                current[k] = v.strip()
    if current:
        items.append(current)
    return items


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


def contract_id(contract_file: Path) -> str:
    helper = Path(__file__).resolve().parent.parent / "engine" / "contract.rb"
    if not contract_file.exists() or not helper.exists() or shutil.which("ruby") is None:
        return ""
    run = subprocess.run(
        ["ruby", str(helper), "contract_id", "--file", str(contract_file)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if run.returncode != 0:
        return ""
    return run.stdout.strip().strip('"')


def project_label(project_dir: Path) -> str:
    # Match install-launchd-inbox-watcher.sh: basename | tr -cs 'A-Za-z0-9' '-'
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project_dir.name + " ")
    if not slug.strip("-"):
        slug = "project-"
    return f"com.superharness.inbox.{slug}"


class Handler(BaseHTTPRequestHandler):
    project_dir: Path
    label: str
    refresh_seconds: int
    scripts_dir: Path
    auth_token: str

    def _set_common_headers(self, content_type: str, body_len: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(body_len))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._set_common_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.replace("__AUTH_TOKEN__", json.dumps(self.auth_token)).encode("utf-8")
        self.send_response(200)
        self._set_common_headers("text/html; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return

    def _run_cmd(self, args: list[str], timeout: int = 30) -> dict:
        run = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        return {
            "exit_code": run.returncode,
            "stdout": run.stdout.strip(),
            "stderr": run.stderr.strip(),
            "cmd": " ".join(shlex.quote(a) for a in args),
        }

    def _expected_origin(self) -> str:
        return f"http://{self.headers.get('Host', '')}"

    def _verify_mutation_auth(self) -> tuple[dict, int] | None:
        token = self.headers.get("X-Superharness-Token", "")
        if not token or token != self.auth_token:
            return ({"error": "forbidden"}, 403)

        expected_origin = self._expected_origin()
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")

        if origin and origin != expected_origin:
            return ({"error": "forbidden"}, 403)
        if referer and not (referer == expected_origin or referer.startswith(expected_origin + "/")):
            return ({"error": "forbidden"}, 403)

        return None

    def _action(self, action: str) -> tuple[dict, int]:
        dispatch = str(self.scripts_dir / "inbox-dispatch.sh")
        recover = str(self.scripts_dir / "inbox-recover-stale.sh")
        normalize = str(self.scripts_dir / "inbox-normalize.sh")

        if action == "dispatch_print_codex":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "codex-cli", "--print-only"]), 200
        if action == "dispatch_print_claude":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "claude-code", "--print-only"]), 200
        if action == "recover_retry":
            return self._run_cmd(["bash", recover, "--project", str(self.project_dir), "--action", "retry", "--timeout-minutes", "20"]), 200
        if action == "normalize_stale":
            return self._run_cmd(["bash", normalize, "--project", str(self.project_dir), "--archive", "--drop-status", "stale"]), 200

        inbox_rb = str(Path(__file__).resolve().parent.parent / "engine" / "inbox.rb")
        inbox_file = str(self.project_dir / ".superharness" / "inbox.yaml")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if action.startswith("pause_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(["ruby", inbox_rb, "set_status", "--file", inbox_file, "--id", item_id, "--from", "pending", "--to", "paused", "--now", now, "--stamp-key", "paused_at"]), 200
        if action.startswith("resume_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(["ruby", inbox_rb, "set_status", "--file", inbox_file, "--id", item_id, "--from", "paused", "--to", "pending", "--now", now, "--stamp-key", "resumed_at"]), 200
        if action.startswith("retry_item:"):
            item_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("id") == item_id), None)
            if not target:
                return ({"error": f"item not found: {item_id}"}, 404)
            from_status = target.get("status", "")
            if from_status not in ("stale", "failed", "stopped"):
                return ({"error": f"cannot retry from status: {from_status}"}, 400)
            return self._run_cmd(["ruby", inbox_rb, "set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "pending", "--now", now, "--stamp-key", "retried_at"]), 200
        if action.startswith("stop_item:"):
            item_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("id") == item_id), None)
            if not target:
                return ({"error": f"item not found: {item_id}"}, 404)
            pid_str = target.get("pid", "")
            if pid_str:
                try:
                    os.kill(int(pid_str), 15)
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
            from_status = target.get("status", "launched")
            result = self._run_cmd(["ruby", inbox_rb, "set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "stopped", "--now", now, "--stamp-key", "stopped_at"])
            return result, 200

        return ({"error": f"unsupported action: {action}"}, 400)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path
        if p in {"/", "/index.html"}:
            self._html(HTML)
            return

        if p == "/api/status":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            ledger = self.project_dir / ".superharness" / "ledger.md"
            contract = self.project_dir / ".superharness" / "contract.yaml"
            outlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.out.log"
            errlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.err.log"
            self._json(
                {
                    "project": str(self.project_dir),
                    "label": self.label,
                    "launchctl_state": watcher_state(self.label),
                    "contract_id": contract_id(contract),
                    "inbox_counts": inbox_counts(inbox),
                    "ledger_tail": tail_lines(ledger, 18),
                    "out_tail": tail_lines(outlog, 16),
                    "err_tail": tail_lines(errlog, 16),
                    "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "refresh_seconds": self.refresh_seconds,
                }
            )
            return

        if p == "/api/inbox":
            qs = parse_qs(parsed.query)
            status_filter = qs.get("status", [""])[0]
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            items = inbox_items(inbox)
            if status_filter:
                items = [i for i in items if i.get("status") == status_filter]
            self._json({"items": items, "status": status_filter, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path

        if p == "/api/action":
            auth_error = self._verify_mutation_auth()
            if auth_error is not None:
                data, status = auth_error
                self._json(data, status)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
                action = str(payload.get("action", ""))
            except Exception:
                self._json({"error": "invalid request body"}, 400)
                return

            data, status = self._action(action)
            self._json(data, status)
            return

        self._json({"error": "not found"}, 404)


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
    try:
        if not ipaddress.ip_address(args.host).is_loopback:
            raise SystemExit(f"monitor-ui host must be loopback-only, got: {args.host}")
    except ValueError:
        if args.host not in {"localhost"}:
            raise SystemExit(f"monitor-ui host must be loopback-only, got: {args.host}")

    scripts_dir = Path(__file__).resolve().parent
    Handler.project_dir = project_dir
    Handler.label = project_label(project_dir)
    Handler.refresh_seconds = args.refresh_seconds
    Handler.scripts_dir = scripts_dir
    Handler.auth_token = secrets.token_urlsafe(24)

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
