#!/usr/bin/env bash
# shux ⇄ RMDI merge verification — end-to-end SUT check (Phase B).
#
# Spins an EPHEMERAL RMDI router with a throwaway state dir + a throwaway shux
# project (isolated SUPERHARNESS_STATE_DIR — never touches real state), then:
#   1. router_health        — ephemeral router boots
#   2. recipe_switched      — shux recipe shux-orchestrator activates (exit 0)
#   3. delegate_resolves    — shux delegate --print-only resolves the model via
#                             the router (prints "RMDI routing: seat ...")
#   4. binding_crosscheck   — the printed bindingVersion matches GET /bindings
#   5. model_override_blocked — --model under routing_strategy:rmdi exits 2
#   6. router_down_fail_loud — with the router dead, delegate exits non-zero
#                             naming the router URL (no silent native fallback)
#
# Emits a fixed-schema JSON (shux-rmdi-verification/v1) to docs/trials/<date>/,
# the same SUT pattern as rmdi's verify-recipe-switch.sh.
#
# Usage: verify-shux-rmdi.sh [port]   (env: RMDI_REPO=/path/to/rmdi  BUN=bun)
set -euo pipefail

PORT="${1:-8211}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RMDI_REPO="${RMDI_REPO:-/mnt/pve/gs-nas/yjjoe-workspace/Anthropic/root/rmdi}"
BUN="${BUN:-$HOME/.bun/bin/bun}"
ROUTER="http://127.0.0.1:$PORT"
STATE="$(mktemp -d)"
PROJ="$STATE/project"
OUT_DIR="$REPO/docs/trials/$(date +%F)"
OUT="$OUT_DIR/shux-rmdi-verification.json"
mkdir -p "$OUT_DIR" "$PROJ/.superharness/handoffs"

export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export SUPERHARNESS_STATE_DIR="$STATE/shux-state"
export RMDI_ROUTER_URL="$ROUTER"

C_HEALTH=false C_SWITCH=false C_DELEGATE=false C_XCHECK=false C_OVERRIDE=false C_DOWN=false
PID=""

cleanup() {
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
  fuser -k "$PORT/tcp" 2>/dev/null || true
  rm -rf "$STATE"
}
trap cleanup EXIT

emit() {
  python3 - "$OUT" <<PYEOF
import json, sys, time
json.dump({
    "schema": "shux-rmdi-verification/v1",
    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "router": "$ROUTER (ephemeral)",
    "checks": {
        "router_health": "$C_HEALTH" == "true",
        "recipe_switched": "$C_SWITCH" == "true",
        "delegate_resolves": "$C_DELEGATE" == "true",
        "binding_crosscheck": "$C_XCHECK" == "true",
        "model_override_blocked": "$C_OVERRIDE" == "true",
        "router_down_fail_loud": "$C_DOWN" == "true",
    },
    "ok": "${1}" == "true",
}, open(sys.argv[1], "w"), indent=2)
print("report:", sys.argv[1])
PYEOF
}

fail() { echo "FAIL: $1" >&2; emit "false"; exit 1; }

echo "== launch ephemeral RMDI router :$PORT =="
RMDI_PORT="$PORT" RMDI_STATE_DIR="$STATE/rmdi-state" \
  RMDI_CONFIG="$RMDI_REPO/config/x-fleet-routing.json" \
  RMDI_ROLES="$RMDI_REPO/config/roles.json" \
  RMDI_RECIPES="$RMDI_REPO/config/recipes" \
  "$BUN" run "$RMDI_REPO/router/src/server.ts" >"$STATE/router.log" 2>&1 &
PID=$!
for _ in $(seq 1 20); do curl -sf -m 2 "$ROUTER/health" >/dev/null 2>&1 && break; sleep 0.5; done
curl -sf -m 3 "$ROUTER/health" >/dev/null || fail "router did not boot (see $STATE/router.log)"
C_HEALTH=true

echo "== seed throwaway shux project =="
cat > "$PROJ/.superharness/profile.yaml" <<'YAML'
routing_strategy: rmdi
autonomy: supervised
YAML
python3 - "$PROJ" <<'PY'
import sys
from superharness.engine.db import get_connection, init_db
proj = sys.argv[1]
conn = get_connection(proj)
init_db(conn)
conn.execute(
    "INSERT INTO tasks (id, title, owner, status, created_at) "
    "VALUES ('T-RMDI', 'verify rmdi routing', 'opencode', 'plan_approved', '2026-07-09T00:00:00Z')"
)
conn.commit()
conn.close()
PY

echo "== 2/6 shux recipe shux-orchestrator =="
python3 -m superharness.commands.recipe shux-orchestrator </dev/null >"$STATE/switch.out" 2>&1 \
  || fail "recipe switch failed: $(cat "$STATE/switch.out")"
grep -q "Activated recipe: shux-orchestrator" "$STATE/switch.out" || fail "switch output missing activation line"
C_SWITCH=true

echo "== 3/6 shux delegate --print-only resolves via router =="
python3 -m superharness.commands.delegate --project "$PROJ" --task T-RMDI --to opencode \
  --print-only --non-interactive >"$STATE/delegate.out" 2>&1 \
  || fail "delegate --print-only failed: $(tail -5 "$STATE/delegate.out")"
grep -q "RMDI routing: seat worker@shux" "$STATE/delegate.out" || fail "no RMDI routing line: $(head -5 "$STATE/delegate.out")"
C_DELEGATE=true

echo "== 4/6 binding cross-check (printed version == router table) =="
python3 - "$ROUTER" "$STATE/delegate.out" <<'PY' || fail "binding cross-check failed"
import json, re, sys, urllib.request
router, out_path = sys.argv[1], sys.argv[2]
out = open(out_path).read()
m = re.search(r"RMDI routing: seat (\S+) -> (\S+) \(v(\d+),", out)
assert m, f"cannot parse routing line from: {out[:200]}"
seat, model_ref, version = m.group(1), m.group(2), int(m.group(3))
rows = json.load(urllib.request.urlopen(f"{router}/bindings"))
row = next(r for r in rows if r["seatID"] == seat)
spec = row["binding"]["modelSpec"]
assert f"{spec['providerID']}/{spec['modelID']}" == model_ref, (spec, model_ref)
assert row["binding"]["version"] == version, (row["binding"]["version"], version)
assert row["binding"]["regime"] == "ddap"
PY
C_XCHECK=true

echo "== 5/6 --model override is rejected under rmdi (exit 2) =="
set +e
python3 -m superharness.commands.delegate --project "$PROJ" --task T-RMDI --to opencode \
  --print-only --non-interactive --model sonnet >"$STATE/override.out" 2>&1
RC=$?
set -e
[ "$RC" = "2" ] || fail "--model under rmdi expected exit 2, got $RC"
grep -q "seat rebinds" "$STATE/override.out" || fail "override error message missing"
C_OVERRIDE=true

echo "== 6/6 router down ⇒ delegate fails loud =="
kill "$PID" 2>/dev/null || true
PID=""
sleep 0.5
set +e
python3 -m superharness.commands.delegate --project "$PROJ" --task T-RMDI --to opencode \
  --print-only --non-interactive >"$STATE/down.out" 2>&1
RC=$?
set -e
[ "$RC" != "0" ] || fail "delegate succeeded with a dead router (silent fallback?)"
grep -q "RMDI router unreachable" "$STATE/down.out" || fail "router-down message missing: $(tail -3 "$STATE/down.out")"
C_DOWN=true

emit "true"
echo "ALL SHUX-RMDI CHECKS PASSED"
