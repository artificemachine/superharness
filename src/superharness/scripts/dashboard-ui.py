#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import secrets
import shlex
import shutil  # noqa: F401 — patched by tests to mock agent CLI detection
import subprocess
import sys
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _ensure_python_with_yaml() -> None:
    """Re-exec into the repo venv if the current interpreter lacks PyYAML."""
    try:
        import yaml  # noqa: F401
        return
    except Exception:
        pass

    if os.environ.get("SUPERHARNESS_MONITOR_REEXEC") == "1":
        return

    repo_root = Path(__file__).resolve().parents[3]
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return

    env = os.environ.copy()
    env["SUPERHARNESS_MONITOR_REEXEC"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>superharness dashboard</title>
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
    .report-scroll { max-height:60vh; overflow-y:scroll; }
    .report-scroll::-webkit-scrollbar { width:8px; }
    .report-scroll::-webkit-scrollbar-track { background:var(--bg); border-radius:4px; }
    .report-scroll::-webkit-scrollbar-thumb { background:var(--btn2); border-radius:4px; }
    .report-scroll::-webkit-scrollbar-thumb:hover { background:#4a6fa5; }
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
    .task-row { display:flex; align-items:flex-start; gap:8px; padding:5px 0; border-bottom:1px solid var(--line); flex-wrap:wrap; }
    .task-actions { display:flex; align-items:flex-start; gap:4px; flex-wrap:wrap; justify-content:flex-start; flex:0 0 auto; }
    .task-meta { display:flex; align-items:center; gap:8px; flex:1 1 280px; min-width:180px; flex-wrap:wrap; }
    button { background:var(--btn); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; cursor:pointer; }
    button:hover { background:var(--btn2); }
    .small { font-size:11px; color:var(--muted); }
    .status { margin-top:8px; font-size:12px; color:var(--muted); }
    .approval-list { margin-top:6px; font-size:12px; line-height:1.4; }
    .approval-list a { color:#93c5fd; text-decoration:none; }
    .approval-list a:hover { text-decoration:underline; }
    .banner { display:none; margin:0 0 10px; padding:10px 12px; border-radius:10px; border:1px solid #7f1d1d; background:#2b1212; color:#fecaca; font-size:13px; line-height:1.4; }
    .banner b { color:#fff; }
    .plan-banner { display:none; margin:0 0 10px; padding:10px 12px; border-radius:10px; border:1px solid #78350f; background:#1c1408; color:#fde68a; font-size:13px; line-height:1.4; }
    .plan-banner b { color:#fff; }
    .plan-list { margin-top:6px; font-size:12px; line-height:1.8; }
    .watcher-health { margin-top:6px; font-size:12px; line-height:1.4; }
    .board { display:grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap:8px; margin-top:10px; }
    .board-col { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px; min-height:80px; }
    .board-col-header { font-size:11px; font-weight:bold; color:var(--muted); margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; }
    .board-col-count { background:var(--btn); border-radius:999px; padding:0 6px; font-size:10px; }
    .board-task { font-size:11px; padding:4px 6px; margin-bottom:4px; background:var(--bg); border:1px solid var(--line); border-radius:6px; cursor:pointer; }
    .board-task:hover { border-color:#4a6fa5; }
    .board-task .bt-id { color:var(--muted); font-size:10px; }
    .board-task .bt-owner { color:var(--muted); font-size:10px; float:right; }
    .review-banner { display:none; margin:0 0 10px; padding:10px 12px; border-radius:10px; border:1px solid #92400e; background:#1c1208; color:#fde68a; font-size:13px; line-height:1.4; }
    .review-banner b { color:#fff; }
    .review-list { margin-top:6px; font-size:12px; line-height:1.8; }
    .agent-health-pills { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
    .agent-pill { display:inline-flex; align-items:center; gap:4px; font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); }
    .live-badge { display:inline-block; font-size:10px; padding:1px 6px; border-radius:999px; background:#ef444422; color:var(--bad); border:1px solid var(--bad); animation:pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
    .view-toggle { display:flex; gap:6px; margin-bottom:8px; align-items:center; }
    .view-btn { font-size:11px; padding:2px 10px; border-radius:6px; cursor:pointer; border:1px solid var(--line); background:var(--btn); color:var(--muted); }
    .view-btn.active { background:var(--btn2); color:#fff; border-color:#4a6fa5; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>superharness dashboard</h1>
    <div class=\"meta\" id=\"meta\">loading...</div>
    <div class=\"banner\" id=\"approvalBanner\" style=\"display:none\">User approval required.</div>
    <div class=\"plan-banner\" id=\"planBanner\" style=\"display:none\">Plan confirmation required.</div>
    <div class=\"review-banner\" id=\"reviewBanner\">
      <b>Review queue</b> — tasks awaiting operator action
      <div class=\"review-list\" id=\"reviewList\"></div>
    </div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"k\">watcher label</div><div class=\"v\" id=\"label\">-</div></div>
      <div class=\"card\"><div class=\"k\">watcher state</div><div class=\"v\" id=\"state\">-</div></div>
      <div class=\"card\"><div class=\"k\">contract id</div><div class=\"v\" id=\"contract\">-</div></div>
      <div class=\"card\"><div class=\"k\">last refresh (UTC)</div><div class=\"v\" id=\"ts\">-</div></div>
    </div>
    <div class=\"card\" style=\"margin-top:10px;\">
      <h2>watcher control</h2>
      <div class=\"watcher-health\" id=\"watcherHealth\">-</div>
      <div class=\"watcher-health\" id=\"heartbeat\">-</div>
      <div class=\"agent-health-pills\" id=\"agentHealthPills\"></div>
      <div class=\"actions\">
        <button onclick=\"act('watcher_start')\">Start watcher</button>
        <button onclick=\"act('watcher_restart')\">Restart watcher</button>
      </div>
    </div>

    <div class=\"card\" style=\"margin-top:10px;display:none;\">
      <h2>plans to confirm</h2>
      <div class=\"v\" id=\"planCount\">-</div>
      <div class=\"plan-list\" id=\"planList\">-</div>
    </div>
    <div class=\"card report-scroll\" style=\"margin-top:10px; display:none;\" id=\"planReportCard\">
      <h2 style=\"position:sticky;top:0;background:var(--panel);padding-bottom:6px;z-index:1;\">plan preview <button onclick=\"document.getElementById('planReportCard').style.display='none'\" style=\"font-size:11px;padding:2px 8px;float:right\">close</button></h2>
      <div class=\"small\" id=\"planReportMeta\" style=\"position:sticky;top:28px;background:var(--panel);padding-bottom:4px;z-index:1;\">-</div>
      <pre id=\"planReportBody\">-</pre>
    </div>

    <div class=\"card\" style=\"margin-top:10px;display:none;\">
      <h2>user approval alerts</h2>
      <div class=\"v\" id=\"approvalCount\">-</div>
      <div class=\"approval-list\" id=\"approvalList\">-</div>
    </div>
    <div class=\"card report-scroll\" style=\"margin-top:10px; display:none;\" id=\"approvalReportCard\">
      <h2 style=\"position:sticky;top:0;background:var(--panel);padding-bottom:6px;z-index:1;\">approval report preview <button onclick=\"document.getElementById('approvalReportCard').style.display='none'\" style=\"font-size:11px;padding:2px 8px;float:right\">close</button></h2>
      <div class=\"small\" id=\"approvalReportMeta\" style=\"position:sticky;top:28px;background:var(--panel);padding-bottom:4px;z-index:1;\">-</div>
      <pre id=\"approvalReportBody\">-</pre>
    </div>

    <div class=\"card report-scroll\" style=\"margin-top:10px; display:none;\" id=\"taskReportCard\">
      <h2 style=\"position:sticky;top:0;background:var(--panel);padding-bottom:6px;z-index:1;\">task report <button onclick=\"document.getElementById('taskReportCard').style.display='none'\" style=\"font-size:11px;padding:2px 8px;float:right\">close</button></h2>
      <div class=\"small\" id=\"taskReportMeta\" style=\"position:sticky;top:28px;background:var(--panel);padding-bottom:4px;z-index:1;\">-</div>
      <pre id=\"taskReportBody\">-</pre>
    </div>

    <div class=\"card report-scroll\" style=\"margin-top:10px; display:none;\" id=\"inboxReasonCard\">
      <h2 style=\"position:sticky;top:0;background:var(--panel);padding-bottom:6px;z-index:1;\">inbox item details <button onclick=\"document.getElementById('inboxReasonCard').style.display='none'\" style=\"font-size:11px;padding:2px 8px;float:right\">close</button></h2>
      <div class=\"small\" id=\"inboxReasonMeta\" style=\"position:sticky;top:28px;background:var(--panel);padding-bottom:4px;z-index:1;\">-</div>
      <pre id=\"inboxReasonBody\" style=\"white-space:pre-wrap;word-break:break-word;\">-</pre>
    </div>

    <div class=\"card\" style=\"margin-top:10px;\">
      <h2>inbox status counts</h2>
      <div id=\"ownerFilter\" style=\"margin-bottom:8px;\"></div>
      <div id=\"counts\"></div>
      <div class=\"inbox-detail\" id=\"inboxDetail\" style=\"display:none\">
        <table><thead><tr><th>id</th><th>task</th><th>to</th><th>priority</th><th>launched_at</th><th>timer</th><th>reason</th><th></th></tr></thead>
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

    <div class=\"card\" style=\"margin-top:10px;\">
      <div style=\"display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;\">
        <h2 style=\"margin:0\">tasks</h2>
        <div class=\"view-toggle\">
          <span class=\"view-btn active\" id=\"listViewBtn\" onclick=\"setView('list')\">☰ list</span>
          <span class=\"view-btn\" id=\"boardViewBtn\" onclick=\"setView('board')\">▦ board</span>
        </div>
      </div>
      <div id=\"taskFilterPills\" style=\"display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;\"></div>
      <div id=\"contractTaskList\">-</div>
    </div>
    <div class=\"card\" style=\"margin-top:10px; display:none;\" id=\"boardViewCard\">
      <h2>board view</h2>
      <div class=\"board\" id=\"boardColumns\"></div>
    </div>

    <div class=\"card\" style=\"margin-top:10px;\">
      <h2>contract owners</h2>
      <div id=\"ownersList\" style=\"margin-bottom:8px;\"></div>
      <div style=\"display:flex;gap:6px;align-items:center;\">
        <input id=\"newOwnerInput\" type=\"text\" placeholder=\"new-agent-name\" style=\"background:var(--btn);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12px;font-family:inherit;\" />
        <button onclick=\"addOwner()\">Add owner</button>
      </div>
      <div class=\"small\" id=\"ownerStatus\" style=\"margin-top:4px;\"></div>
    </div>

    <div class=\"logs\">
      <div class=\"card\"><h2>ledger tail</h2><pre id=\"ledger\">-</pre></div>
      <div class=\"card\"><h2>action output</h2><pre id=\"actionOut\">-</pre></div>
    </div>

    <div class=\"logs\">
      <div class=\"card\"><h2>watcher out.log tail</h2><pre id=\"out\">-</pre></div>
      <div class=\"card\"><h2>watcher err.log tail</h2><pre id=\"err\">-</pre></div>
    </div>

    <div class=\"logs\">
      <div class=\"card\" style=\"flex:1;\">
        <h2>dispatch cost leaderboard <span id=\"costSummary\" style=\"font-weight:normal;font-size:0.85em;\"></span></h2>
        <table id=\"costTable\" style=\"width:100%;border-collapse:collapse;font-size:0.85em;\">
          <thead><tr style=\"text-align:left;\">
            <th style=\"padding:2px 6px;\">task</th>
            <th style=\"padding:2px 6px;text-align:right;\">cost $</th>
            <th style=\"padding:2px 6px;text-align:right;\">tokens</th>
            <th style=\"padding:2px 6px;text-align:right;\">runs</th>
            <th style=\"padding:2px 6px;text-align:right;\">avg s</th>
          </tr></thead>
          <tbody id=\"costRows\"><tr><td colspan=\"5\">-</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>
<script>
let lastActionText = '-';
let selectedStatus = null;
let selectedOwners = new Set();
let knownOwners = [];
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
    const hb = d.heartbeat || {};
    const wh = d.watcher_health || {};
    // Reconcile: if heartbeat is OK but launchd says not-loaded, watcher is in foreground mode
    const heartbeatOk = hb.level === 'ok';
    const launchdLoaded = d.launchctl_state === 'running' || d.launchctl_state === 'loaded';
    if (heartbeatOk && !launchdLoaded) {
      s.textContent = 'foreground';
      s.className = 'v ok';
    } else {
      s.textContent = d.launchctl_state || 'not-loaded';
      s.className = 'v ' + (launchdLoaded ? 'ok' : (d.launchctl_state ? 'warn' : 'bad'));
    }
    const whEl = document.getElementById('watcherHealth');
    if (heartbeatOk && wh.level === 'bad') {
      whEl.textContent = 'Watcher running in foreground mode (heartbeat active).';
      whEl.className = 'watcher-health ok';
    } else {
      whEl.textContent = wh.message || 'watcher health unavailable';
      whEl.className = 'watcher-health ' + (wh.level === 'ok' ? 'ok' : (wh.level === 'warn' ? 'warn' : 'bad'));
    }
    const hbEl = document.getElementById('heartbeat');
    hbEl.textContent = hb.message || 'no data';
    hbEl.className = 'v ' + (hb.level === 'ok' ? 'ok' : (hb.level === 'warn' ? 'warn' : 'bad'));
    document.getElementById('contract').textContent = d.contract_id || '-';
    document.getElementById('ts').textContent = d.now_utc;
    renderOwnersList(d.contract_owners || []);
    renderContractTasks(d.contract_tasks || [], new Set(d.active_inbox_tasks || []), new Set(d.done_inbox_tasks || []));
    // Review queue banner
    const reviewTasks = (d.contract_tasks || []).filter(t => ['review_requested','review_passed','review_failed'].includes(t.status));
    renderReviewQueue(d.review_queue_count || 0, reviewTasks);
    // Agent health pills (list view)
    renderAgentHealthPills((d.agent_status||{}).agents||{});
    // Refresh board if active
    if (_currentView === 'board') loadBoardView();
    document.getElementById('ledger').textContent = (d.ledger_tail || []).join('\\n');
    document.getElementById('out').textContent = (d.out_tail || []).join('\\n');
    document.getElementById('err').textContent = (d.err_tail || []).join('\\n');
    document.getElementById('actionOut').textContent = lastActionText;

    // Owner filter checkboxes
    const ownerDiv = document.getElementById('ownerFilter');
    const owners = Object.keys(d.inbox_owners || {}).sort();
    if (owners.length && (knownOwners.join() !== owners.join())) {
      knownOwners = owners;
      rebuildOwnerCheckboxes();
    }

    // Inbox status counts (filtered by owner if active)
    const counts = document.getElementById('counts');
    counts.innerHTML = '';
    let filteredCounts = d.inbox_counts || {};
    if (selectedOwners.size > 0) {
      // Recompute counts from owner-filtered items
      filteredCounts = {};
      const ownerParams = [...selectedOwners].map(o => 'owner=' + encodeURIComponent(o)).join('&');
      try {
        const allFiltered = await api('/api/inbox?' + ownerParams);
        for (const item of allFiltered.items) {
          const st = item.status || '';
          filteredCounts[st] = (filteredCounts[st] || 0) + 1;
        }
      } catch(e) {}
    }
    const keys = Object.keys(filteredCounts).sort();
    if (!keys.length) { counts.textContent = 'no inbox rows'; selectedStatus = null; }
    for (const k of keys) {
      const el = document.createElement('span');
      el.className = 'pill' + (k === selectedStatus ? ' sel' : '');
      el.textContent = `${k}: ${filteredCounts[k]}`;
      el.onclick = () => selectStatus(k);
      counts.appendChild(el);
    }
    if (selectedStatus) await loadInboxDetail(selectedStatus);

  } catch (e) {
    document.getElementById('meta').textContent = 'error: ' + e;
  }
}

function rebuildOwnerCheckboxes() {
  const ownerDiv = document.getElementById('ownerFilter');
  ownerDiv.innerHTML = '<span class=\"k\">filter by owner:</span> ';
  for (const o of knownOwners) {
    const lbl = document.createElement('label');
    lbl.style.cssText = 'margin-right:12px;cursor:pointer;font-size:13px;';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = selectedOwners.size === 0 || selectedOwners.has(o);
    cb.style.cssText = 'margin-right:4px;cursor:pointer;accent-color:var(--ok);';
    cb.onchange = () => { toggleOwner(o, cb.checked); };
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(o));
    ownerDiv.appendChild(lbl);
  }
}

function toggleOwner(owner, checked) {
  if (checked) {
    selectedOwners.add(owner);
    // If all are checked, clear the filter (show all)
    if (selectedOwners.size >= knownOwners.length) selectedOwners.clear();
  } else {
    // If filter was empty (all shown), populate with all except unchecked
    if (selectedOwners.size === 0) {
      for (const o of knownOwners) { if (o !== owner) selectedOwners.add(o); }
    } else {
      selectedOwners.delete(owner);
      if (selectedOwners.size === 0) selectedOwners.clear();
    }
  }
  rebuildOwnerCheckboxes();
  refresh();
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
    let url = '/api/inbox?status=' + encodeURIComponent(status);
    if (selectedOwners.size > 0) {
      url += '&' + [...selectedOwners].map(o => 'owner=' + encodeURIComponent(o)).join('&');
    }
    const d = await api(url);
    const tbody = document.getElementById('inboxRows');
    tbody.innerHTML = '';
    if (!d.items.length) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="8" style="color:var(--muted)">no items</td>';
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
      const removeBtn = `<button onclick="removeItem('${eid}')" style="font-size:11px;padding:2px 6px;color:var(--bad)">Remove</button>`;
      const taskEsc = (item.task||'').replace(/'/g, "\\\\'");
      const agentEsc = (item.to||'').replace(/'/g, "\\\\'");
      const viewBtn = `<button onclick="viewTaskReport('${taskEsc}','${agentEsc}')" style="font-size:11px;padding:2px 6px">View</button>`;
      const actionCell = `${viewBtn} ${btn ? btn + ' ' : ''}${removeBtn}`;
      const tr = document.createElement('tr');
      const reason = item.pause_reason || item.failed_reason || item.stale_reason || item.stopped_reason || '';
      const itemJson = JSON.stringify(item).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
      const reasonText = reason.replace(/_/g, ' ');
      const reasonCell = reason ? `<span style="color:var(--warn);font-size:11px;cursor:pointer;text-decoration:underline dotted" title="Click for details" onclick="showInboxReason(JSON.parse(this.closest('tr').dataset.item))">${reasonText.length > 40 ? reasonText.slice(0,40) + '…' : reasonText}</span>` : (st !== 'done' ? `<span style="color:var(--muted);font-size:11px;cursor:pointer" onclick="showInboxReason(JSON.parse(this.closest('tr').dataset.item))">details</span>` : '');
      tr.dataset.item = JSON.stringify(item);
      tr.innerHTML = `<td>${item.id||''}</td><td>${item.task||''}</td><td>${item.to||''}</td><td>${item.priority||''}</td><td>${la}</td><td>${timer}</td><td>${reasonCell}</td><td>${actionCell}</td>`;
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

let _liveLogInterval = null;

async function viewTaskReport(taskId, agent) {
  const card = document.getElementById('taskReportCard');
  const meta = document.getElementById('taskReportMeta');
  const body = document.getElementById('taskReportBody');
  meta.textContent = `Loading report for task=${taskId} agent=${agent}...`;
  body.textContent = '...';
  card.style.display = 'block';
  if (_liveLogInterval) { clearInterval(_liveLogInterval); _liveLogInterval = null; }
  try {
    const d = await api('/api/task-report?task=' + encodeURIComponent(taskId) + '&agent=' + encodeURIComponent(agent));
    const _liveStatuses = new Set(['in_progress','todo','plan_approved','report_ready','review_requested']);
    const isActive = _liveStatuses.has(d.contract_status);
    if (isActive) {
      try {
        const logData = await api('/api/task-log?task=' + encodeURIComponent(taskId) + '&lines=100');
        if (logData.log && !logData.log.startsWith('(no log')) {
          const sdkBadge = logData.sdk_status ? ` &nbsp; <span style="color:var(--warn)">${logData.sdk_status}</span>` : '';
          meta.innerHTML = `task=${taskId} &nbsp; agent=${agent} &nbsp; <span class="live-badge">LIVE ●</span> auto-refreshing${sdkBadge}`;
          body.textContent = logData.log;
          body.scrollTop = body.scrollHeight;
          _liveLogInterval = setInterval(async () => {
            try {
              const fresh = await api('/api/task-log?task=' + encodeURIComponent(taskId) + '&lines=100');
              if (fresh.log) { body.textContent = fresh.log; body.scrollTop = body.scrollHeight; }
              const freshBadge = fresh.sdk_status ? ` &nbsp; <span style="color:var(--warn)">${fresh.sdk_status}</span>` : '';
              meta.innerHTML = `task=${taskId} &nbsp; agent=${agent} &nbsp; <span class="live-badge">LIVE ●</span> auto-refreshing${freshBadge}`;
            } catch(e) {}
          }, 3000);
          return;
        }
      } catch(e) {}
    }
    meta.textContent = `task=${taskId}  agent=${agent}  status=${d.contract_status || '-'}`;
    let report = '';

    // ── Contract Task ─────────────────────────────────────────────────────────
    if (d.contract_status) {
      report += '═══ CONTRACT TASK ═══════════════════════════════════════════\\n';
      report += 'ID:      ' + taskId + '\\n';
      if (d.contract_title)  report += 'Title:   ' + d.contract_title + '\\n';
      if (d.contract_owner)  report += 'Owner:   ' + d.contract_owner + '\\n';
      report += 'Status:  ' + d.contract_status + '\\n';
      if (d.dispatch_model)
        report += 'Model:   ' + d.dispatch_model +
                  (d.dispatch_effort ? '  (effort: ' + d.dispatch_effort + ')' : '') +
                  (d.dispatch_via    ? '  via ' + d.dispatch_via : '') + '\\n';
      if (d.blocked_by && d.blocked_by !== 'none' && d.blocked_by !== '')
        report += 'Blocked: ' + d.blocked_by + '\\n';
      if (d.verified != null)
        report += 'Verified: ' + (d.verified ? '✓ yes' : '✗ no') +
                  (d.verified_by ? ' by ' + d.verified_by : '') +
                  (d.verified_at ? ' at ' + d.verified_at : '') + '\\n';
      if (d.tests_passed != null)
        report += 'Tests passed: ' + (d.tests_passed ? '✓ yes' : '✗ no') + '\\n';

      // Timestamps
      const tsKeys = ['todo_at','plan_proposed_at','plan_approved_at','in_progress_at','report_ready_at','done_at','stopped_at'];
      const tsLabels = {'todo_at':'Todo','plan_proposed_at':'Plan proposed','plan_approved_at':'Plan approved',
                        'in_progress_at':'In progress','report_ready_at':'Report ready','done_at':'Done','stopped_at':'Stopped'};
      const tsParts = tsKeys.filter(k => d[k]).map(k => tsLabels[k] + ': ' + d[k]);
      if (tsParts.length) report += '\\nTimeline:\\n' + tsParts.map(s => '  ' + s).join('\\n') + '\\n';

      // Acceptance criteria
      if (d.acceptance_criteria && d.acceptance_criteria.length) {
        report += '\\nAcceptance Criteria:\\n';
        d.acceptance_criteria.forEach(c => { report += '  ✦ ' + c + '\\n'; });
      }

      // Test types
      if (d.test_types && d.test_types.length)
        report += '\\nTest Types: ' + d.test_types.join(', ') + '\\n';

      // TDD block
      if (d.tdd && Object.keys(d.tdd).length) {
        report += '\\nTDD:\\n';
        if (d.tdd.red)     report += '  RED:     ' + String(d.tdd.red).replace(/\\n/g,'\\n           ') + '\\n';
        if (d.tdd.green)   report += '  GREEN:   ' + String(d.tdd.green).replace(/\\n/g,'\\n           ') + '\\n';
        if (d.tdd.refactor)report += '  REFACTOR:' + String(d.tdd.refactor).replace(/\\n/g,'\\n           ') + '\\n';
      }

      // Outcomes
      if (d.outcomes && d.outcomes.length) {
        report += '\\nOutcomes:\\n';
        d.outcomes.forEach(o => { report += '  • ' + o + '\\n'; });
      }

      // Summary
      if (d.contract_summary) report += '\\nSummary: ' + d.contract_summary + '\\n';

      report += '\\n';
    }

    // ── Discussion ────────────────────────────────────────────────────────────
    if (d.discussion_topic) {
      report += '═══ DISCUSSION ══════════════════════════════════════════════\\n';
      report += 'Topic:  ' + d.discussion_topic + '\\n';
      report += 'Status: ' + (d.discussion_status||'-') + '\\n';
      report += 'Round:  ' + (d.discussion_round||'?') + '/' + (d.discussion_max_rounds||'?') + '\\n\\n';
    }

    // ── Handoff / Report ──────────────────────────────────────────────────────
    if (d.handoff_outcome || d.handoff_context || d.handoff_summary || d.markdown_report) {
      report += '═══ HANDOFF REPORT' + (d.handoff_date ? ' (' + d.handoff_date + ')' : '') + ' ════════════════════════\\n';
      if (d.handoff_outcome)  report += '\\nOutcome:\\n' + d.handoff_outcome + '\\n';
      if (d.handoff_context)  report += '\\nContext (for next session):\\n' + d.handoff_context + '\\n';
      if (d.handoff_summary)  report += '\\nSummary: ' + d.handoff_summary + '\\n';
      if (d.markdown_report)  report += '\\n' + d.markdown_report + '\\n';
    }

    if (d.discussion_position) report += '\\n═══ DISCUSSION POSITION (' + (d.discussion_agent||agent) + ') ═══════════════\\n' + d.discussion_position + '\\n';
    if (d.discussion_verdict)  report += 'Verdict: ' + d.discussion_verdict + '\\n';

    if (!report) report = '(no report data found for this task)';
    body.textContent = report;
  } catch (e) {
    body.textContent = 'Error: ' + e;
  }
}

async function removeItem(itemId) {
  const ok = window.confirm(`Remove task item ${itemId} from inbox?`);
  if (!ok) return;
  await act('remove_item:' + itemId);
}

const PHASE_LABEL = {
  todo:             ['⬜', 'todo',             'muted'],
  plan_proposed:    ['📋', 'plan proposed',    'warn'],
  plan_approved:    ['✅', 'plan approved',    'ok'],
  in_progress:      ['🔄', 'in progress',      'warn'],
  report_ready:     ['📝', 'report ready',     'warn'],
  review_requested: ['🔍', 'review requested', 'warn'],
  review_passed:    ['✅', 'review passed',    'ok'],
  review_failed:    ['❌', 'review failed',    'bad'],
  done:             ['✅', 'done',             'ok'],
  failed:           ['❌', 'failed',           'bad'],
  stopped:          ['⏹',  'stopped',          'muted'],
};

// Status filter pills — maps status group → list of statuses it covers
const STATUS_GROUPS = [
  { key: 'done',           label: '✅ done',           statuses: ['done'],                          color: 'var(--ok)' },
  { key: 'stopped',        label: '⛔ disabled',        statuses: ['stopped'],                       color: 'var(--muted)' },
  { key: 'review',         label: '🔍 review',          statuses: ['review_requested','review_passed','review_failed'], color: 'var(--warn)' },
  { key: 'in_progress',    label: '🔄 in progress',     statuses: ['in_progress','launched','running'], color: '#4a9eff' },
  { key: 'plan',           label: '📋 plan',            statuses: ['plan_proposed','plan_approved'], color: '#a78bfa' },
  { key: 'todo',           label: '🕐 todo',            statuses: ['todo'],                          color: 'var(--muted)' },
];
// hidden groups — set of group keys currently hidden; done is hidden by default
const _hiddenGroups = new Set(['done']);

function _statusToGroup(st) {
  for (const g of STATUS_GROUPS) {
    if (g.statuses.includes(st)) return g.key;
  }
  return 'todo';
}

function renderTaskFilterPills(tasks) {
  const el = document.getElementById('taskFilterPills');
  if (!el) return;
  // Count per group
  const counts = {};
  for (const t of tasks) {
    const gk = _statusToGroup(t.status || 'todo');
    counts[gk] = (counts[gk] || 0) + 1;
  }
  el.innerHTML = '';
  for (const g of STATUS_GROUPS) {
    const n = counts[g.key] || 0;
    if (n === 0) continue;
    const hidden = _hiddenGroups.has(g.key);
    const pill = document.createElement('span');
    pill.title = hidden ? `Show ${g.key}` : `Hide ${g.key}`;
    pill.style.cssText = `cursor:pointer;font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid ${g.color};color:${hidden ? 'var(--muted)' : g.color};background:${hidden ? 'transparent' : g.color+'22'};text-decoration:${hidden ? 'line-through' : 'none'};user-select:none`;
    pill.textContent = `${g.label} ${n}`;
    pill.onclick = () => {
      if (_hiddenGroups.has(g.key)) _hiddenGroups.delete(g.key);
      else _hiddenGroups.add(g.key);
      refresh();
    };
    el.appendChild(pill);
  }
}

function inferredWorkflow(task) {
  if (task.workflow) return task.workflow;
  const taskId = task.id || '';
  if (taskId.startsWith('discuss-') && taskId.includes('/round-')) return 'discussion';
  return 'quick';
}

function canEnqueueTask(task) {
  const st = task.status || 'todo';
  const workflow = inferredWorkflow(task);
  if (workflow === 'implementation') return ['plan_approved', 'failed', 'stopped'].includes(st);
  if (workflow === 'quick' || workflow === 'note') return ['todo', 'in_progress', 'failed', 'stopped'].includes(st);
  return false;
}

function renderContractTasks(tasks, activeInboxTasks, doneInboxTasks) {
  const el = document.getElementById('contractTaskList');
  if (!tasks.length) { el.textContent = '(no tasks)'; return; }
  el.innerHTML = '';
  const sorted = [...tasks].reverse();
  renderTaskFilterPills(sorted);
  const visible = _hiddenGroups.size === 0 ? sorted : sorted.filter(t => !_hiddenGroups.has(_statusToGroup(t.status || 'todo')));
  if (!visible.length) { el.textContent = '(no tasks match current filters)'; return; }
  for (const t of visible) {
    const st = t.status || 'todo';
    const [icon, label, cls] = PHASE_LABEL[st] || ['?', st, 'muted'];
    const row = document.createElement('div');
    row.className = 'task-row';

    const badge = `<span class="pill ${cls}" style="font-size:11px">${icon} ${label}</span>`;
    const schedInfo = t.scheduled_after ? ` <span class="small" style="color:var(--warn)">⏳ after ${t.scheduled_after}</span>` : '';
    const dueInfo = t.due_by ? ` <span class="small" style="color:${new Date(t.due_by) < new Date() ? 'var(--bad)' : 'var(--muted)'}">📅 due ${t.due_by}</span>` : '';
    const depsInfo = (t.depends_on && t.depends_on.length) ? ` <span class="small" style="color:var(--muted)">🔗 ${t.depends_on.join(', ')}</span>` : '';
    const reviewerInfo = (st === 'review_requested' && t.review_target) ? ` <span class="small" style="color:var(--warn)">👀 reviewer ${t.review_target}</span>` : '';
    const title = `<span style="flex:1;min-width:120px">${t.id} <span class="small" style="color:var(--muted)">${t.title}</span>${schedInfo}${dueInfo}${depsInfo}</span>`;
    const owner = `<span class="small" style="color:var(--muted)">${t.owner}</span>`;

    const actionButtons = [];
    const tid = t.id.replace(/'/g, "\\\\'");
    const ownerEsc = (t.owner || '').replace(/'/g, "\\\\'");
    // View Report button for any task with a handoff or in report_ready/done status
    const viewReportBtn = `<button onclick="viewTaskReport('${tid}','${ownerEsc}')" style="font-size:11px;padding:2px 8px">View Report</button>`;
    actionButtons.push(viewReportBtn);
    const isEnqueued = activeInboxTasks.has(t.id);
    const isDoneInbox = doneInboxTasks.has(t.id);
    const canEnqueue = canEnqueueTask(t);
    if (canEnqueue && isDoneInbox && !isEnqueued) {
      actionButtons.push(`<button onclick="markTaskDone('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--ok)">Done</button>`);
    }
    if (st === 'plan_proposed') {
      actionButtons.push(`<button onclick="approvePlan('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--ok)">Approve Plan</button>`);
    } else if (st === 'report_ready') {
      const isVerifyTask = tid.startsWith('verify.');
      if (isVerifyTask) {
        // Verify tasks are self-verifying — close is the primary action
        actionButtons.push(`<button onclick="approveReport('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--ok)">Close Without Review</button>`);
        actionButtons.push(`<button onclick="requestReview('${tid}')" style="font-size:10px;padding:1px 6px;color:var(--muted);opacity:0.7" title="Request meta-review of this verification">Request Review</button>`);
      } else {
        actionButtons.push(`<button onclick="requestReview('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--warn)">Request Review</button>`);
        if (t.verified) {
          actionButtons.push(`<button onclick="approveReport('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--muted)">Close Without Review</button>`);
        } else {
          actionButtons.push(`<button disabled title="Run verify before closing" style="font-size:11px;padding:2px 8px;opacity:0.45;cursor:not-allowed">Verify First</button>`);
        }
      }
    } else if (st === 'review_requested') {
      actionButtons.push(`<button onclick="cancelReview('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--muted)">Cancel Review</button>`);
      actionButtons.push(`<button onclick="approveWithoutReview('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--ok)">Approve Without Review</button>`);
    } else if (st === 'review_failed') {
      actionButtons.push(`<span class="small" style="color:var(--bad)">↩ review failed</span>`);
      actionButtons.push(`<button onclick="enqueueTask('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--warn)">Re-enqueue</button>`);
    } else if (st === 'review_passed') {
      actionButtons.push(`<button onclick="runClose('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--ok)">Close</button>`);
    }
    if (st === 'stopped') {
      actionButtons.push(`<button onclick="enableTask('${tid}')" style="font-size:11px;padding:2px 8px;color:var(--warn)">Re-queue</button>`);
    } else if (st !== 'done' && isEnqueued) {
      actionButtons.push(`<span class="pill" style="font-size:10px;background:var(--ok);color:#000;padding:1px 6px;cursor:default">queued</span>`);
    } else if (st !== 'done' && canEnqueue) {
      actionButtons.push(`<button onclick="enqueueTask('${tid}')" style="font-size:10px;padding:1px 6px;background:var(--muted);color:#fff;border-radius:10px">not queued</button>`);
    }
    actionButtons.push(`<button onclick="removeTask('${tid}')" style="font-size:11px;padding:2px 6px;color:var(--bad)">Remove</button>`);
    row.innerHTML = `<div class="task-actions">${actionButtons.join(' ')}</div><div class="task-meta">${badge}${title}${reviewerInfo}${owner}</div>`;
    el.appendChild(row);
  }
}

async function disableTask(taskId) {
  if (!window.confirm(`Disable task "${taskId}"? It will be set to stopped and hidden with done tasks.`)) return;
  await act('disable_task:' + taskId);
}
async function enableTask(taskId) {
  await act('enable_task:' + taskId);
}
async function removeTask(taskId) {
  if (!window.confirm(`Remove task "${taskId}" from contract? This cannot be undone.`)) return;
  await act('remove_task:' + taskId);
}

async function approvePlan(taskId) {
  if (!window.confirm(`Approve plan for task "${taskId}"? The agent will proceed to implement.`)) return;
  await act('approve_plan:' + taskId);
}

async function requestReview(taskId) {
  const dlg = document.createElement('dialog');
  dlg.style.cssText = 'background:var(--panel);color:var(--fg);border:1px solid var(--border);border-radius:8px;padding:20px;min-width:280px;';
  dlg.innerHTML = `
    <h3 style="margin:0 0 12px">Request review for "${taskId}"</h3>
    <label style="display:block;margin-bottom:8px;font-size:13px;">Reviewer:</label>
    <select id="reviewerSelect" style="width:100%;padding:6px 8px;font-size:14px;background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:4px;">
      <option value="codex-cli">codex-cli</option>
      <option value="claude-code">claude-code</option>
    </select>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
      <button id="reviewCancel" style="padding:6px 16px;font-size:13px;">Cancel</button>
      <button id="reviewConfirm" style="padding:6px 16px;font-size:13px;background:var(--ok);color:#000;border-radius:4px;">Request</button>
    </div>`;
  document.body.appendChild(dlg);
  dlg.showModal();
  const result = await new Promise(resolve => {
    dlg.querySelector('#reviewConfirm').onclick = () => resolve(dlg.querySelector('#reviewerSelect').value);
    dlg.querySelector('#reviewCancel').onclick = () => resolve(null);
    dlg.addEventListener('close', () => resolve(null));
  });
  dlg.remove();
  if (!result) return;
  await act('request_review:' + taskId + ':' + result);
}

async function approveReport(taskId) {
  if (!window.confirm(`Close task "${taskId}" without requesting review?`)) return;
  await act('approve_report:' + taskId);
}

async function cancelReview(taskId) {
  if (!window.confirm(`Cancel review for "${taskId}"? Task will return to report_ready.`)) return;
  await act('cancel_review:' + taskId);
}

function humanize(s) { return (s || '').replace(/_/g, ' '); }

function showInboxReason(item) {
  const card = document.getElementById('inboxReasonCard');
  const meta = document.getElementById('inboxReasonMeta');
  const body = document.getElementById('inboxReasonBody');
  const reason = humanize(item.pause_reason || item.failed_reason || item.stale_reason || item.stopped_reason || '(no reason recorded)');
  const status = item.status || '?';
  const statusColors = { paused: 'var(--warn)', failed: 'var(--bad)', stale: 'var(--warn)', stopped: 'var(--muted)' };
  const color = statusColors[status] || 'var(--fg)';
  meta.innerHTML = `<span style="color:${color};font-weight:bold">${status}</span> &middot; task: ${item.task || '-'} &middot; to: ${item.to || '-'} &middot; id: <span class="small">${item.id || '-'}</span>`;
  const lines = [];
  lines.push(`Status:    ${status}`);
  lines.push(`Reason:    ${reason}`);
  lines.push('');
  lines.push(`Task:      ${item.task || '-'}`);
  lines.push(`Agent:     ${item.to || '-'}`);
  lines.push(`Priority:  ${item.priority || '-'}`);
  lines.push(`Retries:   ${item.retry_count || 0} / ${item.max_retries || 3}`);
  lines.push('');
  if (item.created_at) lines.push(`Created:   ${item.created_at}`);
  if (item.launched_at) lines.push(`Launched:  ${item.launched_at}`);
  if (item.paused_at) lines.push(`Paused:    ${item.paused_at}`);
  if (item.failed_at) lines.push(`Failed:    ${item.failed_at}`);
  if (item.stale_at) lines.push(`Stale:     ${item.stale_at}`);
  if (item.stopped_at) lines.push(`Stopped:   ${item.stopped_at}`);
  if (item.done_at) lines.push(`Done:      ${item.done_at}`);
  body.textContent = lines.join('\\n');
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function approveWithoutReview(taskId) {
  if (!window.confirm(`Approve "${taskId}" without agent review and close it?`)) return;
  await act('approve_without_review:' + taskId);
}

async function runClose(taskId) {
  if (!window.confirm(`Close task "${taskId}"? This will run shux close.`)) return;
  await act('close_task:' + taskId);
}

async function enqueueTask(taskId) {
  const modal = document.getElementById('enqueueModal');
  const titleEl = document.getElementById('enqueueModalTitle');
  const targetEl = document.getElementById('enqueueTarget');
  const instrEl = document.getElementById('enqueueInstructions');
  titleEl.textContent = `Enqueue: ${taskId}`;
  targetEl.value = 'claude-code';
  instrEl.value = 'Loading task instructions...';
  modal.dataset.taskId = taskId;
  modal.style.display = 'block';
  try {
    const d = await api('/api/task-instructions?task=' + encodeURIComponent(taskId));
    instrEl.value = d.instructions || '(no plan found for this task)';
  } catch (e) {
    instrEl.value = `Task: ${taskId}\n\n` +
      `1. Read the task details from the contract and handoffs\n` +
      `2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation\n` +
      `3. Implement only after user approves the plan\n` +
      `4. Run tests after each phase — all tests must pass before marking done`;
  }
}

async function submitEnqueue() {
  const modal = document.getElementById('enqueueModal');
  const taskId = modal.dataset.taskId;
  const target = document.getElementById('enqueueTarget').value;
  const instructions = document.getElementById('enqueueInstructions').value.trim();
  modal.style.display = 'none';
  if (!target || (target !== 'claude-code' && target !== 'codex-cli')) {
    alert('Invalid target. Must be claude-code or codex-cli.');
    return;
  }
  const st = document.getElementById('actionStatus');
  st.textContent = 'enqueueing ' + taskId + ' ...';
  try {
    const d = await api('/api/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Superharness-Token': AUTH_TOKEN},
      body: JSON.stringify({action: 'enqueue_task:' + taskId + ':' + target, instructions})
    });
    st.textContent = `enqueued ${taskId} → ${target}`;
  } catch (e) {
    const msg = String(e);
    if (msg.includes('already enqueued')) {
      alert(`Task "${taskId}" is already in the inbox.`);
    }
    st.textContent = 'error: ' + msg;
  }
  await refresh();
}

function cancelEnqueue() {
  document.getElementById('enqueueModal').style.display = 'none';
}

async function markTaskDone(taskId) {
  if (!window.confirm(`Mark task "${taskId}" as done?`)) return;
  await act('mark_done:' + taskId);
}

function renderOwnersList(owners) {
  const el = document.getElementById('ownersList');
  if (!owners || !owners.length) { el.textContent = '(no owners)'; return; }
  el.innerHTML = '';
  for (const o of owners) {
    const pill = document.createElement('span');
    pill.className = 'pill sel';
    pill.innerHTML = o + (owners.length > 2 ? ' <span style="cursor:pointer;margin-left:4px;color:var(--bad)" onclick="removeOwner(\\'' + o.replace(/'/g, "\\\\'") + '\\')">×</span>' : '');
    el.appendChild(pill);
  }
}

async function addOwner() {
  const input = document.getElementById('newOwnerInput');
  const name = input.value.trim();
  if (!name) return;
  const st = document.getElementById('ownerStatus');
  st.textContent = 'adding ' + name + '...';
  try {
    const d = await api('/api/owners', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Superharness-Token': AUTH_TOKEN},
      body: JSON.stringify({action: 'add', owner: name})
    });
    input.value = '';
    st.textContent = d.note || 'added';
    renderOwnersList(d.owners || []);
    await refresh();
  } catch (e) {
    st.textContent = 'error: ' + e;
  }
}

async function removeOwner(name) {
  if (!window.confirm(`Remove owner "${name}" from contract? This removes all their tasks.`)) return;
  const st = document.getElementById('ownerStatus');
  st.textContent = 'removing ' + name + '...';
  try {
    const d = await api('/api/owners', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Superharness-Token': AUTH_TOKEN},
      body: JSON.stringify({action: 'remove', owner: name})
    });
    st.textContent = 'removed';
    renderOwnersList(d.owners || []);
    await refresh();
  } catch (e) {
    st.textContent = 'error: ' + e;
  }
}

let _currentView = 'list';

function setView(v) {
  _currentView = v;
  document.getElementById('listViewBtn').className = 'view-btn' + (v==='list' ? ' active' : '');
  document.getElementById('boardViewBtn').className = 'view-btn' + (v==='board' ? ' active' : '');
  document.getElementById('contractTaskList').style.display = v === 'list' ? '' : 'none';
  document.getElementById('taskFilterPills').style.display = v === 'list' ? '' : 'none';
  document.getElementById('boardViewCard').style.display = v === 'board' ? '' : 'none';
  if (v === 'board') loadBoardView();
}

const BOARD_COL_LABELS = {
  todo: {label:'⬜ todo', color:'var(--muted)'},
  plan: {label:'📋 plan', color:'#a78bfa'},
  in_progress: {label:'🔄 in progress', color:'#4a9eff'},
  review: {label:'🔍 review', color:'var(--warn)'},
  done: {label:'✅ done', color:'var(--ok)'},
};

async function loadBoardView() {
  const el = document.getElementById('boardColumns');
  if (!el) return;
  try {
    const d = await api('/api/board');
    el.innerHTML = '';
    for (const [col, meta] of Object.entries(BOARD_COL_LABELS)) {
      const tasks = (d.columns || {})[col] || [];
      const div = document.createElement('div');
      div.className = 'board-col';
      const header = `<div class="board-col-header"><span style="color:${meta.color}">${meta.label}</span><span class="board-col-count">${tasks.length}</span></div>`;
      let rows = '';
      for (const t of tasks) {
        const st = t.status || '';
        const [icon] = PHASE_LABEL[st] || ['?'];
        const eid = (t.id || '').replace(/'/g, "\\'");
        rows += `<div class="board-task" onclick="viewTaskReport('${eid}','${(t.owner||'').replace(/'/g,"\\'")}')">
          <div class="bt-owner">${t.owner||''}</div>
          <div class="bt-id">${icon} ${t.id||''}</div>
          <div style="font-size:11px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${t.title||''}</div>
        </div>`;
      }
      div.innerHTML = header + (rows || '<div style="color:var(--muted);font-size:11px;text-align:center;padding:8px">empty</div>');
      el.appendChild(div);
    }
    renderAgentHealthPills((d.agent_status||{}).agents||{});
  } catch(e) {
    el.textContent = 'Error loading board: ' + e;
  }
}

function renderAgentHealthPills(agents) {
  const el = document.getElementById('agentHealthPills');
  if (!el) return;
  el.innerHTML = '';
  for (const [agent, info] of Object.entries(agents)) {
    const lvl = (info.level || 'warn');
    const color = lvl === 'ok' ? 'var(--ok)' : lvl === 'warn' ? 'var(--warn)' : 'var(--bad)';
    const pill = document.createElement('span');
    pill.className = 'agent-pill';
    pill.style.cssText = `border-color:${color};color:${color}`;
    pill.title = info.message || '';
    pill.textContent = `${agent} ● ${lvl}`;
    el.appendChild(pill);
  }
}

function renderReviewQueue(reviewCount, reviewTasks) {
  const banner = document.getElementById('reviewBanner');
  const list = document.getElementById('reviewList');
  if (!banner || !list) return;
  if (!reviewCount) {
    banner.style.display = 'none';
    return;
  }
  banner.style.display = '';
  list.innerHTML = '';
  for (const t of (reviewTasks||[])) {
    const st = t.status || '';
    const [icon] = PHASE_LABEL[st] || ['?'];
    const eid = (t.id||'').replace(/'/g,"\\'");
    const a = document.createElement('div');
    a.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:2px;';
    a.innerHTML = `<span>${icon} <b>${t.id}</b> <span style="color:var(--muted)">${t.title||''}</span> <span style="color:var(--muted);font-size:11px">→ ${t.owner||''}</span></span>
      <button onclick="viewTaskReport('${eid}','${(t.owner||'').replace(/'/g,"\\'")}'')" style="font-size:10px;padding:1px 6px">View</button>`;
    list.appendChild(a);
  }
}

async function refreshCosts() {
  try {
    const d = await api('/api/costs?top=20');
    const s = d.summary || {};
    document.getElementById('costSummary').textContent =
      s.total_records ? `(${s.total_records} records · $${(s.total_cost_usd||0).toFixed(4)} total)` : '(no data)';
    const tbody = document.getElementById('costRows');
    if (!d.leaderboard || d.leaderboard.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);padding:4px 6px">no benchmark data yet</td></tr>';
      return;
    }
    tbody.innerHTML = d.leaderboard.map(r => `<tr>
      <td style="padding:2px 6px;font-family:monospace">${r.task_id}</td>
      <td style="padding:2px 6px;text-align:right">$${r.total_cost_usd.toFixed(4)}</td>
      <td style="padding:2px 6px;text-align:right">${r.total_tokens.toLocaleString()}</td>
      <td style="padding:2px 6px;text-align:right">${r.dispatch_count}</td>
      <td style="padding:2px 6px;text-align:right">${r.avg_duration_seconds}s</td>
    </tr>`).join('');
  } catch(e) {
    document.getElementById('costSummary').textContent = '(error)';
  }
}

refresh();
refreshCosts();
setInterval(refresh, 3000);
setInterval(refreshCosts, 30000);
</script>

<div id="enqueueModal" onclick="if(event.target===this)cancelEnqueue()" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:999">
  <div style="background:var(--panel);border:1px solid var(--line);border-radius:8px;max-width:600px;margin:80px auto;padding:20px;color:var(--text)">
    <h3 id="enqueueModalTitle" style="margin:0 0 12px 0">Enqueue Task</h3>
    <label style="font-size:12px;color:var(--muted)">Target agent:</label>
    <select id="enqueueTarget" style="width:100%;padding:6px;margin:4px 0 12px 0;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px">
      <option value="claude-code">claude-code</option>
      <option value="codex-cli">codex-cli</option>
    </select>
    <label style="font-size:12px;color:var(--muted)">Instructions (TDD plan — edit or replace):</label>
    <textarea id="enqueueInstructions" rows="12" style="width:100%;padding:8px;margin:4px 0 12px 0;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px;font-family:monospace;font-size:12px;resize:vertical"></textarea>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button onclick="cancelEnqueue()" style="padding:6px 16px;background:var(--bg);color:var(--muted);border:1px solid var(--line);border-radius:4px;cursor:pointer">Cancel</button>
      <button onclick="submitEnqueue()" style="padding:6px 16px;background:var(--ok);color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold">Accept &amp; Enqueue</button>
    </div>
  </div>
</div>

</body>
</html>
"""


def tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return ["No log file yet (created when watcher runs as launchd service). Foreground mode logs to stdout."]
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [ln.rstrip("\n") for ln in lines[-n:]]


def watcher_runtime(label: str) -> dict:
    info = {
        "loaded": False,
        "state": "",
        "last_exit_code": "",
        "run_interval_seconds": 0,
    }
    if sys.platform == "win32":
        return info
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if out.returncode != 0:
            return info
        info["loaded"] = True
        for ln in out.stdout.splitlines():
            if "state =" in ln and not info["state"]:
                info["state"] = ln.split("=", 1)[1].strip()
            elif "last exit code =" in ln:
                info["last_exit_code"] = ln.split("=", 1)[1].strip()
            elif "run interval =" in ln and "seconds" in ln:
                raw = ln.split("=", 1)[1].strip().split(" ", 1)[0]
                try:
                    info["run_interval_seconds"] = int(raw)
                except ValueError:
                    info["run_interval_seconds"] = 0
    except Exception:
        return info
    return info


def inbox_items(inbox_file: Path) -> list[dict]:
    if not inbox_file.exists():
        return []
    items: list[dict] = []
    current: dict = {}
    for raw in inbox_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if raw.startswith("- "):
            if current:
                items.append(current)
            current = {}
            kv = line[2:]
            if ":" in kv:
                k, _, v = kv.partition(":")
                current[k.strip()] = v.strip()
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


def inbox_owner_counts(inbox_file: Path) -> dict[str, int]:
    counts = Counter()
    for item in inbox_items(inbox_file):
        owner = item.get("to", "unknown")
        counts[owner] += 1
    return dict(counts)


def task_instructions(project_dir: Path, task_id: str) -> str:
    """Build personalized TDD instructions for a task by reading plan docs and contract."""
    import re as _re

    # Get task title and criteria from contract
    contract_file = project_dir / ".superharness" / "contract.yaml"
    task_title = task_id
    criteria = []
    if contract_file.exists():
        try:
            import yaml
            doc = yaml.safe_load(contract_file.read_text()) or {}
            for t in doc.get("tasks") or []:
                if isinstance(t, dict) and t.get("id") == task_id:
                    task_title = t.get("title", task_id)
                    criteria = t.get("acceptance_criteria") or t.get("criteria") or []
                    if isinstance(criteria, str):
                        criteria = [criteria]
                    break
        except Exception:
            pass

    # Try to find matching iteration section in plan docs
    plan_section = ""
    # Build keywords from task ID and title (e.g. mod.3-obsidian → ["obsidian"], mod.7-ntfy + "ntfy notification module" → ["ntfy", "notification", "module"])
    _stop_words = {"mod", "feat", "auto", "module", "task", "the", "with", "from", "that", "this"}
    raw_words = [w.lower() for w in _re.split(r"[.\-_]+", task_id) if w and not w.isdigit() and w.lower() not in _stop_words]
    title_words = [w.lower() for w in _re.split(r"[\s\-_()]+", task_title) if w and len(w) >= 4 and w.lower() not in _stop_words]
    raw_words.extend(title_words)
    task_keywords = []
    for w in raw_words:
        task_keywords.append(w)
        # "autoschedule" → also match "schedule", "auto-schedule"
        parts = _re.findall(r"[a-z]+", w)
        if len(parts) == 1 and len(w) > 5:
            for prefix in ("auto",):
                if w.startswith(prefix) and len(w) > len(prefix):
                    task_keywords.append(w[len(prefix):])
                    task_keywords.append(prefix + "-" + w[len(prefix):])
    for plan_file in sorted(project_dir.glob("docs/plan*.md")):
        try:
            content = plan_file.read_text(errors="replace")
            # Find all iteration sections
            sections = _re.split(r"\n(?=## Iteration \d)", content)
            for section in sections:
                if not section.strip().startswith("## Iteration"):
                    continue
                # Strip trailing --- separator
                section = _re.split(r"\n---\s*$", section, flags=_re.MULTILINE)[0].strip()
                header = section.split("\n", 1)[0].lower()
                # Match by keywords from task ID against iteration header
                # Require the longest keyword to match (most specific)
                sorted_kw = sorted(task_keywords, key=len, reverse=True)
                if sorted_kw and any(kw in header for kw in sorted_kw if len(kw) >= 4):
                    plan_section = section.strip()
                    break
            if plan_section:
                break
        except Exception:
            continue

    lines = [f"Task: {task_title} ({task_id})", ""]

    if plan_section:
        lines.append("## Plan (from docs/)")
        lines.append(plan_section)
        lines.append("")

    if criteria:
        lines.append("## Acceptance Criteria")
        for c in criteria:
            lines.append(f"- {c}")
        lines.append("")

    # Check for prior failed attempts — inbox items and handoff reports
    prior_failure = ""
    inbox_file = project_dir / ".superharness" / "inbox.yaml"
    if inbox_file.exists():
        items = inbox_items(inbox_file)
        failed = [i for i in items if i.get("task") == task_id and i.get("status") in ("failed", "stale")]
        if failed:
            prior_failure = f"Status: {failed[-1].get('status')}"

    # Check handoff for failure details
    report = task_report(project_dir, task_id, "")
    handoff_status = report.get("handoff_status", "")
    md_report = report.get("markdown_report", "")
    handoff_outcome = report.get("handoff_outcome", "")

    if handoff_status in ("failed", "blocked", "stale") or prior_failure:
        lines.append("## Prior Attempt (FAILED)")
        if prior_failure:
            lines.append(prior_failure)
        if handoff_outcome:
            lines.append(f"Outcome: {handoff_outcome.strip()}")
        if md_report:
            # Truncate to keep it readable
            snippet = md_report.strip()[:2000]
            lines.append(f"\nAgent report:\n{snippet}")
        if not handoff_outcome and not md_report:
            lines.append("No detailed report from previous attempt.")
        lines.append("")
        lines.append("Fix the issues above before proceeding.")
        lines.append("")

    lines.append("## Process")
    lines.append("1. Read the task details and plan section above")
    lines.append("2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation")
    lines.append("3. Implement only after user approves the plan")
    lines.append("4. Run tests after each phase — all tests must pass before marking done")

    return "\n".join(lines)


def task_report(project_dir: Path, task_id: str, agent: str) -> dict:
    """Gather all report data for a given task and optional agent."""
    harness = project_dir / ".superharness"
    result: dict = {"task": task_id, "agent": agent}

    # 1. Contract task — full data
    contract_file = harness / "contract.yaml"
    if contract_file.exists():
        try:
            import yaml
            doc = yaml.safe_load(contract_file.read_text()) or {}
            for t in doc.get("tasks") or []:
                if isinstance(t, dict) and t.get("id") == task_id:
                    result["contract_status"]   = t.get("status", "")
                    result["contract_title"]    = t.get("title", "")
                    result["contract_owner"]    = t.get("owner", "")
                    result["contract_summary"]  = t.get("summary", "")
                    result["blocked_by"]        = t.get("blocked_by", "")
                    result["acceptance_criteria"] = t.get("acceptance_criteria") or []
                    result["test_types"]        = t.get("test_types") or []
                    result["tdd"]               = t.get("tdd") or {}
                    result["outcomes"]          = t.get("outcomes") or []
                    result["tests_passed"]      = t.get("tests_passed", None)
                    result["verified"]          = t.get("verified", None)
                    result["verified_at"]       = str(t.get("verified_at", ""))
                    result["verified_by"]       = t.get("verified_by", "")
                    # timestamps
                    for ts_key in ("todo_at", "plan_proposed_at", "plan_approved_at",
                                   "in_progress_at", "report_ready_at", "done_at", "stopped_at"):
                        if t.get(ts_key):
                            result[ts_key] = str(t[ts_key])
                    break
        except Exception:
            pass

    # 1b. Launcher log — extract Model / Effort / Via written at dispatch time
    launcher_log_dir = harness / "launcher-logs"
    if launcher_log_dir.exists():
        try:
            # Most recent log for this task+agent
            logs = sorted(launcher_log_dir.glob(f"{task_id}-{agent}-*.log"), reverse=True)
            if not logs:
                logs = sorted(launcher_log_dir.glob(f"{task_id}-*.log"), reverse=True)
            if logs:
                import re as _re
                # Pick most recent log that has actual content (empty logs are stale)
                log_text = ""
                for _log in logs:
                    _t = _log.read_text(errors="replace")
                    if len(_t.strip()) > 10:
                        log_text = _t
                        break
                for line in log_text.splitlines():
                    # Strip ^D literal, backspace chars, and surrounding whitespace
                    line = _re.sub(r'[\x00-\x08\x0e-\x1f\x7f]', '', line)
                    line = line.replace("^D", "").strip()
                    if line.startswith("Model:"):
                        result["dispatch_model"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Effort:"):
                        result["dispatch_effort"] = line.split(":", 1)[1].strip()
                    elif line.startswith("Via:"):
                        result["dispatch_via"] = line.split(":", 1)[1].strip()
        except Exception:
            pass

    # 2. Handoff YAML + markdown report
    handoff_dir = harness / "handoffs"
    if handoff_dir.exists():
        # Search both .yaml and .md files (md files use YAML frontmatter)
        handoff_files = sorted(handoff_dir.glob("*.yaml"), reverse=True) + sorted(handoff_dir.glob("*.md"), reverse=True)
        for f in handoff_files:
            try:
                content = f.read_text(errors="replace")
                # Match by task/task_id fields in content, or by filename (skip instructions files)
                is_instructions = f.name.endswith("-instructions.md")
                has_task = (f"task: {task_id}" in content or f"task: '{task_id}'" in content
                            or f"task_id: {task_id}" in content or f"task_id: '{task_id}'" in content
                            or (not is_instructions and (f.name.startswith(f"{task_id}-") or f.name.startswith(f"{task_id}."))))
                if not has_task:
                    continue
                import yaml
                # For .md files, extract YAML frontmatter between --- delimiters
                if f.suffix == ".md":
                    stripped = content.strip()
                    if stripped.startswith("---"):
                        parts = stripped.split("---", 2)
                        if len(parts) >= 3:
                            hd = yaml.safe_load(parts[1]) or {}
                            md_body = parts[2].strip()
                        else:
                            hd = {}
                            md_body = stripped
                    else:
                        # No frontmatter — use entire content as report body
                        hd = {}
                        md_body = stripped
                else:
                    hd = yaml.safe_load(content) or {}
                    md_body = ""
                if agent and hd.get("to") and hd["to"] != agent and hd.get("from") != agent:
                    continue
                result["handoff_status"] = hd.get("status", "")
                result["handoff_summary"] = hd.get("summary", "")
                result["handoff_outcome"] = hd.get("outcome", "")
                result["handoff_context"] = hd.get("context", "")
                result["handoff_date"] = str(hd.get("date", hd.get("timestamp", "")))
                md_path = hd.get("markdown_report", "")
                if md_path:
                    md_file = project_dir / md_path if not Path(md_path).is_absolute() else Path(md_path)
                    if md_file.exists():
                        result["markdown_report"] = md_file.read_text(errors="replace")[:8000]
                elif md_body:
                    result["markdown_report"] = md_body[:8000]
                break
            except Exception:
                continue

    # 3. Discussion submissions (task_id like discuss-XXX/round-N)
    if "/" in task_id:
        disc_id, round_part = task_id.rsplit("/", 1)
        disc_dir = harness / "discussions" / disc_id
        if disc_dir.exists():
            # Discussion state
            state_file = disc_dir / "state.yaml"
            if state_file.exists():
                try:
                    import yaml
                    st = yaml.safe_load(state_file.read_text()) or {}
                    result["discussion_topic"] = st.get("topic", "")
                    result["discussion_status"] = st.get("status", "")
                    result["discussion_round"] = st.get("current_round", "")
                    result["discussion_max_rounds"] = st.get("max_rounds", "")
                except Exception:
                    pass

            # Agent submission for this round
            round_num = round_part.replace("round-", "")
            sub_file = disc_dir / f"round-{round_num}-{agent}.yaml"
            if sub_file.exists():
                try:
                    import yaml
                    sub = yaml.safe_load(sub_file.read_text()) or {}
                    result["discussion_verdict"] = sub.get("verdict", "")
                    result["discussion_position"] = sub.get("position", "")
                    result["discussion_agent"] = sub.get("agent", agent)
                except Exception:
                    pass

            # If no specific agent submission, try all agents
            if "discussion_position" not in result:
                all_positions = []
                for sf in sorted(disc_dir.glob(f"round-{round_num}-*.yaml")):
                    try:
                        import yaml
                        sub = yaml.safe_load(sf.read_text()) or {}
                        a = sub.get("agent", sf.stem.split("-")[-1])
                        v = sub.get("verdict", "?")
                        p = sub.get("position", "")
                        all_positions.append(f"[{a}] verdict={v}\n{p}")
                    except Exception:
                        continue
                if all_positions:
                    result["discussion_position"] = "\n\n".join(all_positions)

            # Outcome handoff markdown
            if "markdown_report" not in result:
                for mf in sorted(handoff_dir.glob(f"*{disc_id}*outcome*.md"), reverse=True) if handoff_dir.exists() else []:
                    try:
                        result["markdown_report"] = mf.read_text(errors="replace")[:8000]
                        break
                    except Exception:
                        continue
                # Also check per-agent markdown
                if "markdown_report" not in result and agent:
                    for mf in sorted(handoff_dir.glob(f"*{disc_id}*{agent}*.md"), reverse=True) if handoff_dir.exists() else []:
                        try:
                            result["markdown_report"] = mf.read_text(errors="replace")[:8000]
                            break
                        except Exception:
                            continue

    return result


def task_log_content(project_dir: Path, task_id: str, agent: str, lines: int = 0) -> dict:
    """Retrieve live launcher log content for a task+agent.

    Args:
        project_dir: Project root directory
        task_id: Task ID
        agent: Agent name (optional, if empty will match any agent)
        lines: If > 0, return only last N lines

    Returns:
        dict with keys: task, agent, exists, content, log, log_file, size_bytes
        (includes both 'content' and 'log' for compatibility)
    """
    harness = project_dir / ".superharness"
    log_dir = harness / "launcher-logs"

    result: dict = {
        "task": task_id,
        "agent": agent,
        "exists": False,
        "content": "",
        "log": "",
        "log_file": None,
        "size_bytes": 0,
    }

    if not log_dir.exists():
        result["log"] = "(no log file found)"
        return result

    # Find most recent log file matching task-agent-*.log or task-*-*.log pattern
    if agent:
        pattern = f"{task_id}-{agent}-*.log"
    else:
        pattern = f"{task_id}-*.log"
    matching = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    if matching:
        log_file = matching[0]
        result["exists"] = True
        result["log_file"] = str(log_file.relative_to(project_dir))
        try:
            content = log_file.read_text(errors="replace")
            if lines > 0:
                # Return only last N lines
                all_lines = content.splitlines()
                content = "\n".join(all_lines[-lines:])
            result["content"] = content
            result["log"] = content  # Compatibility with existing JS code
            result["size_bytes"] = log_file.stat().st_size
        except Exception as exc:
            error_msg = f"(error reading log: {exc})"
            result["content"] = error_msg
            result["log"] = error_msg
    else:
        result["log"] = "(no log file found)"

    # Check SDK session JSONL for sub-agent activity
    sdk_status = _detect_sdk_activity(project_dir)
    if sdk_status:
        result["sdk_status"] = sdk_status
        if result["log"] and not result["log"].startswith("(no log"):
            result["log"] += f"\n\n--- {sdk_status} ---"
            result["content"] = result["log"]

    # Live diff: show what the agent is changing right now
    git_diff = _git_diff_stat(project_dir)
    if git_diff:
        result["git_diff"] = git_diff
        if result["log"] and not result["log"].startswith("(no log"):
            result["log"] += f"\n\n--- files changed ---\n{git_diff}"
            result["content"] = result["log"]

    return result


def _git_diff_stat(project_dir: Path) -> str:
    """Return compact git diff --stat for uncommitted changes."""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "diff", "--stat", "--no-color", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
            cwd=str(project_dir),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def _detect_sdk_activity(project_dir: Path) -> str:
    """Scan the newest SDK session JSONL for current activity."""
    import json as _json
    safe_path = str(project_dir).replace("/", "-")
    session_dir = Path.home() / ".claude" / "projects" / safe_path
    if not session_dir.exists():
        return ""
    candidates = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return ""
    jsonl = candidates[0]
    try:
        # Read last few lines to detect current activity
        with open(jsonl, "r", encoding="utf-8") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 8KB
            f.seek(max(0, size - 8192))
            tail = f.read()
        last_tool = ""
        last_text = ""
        for line in tail.strip().splitlines():
            if not line.strip():
                continue
            try:
                d = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if d.get("type") == "assistant":
                msg = d.get("message", {})
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            if name == "Agent":
                                desc = inp.get("description", "")
                                return f"sub-agent running: {desc}" if desc else "sub-agent running"
                            last_tool = name
                        elif block.get("type") == "text":
                            last_text = block.get("text", "")[:100]
        if last_tool:
            return f"last tool: {last_tool}"
        return ""
    except Exception:
        return ""


def contract_owners(contract_file: Path) -> list[str]:
    """Read distinct task owners from contract.yaml."""
    if not contract_file.exists():
        return []
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return []
    tasks = doc.get("tasks") or []
    owners = []
    seen = set()
    for t in tasks:
        if isinstance(t, dict):
            o = t.get("owner")
            if o and o not in seen:
                owners.append(o)
                seen.add(o)
    return owners


def parse_utc_timestamp(raw: str) -> dt.datetime | None:
    value = raw.strip().strip("'\"")
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def watcher_health(runtime: dict, items: list[dict], now_utc: str) -> dict:
    now_dt = parse_utc_timestamp(now_utc)
    state = runtime.get("state", "")
    loaded = bool(runtime.get("loaded", False))
    last_exit_code = str(runtime.get("last_exit_code", "")).strip()
    run_interval_seconds = int(runtime.get("run_interval_seconds", 0) or 0)
    pending_items = [x for x in items if x.get("status", "") == "pending"]
    pending_count = len(pending_items)
    stale_count = sum(1 for x in items if x.get("status", "") == "stale")
    failed_count = sum(1 for x in items if x.get("status", "") == "failed")

    if not loaded:
        return {
            "level": "bad",
            "message": "Watcher is not running. Run 'shux dashboard' to start the dashboard and watcher.",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state == "not running" and run_interval_seconds > 0 and last_exit_code in {"0", "(never exited)"}:
        if stale_count > 0 or failed_count > 0:
            return {
                "level": "warn",
                "message": f"Watcher loaded and idle between runs ({run_interval_seconds}s), but backlog issues exist (stale={stale_count}, failed={failed_count}).",
                "pending_count": pending_count,
                "stale_count": stale_count,
                "failed_count": failed_count,
            }
        return {
            "level": "ok",
            "message": f"Watcher loaded and idle between runs (every {run_interval_seconds}s).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state in {"running", "active"} and run_interval_seconds > 0 and last_exit_code in {"0", "(never exited)"}:
        if stale_count > 0 or failed_count > 0:
            return {
                "level": "warn",
                "message": f"Watcher loaded and active (every {run_interval_seconds}s), but backlog issues exist (stale={stale_count}, failed={failed_count}).",
                "pending_count": pending_count,
                "stale_count": stale_count,
                "failed_count": failed_count,
            }
        return {
            "level": "ok",
            "message": f"Watcher loaded and active (every {run_interval_seconds}s).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }
    if state != "running" and state != "not running":
        return {
            "level": "warn",
            "message": f"Watcher loaded but in state '{state}' (last exit={last_exit_code or 'unknown'}).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }

    oldest_pending_age = None
    if now_dt:
        ages = []
        for item in pending_items:
            created = parse_utc_timestamp(item.get("created_at", ""))
            if created is not None:
                ages.append(int((now_dt - created).total_seconds()))
        if ages:
            oldest_pending_age = max(ages)

    if oldest_pending_age is not None and oldest_pending_age > 300:
        mins = oldest_pending_age // 60
        return {
            "level": "warn",
            "message": f"Watcher running but pending queue is aging ({mins}m oldest). Consider Restart watcher.",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
            "oldest_pending_age_seconds": oldest_pending_age,
        }

    if stale_count > 0 or failed_count > 0:
        return {
            "level": "warn",
            "message": f"Watcher running with backlog issues (stale={stale_count}, failed={failed_count}).",
            "pending_count": pending_count,
            "stale_count": stale_count,
            "failed_count": failed_count,
        }

    return {
        "level": "ok",
        "message": f"Watcher running and healthy. pending={pending_count}, stale={stale_count}, failed={failed_count}.",
        "pending_count": pending_count,
        "stale_count": stale_count,
        "failed_count": failed_count,
    }


def _agent_status_health(project_dir: Path, stale_seconds: int = 120) -> dict:
    """Return agent status health for all runtimes — no hardcoded runtime names.

    Uses heartbeat contract v1 (engine.agent_status).  Falls back gracefully
    if the module is unavailable so existing deployments are not broken.
    """
    try:
        from superharness.engine.agent_status import agent_status_health
        return agent_status_health(project_dir, stale_seconds=stale_seconds)
    except Exception:
        return {"agents": {}}


def heartbeat_health(project_dir: Path, stale_seconds: int = 120) -> dict:
    watcher_project = Path(str(watcher_config(project_dir).get("watcher_project", str(project_dir))))
    hb_root = watcher_project if (watcher_project / ".superharness").exists() else project_dir
    hb_file = hb_root / ".superharness" / "watcher.heartbeat"
    if not hb_file.exists():
        return {
            "level": "warn",
            "message": "No heartbeat file — watcher may not be running.",
            "age_seconds": -1,
        }
    raw = hb_file.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return {
            "level": "warn",
            "message": "Heartbeat file is empty — watcher may not be running.",
            "age_seconds": -1,
        }
    hb_dt = parse_utc_timestamp(raw.splitlines()[0])
    if hb_dt is None:
        return {
            "level": "warn",
            "message": f"Heartbeat timestamp unparseable: {raw[:40]}",
            "age_seconds": -1,
        }
    now_dt = dt.datetime.now(tz=dt.timezone.utc)
    age = int((now_dt - hb_dt).total_seconds())
    via_worker = hb_root != project_dir
    if age >= stale_seconds:
        mins = age // 60
        return {
            "level": "warn",
            "message": f"Heartbeat stale ({mins}m ago){' — worker project' if via_worker else ''} — watcher may have crashed.",
            "age_seconds": age,
        }
    return {
        "level": "ok",
        "message": f"Heartbeat OK ({age}s ago){' — worker project' if via_worker else ''}.",
        "age_seconds": age,
    }


def contract_id(contract_file: Path) -> str:
    if not contract_file.exists():
        return ""
    try:
        import yaml
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
        return str(doc.get("id", "") or "")
    except Exception:
        return ""


def contract_tasks(contract_file: Path) -> list[dict]:
    """Return all contract tasks with id, title, status, owner."""
    if not contract_file.exists():
        return []
    try:
        import yaml
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
        tasks = []
        for t in doc.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            tasks.append({
                "id": str(t.get("id", "")),
                "title": str(t.get("title", "")),
                "status": str(t.get("status", "todo")),
                "owner": str(t.get("owner", "")),
                "review_target": _review_target_for_owner(str(t.get("owner", ""))) if str(t.get("status", "todo")) == "review_requested" else "",
                "verified": bool(t.get("verified", False)),
                "workflow": str(t.get("workflow", "")),
                "scheduled_after": str(t.get("scheduled_after", "")),
                "due_by": str(t.get("due_by", "")),
                "depends_on": t.get("depends_on", []) if isinstance(t.get("depends_on"), list) else [x.strip() for x in str(t.get("depends_on", "")).strip("[]").split(",") if x.strip()],
            })
        return tasks
    except Exception:
        return []


def pending_approvals(handoff_dir: Path) -> list[dict]:
    rows: list[dict] = []
    if not handoff_dir.exists():
        return rows
    for file in sorted(handoff_dir.glob("*.yaml")):
        task = ""
        status = ""
        markdown_report = ""
        required = False
        approved = False
        in_gate = False
        for raw in file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if stripped.startswith("task:"):
                task = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped.startswith("status:"):
                status = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped.startswith("markdown_report:"):
                markdown_report = stripped.split(":", 1)[1].strip().strip("'\"")
            elif stripped == "approval_gate:":
                in_gate = True
            elif in_gate and not line.startswith("  "):
                in_gate = False
            elif in_gate and stripped.startswith("required:"):
                required = stripped.split(":", 1)[1].strip().lower() == "true"
            elif in_gate and stripped.startswith("approved_by_user:"):
                approved = stripped.split(":", 1)[1].strip().lower() == "true"
        pending = status == "pending_user_approval" or (required and not approved)
        if pending:
            rows.append(
                {
                    "task": task,
                    "status": status,
                    "required": required,
                    "approved_by_user": approved,
                    "markdown_report": markdown_report,
                }
            )
    return rows


def plan_proposals(harness_dir: Path) -> list[dict]:
    """Return contract tasks with status=plan_proposed that await user confirmation."""
    rows: list[dict] = []
    contract_file = harness_dir / "contract.yaml"
    handoff_dir = harness_dir / "handoffs"
    if not contract_file.exists():
        return rows
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return rows
    tasks = doc.get("tasks", []) or []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") != "plan_proposed":
            continue
        task_id = t.get("id", "")
        owner = t.get("owner", "")
        title = t.get("title", task_id)
        # Find matching handoff for the plan content
        summary = t.get("summary", "")
        handoff_summary = ""
        if handoff_dir.exists():
            for hf in sorted(handoff_dir.glob("*.yaml"), reverse=True):
                try:
                    raw = hf.read_text(encoding="utf-8", errors="replace")
                    hdata = yaml.safe_load(raw) or {}
                    if hdata.get("task") == task_id and hdata.get("status") == "plan_proposed":
                        handoff_summary = hdata.get("summary", "") or hdata.get("scope", "")
                        if isinstance(handoff_summary, list):
                            handoff_summary = "\n".join(str(x) for x in handoff_summary)
                        break
                except Exception:
                    continue
        rows.append({
            "task": task_id,
            "title": title,
            "from": owner,
            "summary": handoff_summary or summary or title,
        })
    return rows


def _set_task_status(harness_dir: Path, task_id: str, to_status: str, from_status: str | None = None) -> dict:
    """Set a contract task status, optionally requiring it to be in from_status first."""
    import yaml  # noqa: F811
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    contract_file = harness_dir / "contract.yaml"
    try:
        doc = yaml.safe_load(contract_file.read_text()) or {}
        found = False
        for t in doc.get("tasks") or []:
            if isinstance(t, dict) and t.get("id") == task_id:
                if from_status and t.get("status") != from_status:
                    return {"ok": False, "error": f"task {task_id} is {t.get('status')!r}, expected {from_status!r}"}
                t["status"] = to_status
                t[f"{to_status}_at"] = now
                found = True
                break
        if not found:
            return {"ok": False, "error": f"task {task_id} not found"}
        contract_file.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False))
        return {"ok": True, "task": task_id, "status": to_status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _contract_task(harness_dir: Path, task_id: str) -> dict | None:
    contract_file = harness_dir / "contract.yaml"
    if not contract_file.exists():
        return None
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text()) or {}
    except Exception:
        return None
    for task in doc.get("tasks") or []:
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    return None


def _review_target_for_owner(owner: str) -> str:
    if owner == "claude-code":
        return "codex-cli"
    return "claude-code"


def board_view(contract_file: Path) -> dict:
    """Return contract tasks grouped into operator board columns.

    Columns: todo | plan | in_progress | review | done
    review_queue: tasks in review_requested / review_passed / review_failed states.
    totals: per-column task count.
    """
    _STATUS_TO_COL = {
        "todo": "todo",
        "plan_proposed": "plan",
        "plan_approved": "plan",
        "plan_confirmed": "plan",
        "in_progress": "in_progress",
        "launched": "in_progress",
        "running": "in_progress",
        "report_ready": "review",
        "review_requested": "review",
        "review_passed": "review",
        "review_failed": "review",
        "done": "done",
        "stopped": "done",
        "failed": "done",
    }
    _REVIEW_QUEUE_STATUSES = {"review_requested", "review_passed", "review_failed"}
    empty: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}

    if not contract_file.exists():
        return {"columns": empty, "review_queue": [], "totals": {col: 0 for col in empty}}

    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {"columns": empty, "review_queue": [], "totals": {col: 0 for col in empty}}

    columns: dict = {col: [] for col in ("todo", "plan", "in_progress", "review", "done")}
    review_queue: list = []

    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        entry = {
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "verified": bool(t.get("verified", False)),
            "blocked_by": str(t.get("blocked_by", "") or ""),
        }
        columns[col].append(entry)
        if st in _REVIEW_QUEUE_STATUSES:
            review_queue.append(entry)

    totals = {col: len(tasks) for col, tasks in columns.items()}
    return {"columns": columns, "review_queue": review_queue, "totals": totals}


def _confirm_plan(harness_dir: Path, task_id: str) -> dict:
    """Confirm a plan_proposed task: set contract task to todo, update handoff."""
    import yaml  # noqa: F811
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    contract_file = harness_dir / "contract.yaml"
    handoff_dir = harness_dir / "handoffs"
    errors = []

    # Update contract task status plan_proposed -> todo
    if contract_file.exists():
        try:
            doc = yaml.safe_load(contract_file.read_text()) or {}
            tasks = doc.get("tasks", []) or []
            found = False
            for t in tasks:
                if isinstance(t, dict) and t.get("id") == task_id and t.get("status") == "plan_proposed":
                    t["status"] = "todo"
                    t["plan_confirmed_at"] = now
                    t["plan_confirmed_by"] = "owner"
                    found = True
                    break
            if found:
                contract_file.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            else:
                errors.append(f"task {task_id} not found in plan_proposed status")
        except Exception as e:
            errors.append(f"contract update error: {e}")  # shipguard:ignore PY-007

    # Update matching handoff: add plan_gate confirmation
    if handoff_dir.exists():
        for hf in sorted(handoff_dir.glob("*.yaml"), reverse=True):
            try:
                raw = hf.read_text(encoding="utf-8", errors="replace")
                hdata = yaml.safe_load(raw) or {}
                if hdata.get("task") == task_id and hdata.get("status") == "plan_proposed":
                    hdata["status"] = "plan_confirmed"
                    gate = hdata.get("plan_gate", {}) or {}
                    gate["confirmed_by_user"] = True
                    gate["confirmed_at"] = now
                    gate["confirmed_by"] = "owner"
                    hdata["plan_gate"] = gate
                    hf.write_text(yaml.dump(hdata, default_flow_style=False, allow_unicode=True))
                    break
            except Exception as e:
                errors.append(f"handoff update error: {e}")  # shipguard:ignore PY-007

    result = {"ok": not errors, "task": task_id, "confirmed_at": now}
    if errors:
        result["errors"] = errors
    return result


def watcher_config(project_dir: Path) -> dict:
    cfg_map = {
        "watcher_project": str(project_dir),
        "interval_seconds": 15,
        "recover_timeout_minutes": 3,
        "recover_action": "retry",
        "launcher_timeout_seconds": 900,
        "target": "both",
        "codex_bypass": False,
    }
    cfg = project_dir / ".superharness" / "watcher.yaml"
    if not cfg.exists():
        return cfg_map
    for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("watcher_project:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val:
                candidate = Path(val).expanduser().resolve()
                if (candidate / ".superharness").exists():
                    cfg_map["watcher_project"] = str(candidate)
        elif line.startswith("interval_seconds:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit() and int(raw_val) > 0:
                cfg_map["interval_seconds"] = int(raw_val)
        elif line.startswith("recover_timeout_minutes:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit():
                cfg_map["recover_timeout_minutes"] = int(raw_val)
        elif line.startswith("recover_action:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val in {"stale", "retry"}:
                cfg_map["recover_action"] = val
        elif line.startswith("launcher_timeout_seconds:"):
            raw_val = line.split(":", 1)[1].strip()
            if raw_val.isdigit():
                cfg_map["launcher_timeout_seconds"] = int(raw_val)
        elif line.startswith("target:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            if val in {"both", "claude-code", "codex-cli"}:
                cfg_map["target"] = val
        elif line.startswith("codex_bypass:"):
            cfg_map["codex_bypass"] = line.split(":", 1)[1].strip().lower() == "true"
    return cfg_map


def board_tasks(contract_file: Path) -> dict[str, list[dict]]:
    """Group contract tasks by board column (todo/plan/active/review/done/stopped)."""
    if not contract_file.exists():
        return {}
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}

    _STATUS_TO_COL: dict[str, str] = {
        "todo": "todo",
        "plan_proposed": "plan",
        "plan_approved": "plan",
        "in_progress": "active",
        "launched": "active",
        "running": "active",
        "report_ready": "review",
        "review_requested": "review",
        "review_passed": "review",
        "review_failed": "review",
        "done": "done",
        "failed": "done",
        "stopped": "stopped",
    }

    columns: dict[str, list[dict]] = {
        "todo": [], "plan": [], "active": [], "review": [], "done": [], "stopped": []
    }

    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        columns[col].append({
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "verified": bool(t.get("verified", False)),
        })

    return columns


def review_queue(contract_file: Path) -> list[dict]:
    """Return tasks in review states ordered by urgency (review_failed first)."""
    if not contract_file.exists():
        return []
    try:
        import yaml  # noqa: F811
        doc = yaml.safe_load(contract_file.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return []

    _REVIEW_STATUSES = {"report_ready", "review_requested", "review_passed", "review_failed"}
    _URGENCY = {
        "review_failed": 0,
        "report_ready": 1,
        "review_requested": 2,
        "review_passed": 3,
    }

    queue = []
    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status", ""))
        if st not in _REVIEW_STATUSES:
            continue
        queue.append({
            "id": str(t.get("id", "")),
            "title": str(t.get("title", "")),
            "status": st,
            "owner": str(t.get("owner", "")),
            "review_target": _review_target_for_owner(str(t.get("owner", ""))),
            "verified": bool(t.get("verified", False)),
            "urgency": _URGENCY.get(st, 9),
        })

    return sorted(queue, key=lambda x: x["urgency"])


def budget_signals(project_dir: Path) -> dict:
    """Extract per-agent budget/usage signals from .superharness/agents/*.status.yaml."""
    try:
        from superharness.engine.agent_status import read_all_agent_statuses
        records = read_all_agent_statuses(project_dir)
        signals: dict = {}
        for runtime, record in records.items():
            if record and record.budget:
                signals[runtime] = record.budget if isinstance(record.budget, dict) else dict(record.budget)
        return {"agents": signals, "available": True}
    except Exception:
        # Fallback: manually scan agents/*.status.yaml for budget fields
        agents_dir = project_dir / ".superharness" / "agents"
        if not agents_dir.exists():
            return {"agents": {}, "available": False}
        signals = {}
        try:
            import yaml  # noqa: F811
            for f in agents_dir.glob("*.status.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}
                    runtime = data.get("runtime", f.stem.replace(".status", ""))
                    if "budget" in data and data["budget"]:
                        signals[runtime] = data["budget"]
                except Exception:
                    continue
        except Exception:
            pass
        return {"agents": signals, "available": bool(signals)}


def project_label(project_dir: Path) -> str:
    # Match install-launchd-inbox-watcher.sh: basename | tr -cs 'A-Za-z0-9' '-'
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project_dir.name).strip("-")
    if not slug:
        slug = "project"
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

    def log_message(self, _fmt: str, *args) -> None:
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

    def _action(self, action: str, payload: dict | None = None) -> tuple[dict, int]:
        wcfg = watcher_config(self.project_dir)
        watcher_project = Path(str(wcfg.get("watcher_project", str(self.project_dir))))
        dispatch = str(self.scripts_dir / "inbox-dispatch.sh")
        recover = str(self.scripts_dir / "inbox-recover-stale.sh")
        normalize = str(self.scripts_dir / "inbox-normalize.sh")
        discuss = str(self.scripts_dir / "discuss.sh")
        install_watcher = str(self.scripts_dir / "install-launchd-inbox-watcher.sh")

        if action in {"watcher_start", "watcher_restart"}:
            install_args = [
                sys.executable,
                "-m",
                "superharness.commands.watcher_worker",
                "--project",
                str(self.project_dir),
                "--worker",
                str(watcher_project),
                "--interval",
                str(int(wcfg.get("interval_seconds", 15))),
                "--recover-timeout-minutes",
                str(int(wcfg.get("recover_timeout_minutes", 3))),
                "--recover-action",
                str(wcfg.get("recover_action", "retry")),
                "--launcher-timeout",
                str(int(wcfg.get("launcher_timeout_seconds", 180))),
                "--to",
                str(wcfg.get("target", "both")),
            ]
            if bool(wcfg.get("codex_bypass", False)):
                install_args.append("--codex-bypass")
            install_result = self._run_cmd(install_args, timeout=120)
            if install_result["exit_code"] != 0:
                return install_result, 200
            uid = os.getuid() if hasattr(os, "getuid") else 0
            kickstart_result = self._run_cmd(
                [
                    "launchctl",
                    "kickstart",
                    "-k",
                    f"gui/{uid}/{self.label}",
                ]
            )
            merged = {
                "exit_code": kickstart_result["exit_code"],
                "stdout": "\n".join(
                    x for x in [install_result.get("stdout", ""), kickstart_result.get("stdout", "")] if x
                ),
                "stderr": "\n".join(
                    x for x in [install_result.get("stderr", ""), kickstart_result.get("stderr", "")] if x
                ),
                "cmd": f"{install_result.get('cmd', '')} && {kickstart_result.get('cmd', '')}".strip(),
            }
            return merged, 200

        if action == "dispatch_print_codex":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "codex-cli", "--print-only"]), 200
        if action == "dispatch_print_claude":
            return self._run_cmd(["bash", dispatch, "--project", str(self.project_dir), "--to", "claude-code", "--print-only"]), 200
        if action == "recover_retry":
            return self._run_cmd(["bash", recover, "--project", str(self.project_dir), "--action", "retry", "--timeout-minutes", "20"]), 200
        if action == "normalize_stale":
            return self._run_cmd(["bash", normalize, "--project", str(self.project_dir), "--archive", "--drop-status", "stale"]), 200
        if action.startswith("confirm_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _confirm_plan(self.project_dir / ".superharness", task_id)
            return result, (200 if result.get("ok") else 500)

        if action.startswith("disable_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "stopped")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("enable_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "todo", from_status="stopped")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("remove_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            contract_file = harness_dir / "contract.yaml"
            try:
                import yaml as _yaml
                with open(contract_file) as _f:
                    _contract = _yaml.safe_load(_f)
                _tasks = _contract.get("tasks", [])
                _before = len(_tasks)
                _contract["tasks"] = [t for t in _tasks if t.get("id") != task_id]
                if len(_contract["tasks"]) == _before:
                    return ({"error": f"task '{task_id}' not found"}, 404)
                with open(contract_file, "w") as _f:
                    _yaml.safe_dump(_contract, _f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                return {"ok": True, "removed": task_id}, 200
            except Exception as exc:
                return ({"error": str(exc)}, 500)

        if action.startswith("approve_plan:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "plan_approved", from_status="plan_proposed")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("request_review:"):
            parts = action.split(":", 2)
            task_id = parts[1] if len(parts) > 1 else ""
            reviewer = parts[2] if len(parts) > 2 else ""
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            task = _contract_task(harness_dir, task_id)
            if not task:
                return ({"error": f"task {task_id} not found"}, 404)
            if str(task.get("status", "")) != "report_ready":
                return ({"error": f"task {task_id} is {task.get('status')!r}, expected 'report_ready'"}, 400)

            items = inbox_items(harness_dir / "inbox.yaml")
            active_statuses = {"pending", "launched", "running", "paused"}
            for item in items:
                if item.get("task") == task_id and item.get("status") in active_statuses:
                    return ({"error": f"task '{task_id}' already enqueued (item {item.get('id')}, status={item.get('status')})"}, 409)

            target = reviewer if reviewer in ("claude-code", "codex-cli") else _review_target_for_owner(str(task.get("owner", "")))
            enqueue_result = self._run_cmd(
                [
                    sys.executable,
                    "-m",
                    "superharness.commands.inbox_enqueue",
                    "--project",
                    str(self.project_dir),
                    "--to",
                    target,
                    "--task",
                    task_id,
                    "--priority",
                    "1",
                ]
            )
            if enqueue_result.get("exit_code") != 0:
                return enqueue_result, 200

            status_result = _set_task_status(harness_dir, task_id, "review_requested", from_status="report_ready")
            if not status_result.get("ok"):
                return status_result, 500

            return (
                {
                    "exit_code": 0,
                    "stdout": f"Requested review for '{task_id}' via {target}.\n{enqueue_result.get('stdout', '').strip()}".strip(),
                    "stderr": enqueue_result.get("stderr", ""),
                    "cmd": enqueue_result.get("cmd", ""),
                    "status": "review_requested",
                    "review_target": target,
                },
                200,
            )

        if action.startswith("cancel_review:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            # Revert task status from review_requested back to report_ready
            result = _set_task_status(harness_dir, task_id, "report_ready", from_status="review_requested")
            if not result.get("ok"):
                return result, 500
            # Remove any pending/paused inbox items for this review
            items = inbox_items(harness_dir / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in ("pending", "paused", "launched"):
                    self._run_cmd(
                        [sys.executable, "-m", "superharness.engine.inbox", "remove",
                         "--file", str(harness_dir / "inbox.yaml"), "--id", item.get("id", "")]
                    )
            return ({"ok": True, "stdout": f"Review cancelled for '{task_id}'. Status reverted to report_ready.", "status": "report_ready"}, 200)

        if action.startswith("approve_without_review:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            harness_dir = self.project_dir / ".superharness"
            # Remove any pending/paused inbox items for this review
            items = inbox_items(harness_dir / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in ("pending", "paused", "launched"):
                    self._run_cmd(
                        [sys.executable, "-m", "superharness.engine.inbox", "remove",
                         "--file", str(harness_dir / "inbox.yaml"), "--id", item.get("id", "")]
                    )
            # Revert to report_ready first (close command rejects review_requested)
            revert = _set_task_status(harness_dir, task_id, "report_ready", from_status="review_requested")
            if not revert.get("ok"):
                return revert, 500
            # Now close the task (skip-verify: operator is explicitly approving)
            return self._run_cmd(
                [
                    sys.executable, "-m", "superharness.commands.close",
                    "--project", str(self.project_dir),
                    "--id", task_id,
                    "--actor", "owner",
                    "--summary", "Approved by operator without agent review",
                    "--skip-verify",
                ]
            ), 200

        if action.startswith("approve_report:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [
                    sys.executable,
                    "-m",
                    "superharness.commands.close",
                    "--project",
                    str(self.project_dir),
                    "--id",
                    task_id,
                    "--actor",
                    "owner",
                    "--summary",
                    "Closed from dashboard without review request",
                    "--skip-verify",
                ]
            ), 200

        if action.startswith("mark_done:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            result = _set_task_status(self.project_dir / ".superharness", task_id, "done", from_status="todo")
            return result, (200 if result.get("ok") else 500)

        if action.startswith("enqueue_task:"):
            parts = action.split(":", 2)
            if len(parts) < 3 or not parts[1] or not parts[2]:
                return ({"error": "Missing task ID or target agent."}, 400)
            task_id, target = parts[1], parts[2]
            if target not in ("claude-code", "codex-cli"):
                return ({"error": f"invalid target: {target}"}, 400)
            # Block duplicate: reject if task already has an active/paused inbox item
            active_statuses = {"pending", "launched", "running", "paused"}
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            for item in items:
                if item.get("task") == task_id and item.get("status") in active_statuses:
                    return ({"error": f"task '{task_id}' already enqueued (item {item.get('id')}, status={item.get('status')})"}, 409)
            # Save instructions file if provided
            instructions = (payload or {}).get("instructions", "").strip()
            if instructions:
                instructions_file = self.project_dir / ".superharness" / "handoffs" / f"{task_id}-instructions.md"
                instructions_file.parent.mkdir(parents=True, exist_ok=True)
                instructions_file.write_text(instructions, encoding="utf-8")
            return self._run_cmd(
                [sys.executable, "-m", "superharness.commands.inbox_enqueue",
                 "--project", str(self.project_dir),
                 "--to", target, "--task", task_id, "--priority", "2"]
            ), 200

        if action.startswith("close_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [sys.executable, "-m", "superharness.commands.close",
                 "--project", str(self.project_dir), "--id", task_id,
                 "--actor", "owner"]
            ), 200

        if action.startswith("approve_task:"):
            task_id = action.split(":", 1)[1]
            if not task_id:
                return ({"error": "missing task id"}, 400)
            return self._run_cmd(
                [
                    "bash",
                    discuss,
                    "approve",
                    "--project",
                    str(self.project_dir),
                    "--task",
                    task_id,
                    "--by",
                    "owner",
                    "--note",
                    "Approved from dashboard",
                ]
            ), 200

        inbox_py = [sys.executable, "-m", "superharness.engine.inbox"]
        inbox_file = str(self.project_dir / ".superharness" / "inbox.yaml")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if action.startswith("pause_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", "pending", "--to", "paused", "--now", now, "--stamp-key", "paused_at"]), 200
        if action.startswith("resume_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", "paused", "--to", "pending", "--now", now, "--stamp-key", "resumed_at"]), 200
        if action.startswith("retry_item:"):
            item_id = action.split(":", 1)[1]
            items = inbox_items(self.project_dir / ".superharness" / "inbox.yaml")
            target = next((i for i in items if i.get("id") == item_id), None)
            if not target:
                return ({"error": f"item not found: {item_id}"}, 404)
            from_status = target.get("status", "")
            if from_status not in ("stale", "failed", "stopped"):
                return ({"error": f"cannot retry from status: {from_status}"}, 400)
            return self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "pending", "--now", now, "--stamp-key", "retried_at"]), 200
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
            result = self._run_cmd(inbox_py + ["set_status", "--file", inbox_file, "--id", item_id, "--from", from_status, "--to", "stopped", "--now", now, "--stamp-key", "stopped_at"])
            return result, 200
        if action.startswith("remove_item:"):
            item_id = action.split(":", 1)[1]
            return self._run_cmd(inbox_py + ["remove", "--file", inbox_file, "--id", item_id]), 200

        return ({"error": f"unsupported action: {action}"}, 400)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path
        if p in {"/", "/index.html"}:
            self._html(HTML)
            return

        if p.startswith("/.superharness/handoffs/") and p.endswith(".md"):
            report_path = (self.project_dir / p.lstrip("/")).resolve()
            handoff_root = (self.project_dir / ".superharness" / "handoffs").resolve()
            if not report_path.is_relative_to(handoff_root):
                self._json({"error": "forbidden"}, 403)
                return
            if not report_path.exists():
                self._json({"error": "not found"}, 404)
                return
            body = report_path.read_bytes()
            self.send_response(200)
            self._set_common_headers("text/markdown; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if p == "/api/status":
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            ledger = self.project_dir / ".superharness" / "ledger.md"
            contract = self.project_dir / ".superharness" / "contract.yaml"
            outlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.out.log"
            errlog = Path.home() / "Library/Logs/superharness" / f"{self.label}.err.log"
            now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            runtime = watcher_runtime(self.label)
            state = str(runtime.get("state", ""))
            items = inbox_items(inbox)
            wcfg = watcher_config(self.project_dir)
            self._json(
                {
                    "project": str(self.project_dir),
                    "label": self.label,
                    "launchctl_state": state or ("loaded" if runtime.get("loaded") else ""),
                    "watcher_health": watcher_health(runtime, items, now_utc),
                    "heartbeat": heartbeat_health(self.project_dir),
                    "agent_status": _agent_status_health(self.project_dir),
                    "watcher_runtime": runtime,
                    "watcher_project": str(wcfg.get("watcher_project", str(self.project_dir))),
                    "watcher_config": wcfg,
                    "contract_id": contract_id(contract),
                    "contract_tasks": contract_tasks(contract),
                    "contract_owners": contract_owners(contract),
                    "active_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") in ("pending", "launched", "running", "paused")
                        and item.get("task")
                    }),
                    "done_inbox_tasks": list({
                        item.get("task") for item in inbox_items(inbox)
                        if item.get("status") == "done"
                        and item.get("task")
                    }),
                    "inbox_counts": inbox_counts(inbox),
                    "inbox_owners": inbox_owner_counts(inbox),
                    "review_queue_count": sum(
                        1 for t in contract_tasks(contract)
                        if t.get("status") in {"review_requested", "review_passed", "review_failed"}
                    ),
                    "review_queue": review_queue(contract),
                    "board_columns": board_tasks(contract),
                    "budget": budget_signals(self.project_dir),
                    "ledger_tail": tail_lines(ledger, 18),
                    "out_tail": tail_lines(outlog, 16),
                    "err_tail": tail_lines(errlog, 16),
                    "now_utc": now_utc,
                    "refresh_seconds": self.refresh_seconds,
                }
            )
            return

        if p == "/api/inbox":
            qs = parse_qs(parsed.query)
            status_filter = qs.get("status", [""])[0]
            owner_filter = qs.get("owner", [])
            inbox = self.project_dir / ".superharness" / "inbox.yaml"
            items = inbox_items(inbox)
            if status_filter:
                items = [i for i in items if i.get("status") == status_filter]
            if owner_filter:
                items = [i for i in items if i.get("to") in owner_filter]
            self._json({"items": items, "status": status_filter, "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return

        if p == "/api/task-log":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            agent = qs.get("agent", [""])[0]
            lines = int(qs.get("lines", ["200"])[0])
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                result = task_log_content(self.project_dir, task_id, agent, lines)
                # Add lines field for compatibility
                result["lines"] = lines
                self._json(result)
            except Exception as exc:
                self._json({"error": f"task_log_content failed: {exc}", "task": task_id, "agent": agent}, 500)
            return

        if p == "/api/task-instructions":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                text = task_instructions(self.project_dir, task_id)
                self._json({"task": task_id, "instructions": text})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        if p == "/api/task-report":
            qs = parse_qs(parsed.query)
            task_id = qs.get("task", [""])[0]
            agent = qs.get("agent", [""])[0]
            if not task_id:
                self._json({"error": "task parameter required"}, 400)
                return
            try:
                self._json(task_report(self.project_dir, task_id, agent))
            except Exception as exc:
                self._json({"error": f"task_report failed: {exc}", "task": task_id, "agent": agent}, 500)
            return

        if p == "/api/board":
            contract = self.project_dir / ".superharness" / "contract.yaml"
            agent_health = _agent_status_health(self.project_dir)
            bv = board_view(contract)
            self._json({
                # New fields (feat.dashboard-operator-upgrade)
                "board": board_tasks(contract),
                "review_queue": review_queue(contract),
                "agent_health": agent_health,
                "budget": budget_signals(self.project_dir),
                # Legacy fields (backward compat with existing tests/JS)
                "columns": bv.get("columns", {}),
                "totals": bv.get("totals", {}),
                "agent_status": agent_health,
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/review-queue":
            contract = self.project_dir / ".superharness" / "contract.yaml"
            self._json({
                "queue": review_queue(contract),
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return

        if p == "/api/costs":
            try:
                from superharness.engine.benchmark import load_records, aggregate
            except ImportError:
                self._json({"error": "benchmark module not available"}, 500)
                return
            qs = parse_qs(parsed.query)
            top_n = int(qs.get("top", ["20"])[0])
            records = load_records(self.project_dir)
            stats = aggregate(records)[:top_n]
            total_cost = sum(r.get("cost_usd", 0.0) for r in records)
            total_tokens = sum(r.get("tokens", 0) for r in records)
            self._json({
                "leaderboard": [
                    {
                        "task_id": s.task_id,
                        "total_cost_usd": round(s.total_cost_usd, 4),
                        "total_tokens": s.total_tokens,
                        "dispatch_count": s.dispatch_count,
                        "success_count": s.success_count,
                        "avg_duration_seconds": round(s.avg_duration_seconds, 1),
                    }
                    for s in stats
                ],
                "summary": {
                    "total_records": len(records),
                    "total_cost_usd": round(total_cost, 4),
                    "total_tokens": total_tokens,
                },
                "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
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

            data, status = self._action(action, payload=payload)
            self._json(data, status)
            return

        if p == "/api/owners":
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
                owner = str(payload.get("owner", "")).strip()
            except Exception:
                self._json({"error": "invalid request body"}, 400)
                return

            if not owner or not all(c.isalnum() or c in "-_" for c in owner):
                self._json({"error": "invalid owner name"}, 400)
                return

            task_sh = self.scripts_dir / "task.sh"
            contract = self.project_dir / ".superharness" / "contract.yaml"

            if action == "add":
                existing = contract_owners(contract)
                if owner in existing:
                    self._json({"ok": True, "owners": existing, "note": "already exists"})
                    return
                task_id = f"agent-{owner}"
                run = subprocess.run(
                    ["bash", str(task_sh), "create",
                     "--project", str(self.project_dir),
                     "--id", task_id,
                     "--title", f"Tasks for {owner}",
                     "--owner", owner,
                     "--status", "todo"],
                    capture_output=True, text=True, check=False, timeout=10,
                )
                if run.returncode != 0:
                    self._json({"error": run.stderr.strip()}, 500)
                    return
                self._json({"ok": True, "owners": contract_owners(contract)})
                return

            if action == "remove":
                existing = contract_owners(contract)
                if owner not in existing:
                    self._json({"ok": True, "owners": existing, "note": "not found"})
                    return
                if len(existing) <= 2:
                    self._json({"error": "Cannot remove owner: at least 2 owners required"}, 400)
                    return
                # Remove all tasks owned by this owner
                try:
                    import yaml
                    doc = yaml.safe_load(contract.read_text()) or {}
                    tasks = doc.get("tasks") or []
                    doc["tasks"] = [t for t in tasks if not (isinstance(t, dict) and t.get("owner") == owner)]
                    contract.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False))
                except Exception as e:
                    self._json({"error": str(e)}, 500)
                    return
                self._json({"ok": True, "owners": contract_owners(contract)})
                return

            self._json({"error": f"unknown owner action: {action}"}, 400)
            return

        self._json({"error": "not found"}, 404)


def autohealth_check(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Ping the dashboard server. Returns True if healthy, False otherwise."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/status")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def autohealth_loop(
    project_dir: str,
    port: int = 8787,
    host: str = "127.0.0.1",
    interval: int = 5,
    max_restarts: int = 100,
) -> None:
    """Watchdog loop: check server health every `interval` seconds, restart if dead."""
    import signal
    restarts = 0
    proc: subprocess.Popen | None = None
    log_handle: object = None

    def _start() -> subprocess.Popen:
        nonlocal log_handle
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
        log_handle = open(os.path.join(project_dir, ".superharness", "dashboard-health.log"), "a")
        return subprocess.Popen(
            [sys.executable, "-u", __file__, "--project", str(project_dir),
             "--port", str(port), "--host", host, "--no-open"],
            start_new_session=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

    def _shutdown(signum: int, frame: object) -> None:
        if proc and proc.poll() is None:
            proc.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    proc = _start()
    print(f"autohealth: started dashboard pid={proc.pid} port={port}")

    while restarts < max_restarts:
        time.sleep(interval)
        if proc.poll() is not None or not autohealth_check(port, host):
            restarts += 1
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            proc = _start()
            print(f"autohealth: restarted dashboard pid={proc.pid} (restart #{restarts})")
    print(f"autohealth: max restarts ({max_restarts}) reached, exiting")


def main() -> int:
    _ensure_python_with_yaml()
    ap = argparse.ArgumentParser(description="superharness browser dashboard")
    ap.add_argument("--project", default=None, help="project directory containing .superharness (default: cwd)")
    ap.add_argument("--port", type=int, default=8787, help="HTTP port (default: 8787)")
    ap.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    ap.add_argument("--refresh-seconds", type=int, default=3, help="ui refresh seconds (default: 3)")
    ap.add_argument("--no-open", action="store_true", help="do not open browser automatically")
    ap.add_argument("--autohealth", action="store_true", help="run watchdog that auto-restarts dashboard if it dies")
    ap.add_argument("--health-interval", type=int, default=5, help="health check interval in seconds (default: 5)")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve() if args.project else Path.cwd()
    if not (project_dir / ".superharness").is_dir():
        raise SystemExit(f"Missing .superharness in project: {project_dir}")
    try:
        if not ipaddress.ip_address(args.host).is_loopback:
            raise SystemExit(f"dashboard host must be loopback-only, got: {args.host}")
    except ValueError:
        if args.host not in {"localhost"}:
            raise SystemExit(f"dashboard host must be loopback-only, got: {args.host}")

    if args.autohealth:
        autohealth_loop(
            project_dir=str(project_dir),
            port=args.port,
            host=args.host,
            interval=args.health_interval,
        )
        return 0

    scripts_dir = Path(__file__).resolve().parent

    # Guard: prevent a second dashboard for the same project directory.
    _my_pid = os.getpid()
    try:
        import subprocess as _sp
        _ps = _sp.run(["ps", "ax", "-o", "pid=,args="], capture_output=True, text=True).stdout
        for _line in _ps.splitlines():
            _line = _line.strip()
            if "dashboard-ui.py" not in _line and "monitor-ui.py" not in _line:
                continue
            _parts = _line.split()
            try:
                _other_pid = int(_parts[0])
            except (ValueError, IndexError):
                continue
            if _other_pid == _my_pid:
                continue
            # Extract --project from that process's cmdline
            _other_proj = None
            for _i, _p in enumerate(_parts):
                if _p == "--project" and _i + 1 < len(_parts):
                    _other_proj = str(Path(_parts[_i + 1]).expanduser().resolve())
                    break
            if _other_proj and Path(_other_proj).resolve() == project_dir.resolve():
                # Find its port via lsof
                _lsof = _sp.run(
                    ["lsof", "-a", "-i", "TCP", "-sTCP:LISTEN", "-n", "-P", "-p", str(_other_pid)],
                    capture_output=True, text=True,
                ).stdout
                _existing_port = None
                for _ll in _lsof.splitlines():
                    _lp = _ll.split()
                    if len(_lp) >= 9:
                        try:
                            _existing_port = int(_lp[8].split(":")[-1])
                        except ValueError:
                            pass
                _url = f"http://127.0.0.1:{_existing_port}" if _existing_port else "(port unknown)"
                print(f"dashboard already running for project '{project_dir.name}' (pid={_other_pid}, {_url})")
                print(f"  kill it first:  shux dashboard-kill --project {project_dir}")
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass  # Guard failure must never block startup

    Handler.project_dir = project_dir
    Handler.label = project_label(project_dir)
    Handler.refresh_seconds = args.refresh_seconds
    Handler.scripts_dir = scripts_dir
    Handler.auth_token = secrets.token_urlsafe(24)

    port = args.port
    user_specified_port = "--port" in sys.argv
    if not user_specified_port:
        for candidate in range(port, port + 20):
            try:
                server = ThreadingHTTPServer((args.host, candidate), Handler)
                if candidate != port:
                    print(f"port {port} in use, using {candidate}")
                port = candidate
                break
            except OSError as exc:
                if exc.errno in (48, 98) or "address already in use" in str(exc).lower():
                    continue
                raise
        else:
            raise SystemExit(f"No free port found in range {args.port}–{args.port + 19}")
    else:
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
        except OSError as exc:
            if exc.errno in (48, 98) or "address already in use" in str(exc).lower():
                raise SystemExit(f"Port {port} is already in use") from None
            raise
    url = f"http://{args.host}:{port}"
    print(f"dashboard: {url}")
    print(f"project: {project_dir}")
    print(f"watcher label: {Handler.label}")
    url_file = os.environ.get("SUPERHARNESS_DASHBOARD_URL_FILE") or os.environ.get("SUPERHARNESS_MONITOR_URL_FILE")
    if url_file:
        with open(url_file, "w") as _f:
            _f.write(f"dashboard: {url}\n")
            _f.write(f"project: {project_dir}\n")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
