# Codex Master Prompt — Kalshi Agentic Trader Full Rebuild

You are working inside the repository `ajsuss/kalshi-agentic-trader`.

Your job is **not** to keep incrementally extending the current numbered-step architecture. Your job is to **reform the repo into the correct end-state product** while preserving working primitives and maintaining strict safety controls.

The attached document `kalshi_rebuild_spec.md` is the canonical rebuild specification. Read it first and follow it as the source of truth.

## Mission
Rebuild the current partial Kalshi Telegram trading framework into a durable, modular, Telegram-first agent operating system for Kalshi account management and trade execution workflows.

The finished system must support:
- Telegram as the main operating interface
- modular agents and team workflows
- governance layers for budget allocation and execution approval
- structured state and logging
- dry-run by default, live mode only via explicit guarded policy
- clear auditability for every meaningful decision

## Important context about the current repo
The current repo already contains useful pieces that should be reused where sensible:
- configuration loading for secrets and environment variables
- a signed Kalshi API client
- market scan and targeted market lookup helpers
- snapshot logic
- Telegram status command handling
- dry-run seed state files
- many historical numbered step scripts

Do **not** assume the current file structure is the right architecture.

## Required attitude
- Be willing to move, rename, consolidate, or replace files.
- Preserve good logic; discard bad structure.
- Optimize for the final product, not for historical continuity.
- Favor explicit modules, typed data contracts, and stable packages over ad hoc scripts.

## Hard constraints
1. Keep live trading disabled by default.
2. Do not remove or weaken risk and execution safeguards.
3. No agent may directly place live orders without passing through governance and executor checks.
4. Every important action must be logged in a structured way.
5. Do not continue the repo's long-term architecture through new numbered step scripts unless a temporary migration shim is absolutely necessary.

## What you must produce
### 1. New durable architecture
Create or migrate toward a structure like:
- `bot/` for Telegram app logic and command routing
- `agents/` for reusable agent modules
- `orchestrators/` for multi-agent workflows
- `governance/` for budget distributor, executor, risk guard, policies
- `services/` for Kalshi, execution, notifications, market data, research
- `state/` for persistent state interfaces and storage
- `reporting/` for digests and performance summaries
- `schemas/` for typed request/response models
- `prompts/` for internal agent prompts and templates

### 2. Migration of existing useful logic
Find the existing working primitives and migrate them into the new architecture:
- config loader
- Kalshi client
- market scanning
- targeted event/market lookup
- snapshots
- Telegram status functionality
- seed state handling

### 3. Governance layer
Implement explicit reusable modules for:
- budget distribution
- executor approval / rejection
- risk guard
- policy thresholds
- dry-run vs live-mode gating

### 4. Telegram-first control plane
Refactor the bot into a true command system with:
- `/help`
- `/agents`
- `/status`
- `/queue`
- `/performance`
- `/budget`
- `/refresh`
- `/review`
- `/approve`
- `/deny`
- `/agent <name> <instruction>` for routed free-form tasks

Support both direct commands and routed specialist instructions.

### 5. Strategy / candidate lifecycle
Create explicit lifecycle states for trade ideas:
- discovered
- enriched
- challenged
- budgeted
- execution_review
- approved
- blocked
- sent
- monitored
- closed
- postmortem

### 6. State and observability
Implement:
- centralized state manager
- append-only structured event log
- performance ledger
- clear human-readable summaries
- reproducible reconstruction of major actions from logs/state

### 7. Testing
Add tests for at least:
- Kalshi client wrappers
- governance decisions
- command routing
- one dry-run end-to-end candidate flow

### 8. Documentation
Write clear docs so a future contributor can understand the system without relying on historical conversation context.

## Execution plan
Work in phases.

### Phase A — audit and plan
- inspect current repo
- identify reusable logic vs structural debt
- produce a concise migration plan in repo docs before large edits

### Phase B — build core skeleton
- create package layout
- define schemas and base interfaces
- migrate config/client/state/logging foundations

### Phase C — migrate features
- move market scan, snapshots, summaries, and Telegram status logic into stable modules
- keep temporary compatibility shims only if needed

### Phase D — governance and command system
- implement executor, risk guard, budget distributor
- implement Telegram command registry and routed agent interface

### Phase E — cleanup and docs
- deprecate or remove obsolete step-script architecture where appropriate
- finalize docs, tests, and startup workflows

## Deliverable standard
When finished, the repo should feel like a coherent product, not a chronology of experiments.

## Output format for your work
As you proceed:
1. explain the migration plan briefly
2. make the edits
3. summarize exactly what changed
4. identify any remaining gaps to the full end state

Start by auditing the current repository and then begin Phase A.
