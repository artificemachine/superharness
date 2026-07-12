# vLLM per-tier fleet endpoints — enablement guide

`_call_fleet` and `fleet_health` (src/superharness/engine/model_router.py) speak plain OpenAI-compatible `/chat/completions` and `/models` — vLLM's native API, same as Ollama's. No code change is needed to accept vLLM endpoints; `fleet.yaml`'s per-tier shape already resolves them via `_fleet_candidates` (mini → standard → all, endpoint failover added in PLAN-superharness-L5.md iteration 3).

## Config shape

`~/.config/superharness/fleet.yaml`:

```yaml
fleet:
  endpoints:
    mini: "http://<gpu-lab-mini-host>:8100/v1"
    standard: "http://<gpu-lab-standard-host>:8100/v1"
    max: "http://<gpu-lab-max-host>:8100/v1"
    all: "http://127.0.0.1:11434/v1"   # local Ollama fallback

  models:
    mini: "<model-id-from-that-box>"
    standard: "<model-id-from-that-box>"
    max: "<model-id-from-that-box>"
    all: "qwen2.5:7b"
```

**Real bug found while enabling this**: the config previously had a *commented-out* sketch using the key `fleet_endpoints:` — that key is never read by any code path. The actual keys are `fleet.endpoints` and `fleet.models`, both flat dicts keyed by tier. A config using `fleet_endpoints:` would silently do nothing if uncommented as-is.

**Always use the explicit IPv4 loopback (`127.0.0.1`), never `localhost`**, for any local endpoint in this file — see the "onboard fleet template" fix (iteration 2) for why: on a machine running a second OpenAI-compatible server on the same port, `localhost` can resolve straight to the wrong server's model store.

## Enablement steps

1. Probe reachability before writing anything: `curl -s --max-time 5 http://<host>:<port>/v1/models` for each tier's box. Do not guess a model id — read it from the response.
2. Write the per-tier `endpoints`/`models` entries. Keep `all` (local Ollama) configured too — it becomes the automatic last-resort fallback via `_fleet_candidates`'s failover, at zero extra cost.
3. Verify: `shux doctor` (or the dev-repo equivalent, `python -m superharness.commands.doctor --project .`) — each configured tier prints `PASS fleet/<tier>: <model> @ <endpoint>` on success, `WARN fleet/<tier>: ...` if the endpoint is unreachable or the model isn't actually served there.
4. Optional real check: run a classify call through the new tier directly (`model_router._classify_via_fleet(...)`) and confirm the returned `(tier, effort)` makes sense for the prompt.

## Verification record (2026-07-12)

Probed all three GPU-lab tiers from this machine:

| Tier | Host | Result |
|---|---|---|
| mini | `<LAN-mini-endpoint>:8100` | Reachable — `qwen25-7b`, `qwen25-coder-7b`, `qwen25-15b`, `granite31-8b`, `qwen2.5-vl-7b` |
| standard | `<LAN-standard-endpoint>:8100` | Reachable — `qwen3.6-27b-awq`, `gemma4-31b-awq`, `qwen3.5-9b`, `qwen3-32b-awq` |
| max | `<LAN-max-endpoint>:8100` | **Unreachable** — `curl` connection refused (verified, not assumed; box appears down, not merely idle/unloaded) |

Enabled `mini` (`qwen25-7b`) and `standard` (`qwen3-32b-awq`) in the live user fleet config. `max` left commented with the exact re-check command, per the config's own comment — do not guess a model id for it once it comes back; re-probe.

Post-enablement `shux doctor` (dev repo):
```
PASS fleet/mini: qwen25-7b @ http://<LAN-mini-endpoint>:8100/v1
PASS fleet/standard: qwen3-32b-awq @ http://<LAN-standard-endpoint>:8100/v1
PASS fleet/all: qwen2.5:7b @ http://127.0.0.1:11434/v1
```

Real classify call routed through the new `mini` tier (not the local Ollama fallback): a trivial README-typo prompt returned `(mini, low)` — correct.
