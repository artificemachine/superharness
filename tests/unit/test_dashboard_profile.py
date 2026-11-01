import shutil
import subprocess
from pathlib import Path

import pytest


def test_populated_profile_renders_and_escapes_html():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute dashboard JavaScript")
    html = (Path(__file__).parents[2] / "src/superharness/scripts/dashboard.html").read_text()
    start = html.find("function escapeHtml(")
    if start < 0:
        start = html.index("async function loadProfile()")
    source = html[start:html.index("function rebuildOwnerCheckboxes()", start)]
    script = """
const assert = require('node:assert/strict');
const elements = {};
const document = {getElementById(id) { return elements[id] ||= {}; }};
const hostile = `<img src=x onerror='bad()'>&\"`;
async function api() { return {has_data: true, profiles: {
  task_style: {default_effort: hostile, tdd_required: true, sample_count: 2},
  model_prefs: {preferred_model: hostile, sample_count: 1}
}, trials: [{profile_key: hostile, old_value: hostile, new_value: hostile}]}; }
""" + source + """
loadProfile().then(() => {
  assert.match(elements.profileContent.innerHTML || '', /Task style:/);
  assert.match(elements.profileContent.innerHTML, /Model:/);
  for (const id of ['profileContent', 'profileTrials']) {
    assert.ok(!elements[id].innerHTML.includes('<img'));
    assert.ok(elements[id].innerHTML.includes('&lt;img'));
    assert.ok(elements[id].innerHTML.includes('&amp;'));
    assert.ok(elements[id].innerHTML.includes('&#39;'));
    assert.ok(elements[id].innerHTML.includes('&quot;'));
  }
});
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
