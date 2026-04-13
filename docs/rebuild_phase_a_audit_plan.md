# Phase A Audit and Migration Plan

## Scope and intent
This document is the Phase A artifact requested by the rebuild prompt: an explicit audit of the current repository, a preserve-vs-replace map, the target architecture, and an ordered migration sequence before major code movement.

Safety invariant carried forward in all phases: **live trading remains disabled by default** and no order path bypasses governance checks.

## 1) Repository audit (current state)

### Reusable primitives already present
- `app/kalshi_agentic/config.py`: environment + secret loading with file-backed secret support and Kalshi base URL resolution.
- `app/kalshi_agentic/kalshi_client.py`: signed Kalshi REST client with auth headers and `public_get`, `auth_get`, `auth_post`.
- `app/kalshi_agentic/market_scan.py`: market page fetch, summary shaping, candidate tradability checks, scoring, ranked universe scan.
- `app/kalshi_agentic/market_selection.py`: targeted event/market lookup helpers.
- `app/kalshi_agentic/snapshots.py`: snapshot helpers used by scripts and status workflows.
- `app/kalshi_agentic/telegram_notifier.py`: Telegram send wrapper.
- `state/*.json`: seed state files for team status, codex seed state, and performance.

### Structural debt and migration pressures
- `scripts/step*.py` is the dominant control-plane architecture (dozens of numbered scripts).
- `scripts/step44_telegram_status_bot.py` hardcodes command handling and shells out to other step scripts rather than routing via typed modules.
- Risk/governance logic appears fragmented across multiple step scripts rather than stable package modules.
- State reads/writes are distributed ad hoc instead of centralized state APIs.
- Existing architecture emphasizes chronology of build steps, not durable product boundaries.

## 2) Preserve vs replace map

### Preserve (logic to migrate with minimal behavior change)
1. Secret/config loading semantics.
2. Kalshi request signing and client transport behavior.
3. Market scanning and ranking heuristics.
4. Targeted lookup + snapshot shaping functions.
5. Seed state conventions.
6. Current dry-run safeguards and live mode arming/disarming workflow.

### Replace (structure and integration points)
1. Numbered step-script orchestration as the primary architecture.
2. Subprocess-driven Telegram command execution.
3. Fragmented governance/risk modules.
4. Implicit candidate lifecycle transitions.
5. Non-unified state persistence and observability.

## 3) Target architecture proposal

```text
bot/
  telegram_app.py
  command_router.py
  command_registry.py

agents/
  base.py
  market_scanner.py
  market_selection.py
  snapshot.py
  team_status.py
  performance.py
  digest.py
  review.py

orchestrators/
  candidate_pipeline.py
  refresh_cycle.py

governance/
  risk_guard.py
  executor.py
  budget_distributor.py
  policy.py

services/
  config.py
  kalshi_client.py
  market_data_service.py
  execution_service.py
  notification_service.py

state/
  manager.py
  store.py
  schemas.py
  event_log.py

reporting/
  digest_builder.py
  performance_report.py

schemas/
  commands.py
  candidate.py
  governance.py
  telegram.py

prompts/
  deliberation/
```

### Design principles
- Move from script-to-script subprocess chaining to in-process module calls.
- Define typed request/response contracts for command handling and agent execution.
- Keep execution gated through governance with explicit dry-run/live mode policy checks.
- Centralize state writes and append-only event logging for reconstruction.

## 4) Migration sequence

### Phase A (this document + prep)
1. Publish the audit and migration plan (this file).
2. Canonicalize rebuild prompt path for local usage (`docs/codex_full_rebuild_prompt.md`).
3. Establish implementation checklist for next phases.

### Phase B (core skeleton)
1. Create package scaffolding (`agents`, `bot`, `governance`, `services`, `state`, `schemas`, `reporting`, `orchestrators`).
2. Migrate config + Kalshi client into `services` while keeping compatibility shims.
3. Introduce centralized state manager and structured event log.

### Phase C (feature migration)
1. Migrate market scan/selection/snapshots into agents + services.
2. Introduce `AgentManager`/registry for discoverable agents.
3. Replace script subprocess dependencies with direct module invocation.

### Phase D (governance + command system)
1. Implement policy thresholds, risk guard, budget distributor, and executor.
2. Build Telegram command registry and route commands to agents/orchestrators.
3. Add review/approve/deny control flow and operator notifications.

### Phase E (tests, cleanup, docs)
1. Add tests for client wrappers, governance decisions, command routing, dry-run E2E flow.
2. Deprecate obsolete step scripts (retain thin compatibility wrappers only where needed).
3. Update operational docs and startup scripts for the new architecture.

## 5) Beginning Phase A implementation status
- [x] Completed repo audit and preserve/replace analysis.
- [x] Published explicit target architecture proposal.
- [x] Published migration sequence with phase gates.
- [x] Added canonical rebuild prompt filename used by instructions.
- [ ] Next: begin Phase B skeleton creation and compatibility shims.
