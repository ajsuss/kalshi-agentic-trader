# Rebuild Wave 1: Audit Matrix + Initial Code Migration

## Source-of-truth confirmation
- `docs/kalshi_rebuild_spec.md` **already existed in the repository before this wave** and remains the primary specification.
- `docs/codex_full_rebuild_prompt.md` is treated as operating guidance for execution behavior, not the architecture source of truth.

## A) Preserve / Replace / Deprecate matrix

| Area | Preserve | Replace | Deprecate |
|---|---|---|---|
| Config + secrets | `app/kalshi_agentic/config.py` semantics | direct script-level env parsing | scattered env parsing in step scripts |
| Kalshi API primitives | signed request logic in `app/kalshi_agentic/kalshi_client.py` | script-owned client wiring | step-specific transport wrappers |
| Market intelligence primitives | scan/selection/snapshot helper logic | subprocess fan-out between scripts | numbered scripts as long-term feature hosts |
| Governance and execution | dry-run safety posture | implicit/fragmented decision logic | direct execution paths outside centralized executor/policy |
| Telegram interface | command intent from status bot | hardcoded script subprocess dispatcher | command handlers tied to `stepNN` invocations |
| State and logs | existing seed files + log history | ad hoc JSON IO in each script | file-specific state logic duplicated across scripts |
| Legacy scripts | temporary entrypoints for compatibility | architecture based on script chaining | `stepNN` scripts once equivalent module routing is complete |

## B) Target end-state package structure

```text
app/
  core/
    agent.py
    agent_registry.py
  agents/
    ...
  orchestration/
    ...
  governance/
    ...
  execution/
    executor.py
  interfaces/
    telegram/
      router.py
  state/
    manager.py
  observability/
    ...
  policies/
    risk_policy.py
  migration/
    legacy_compat.py

tests/
```

## C) Migration rules (enforced during rebuild)
1. Live trading remains disabled by default.
2. Dry-run only unless explicitly armed via policy gate (`EXECUTION_MODE=live` and `KALSHI_LIVE_TRADING_ARMED=1`).
3. No direct order execution path without executor + policy checks.
4. Preserve logs and observability; do not delete existing historical logs/state.
5. Keep the current repo usable during migration via compatibility entrypoints.

## D) Migration wave plan
- **Wave 1 (this change):** create foundational modules (agent interface/registry, state manager, risk policy, executor, Telegram router) and wire legacy script compatibility for step43/45/46.
- **Wave 2:** migrate market scan/selection/snapshots into `app/agents` and `app/services`, then point bot command routing at module calls.
- **Wave 3:** implement governance modules (`budget_distributor`, richer risk checks), candidate lifecycle orchestration, and structured event logging.
- **Wave 4:** retire step-script internals behind thin wrappers; add end-to-end dry-run tests and finalize operator docs.
