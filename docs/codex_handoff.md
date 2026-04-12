# Codex Handoff: Kalshi Agentic Trader

## Purpose
This document provides a **repo-visible control-plane handoff** so cloud tasks can reason about the latest intended dry-run state even when local runtime logs are unavailable (logs are gitignored).

## Architecture (Current)
The system is a guarded, step-oriented control plane:

1. Candidate/review/executor pipeline produces order-submission candidates.
2. Risk and execution safeguards evaluate candidate readiness.
3. Guarded live path attempts are blocked unless all gates pass.
4. Retirement marks stale executor-approved candidates as retired.
5. Active queue view separates active and retired candidates.
6. Operator console summarizes control-plane status.

Key scripts:
- `scripts/step26_guarded_live_order_path.py` (guarded send path; step37 record kind)
- `scripts/step29_operator_console.py` (operator summary; step40 record kind)
- `scripts/step39_retire_stale_candidates.py` (retirement)
- `scripts/step42_active_queue_view.py` (active vs retired queue)
- `scripts/step43_repo_state_snapshot.py` (repo-visible snapshot, added for cloud-safe state reasoning)

## Current Known Dry-Run State (Operator-Provided Truth)
When local authoritative logs are not visible to cloud tasks, use this known state:

- active queue count: `0`
- retired candidate count: `1`
- executor actionable_now: `false`
- previously executor-approved Philadelphia spread candidate: `retired`
- guarded live path blocked by:
  - `freshness_guard`
  - `execution_gate`
  - `market_preflight`
  - `confirm_live_send`

## Safety Invariants (Do Not Relax)
- Do not enable live trading by default.
- Do not remove risk or execution safeguards.
- Do not modify order execution behavior without explicit operator direction.
- Keep changes small, additive, and reversible.

## Historical vs Current Truth
- **Historical**: append-only runtime logs under `logs/` (local, gitignored).
- **Current truth for cloud tasks**:
  1. Prefer newest authoritative runtime records if available locally.
  2. Otherwise use committed seed fallback in `state/codex_seed_state.json`.

## Operator Interaction
The operator can update `state/codex_seed_state.json` when local state changes and cloud tasks need accurate context before log sync.

## Minimal Operator Commands
For a lightweight control loop with Telegram status queries:

1. Local snapshot (logs-first, seed fallback):
   - `python3 scripts/step43_repo_state_snapshot.py`
2. Telegram `/status` responder (safe, read-only):
   - `python3 scripts/step44_telegram_status_bot.py --run-once`
   - or run continuously: `python3 scripts/step44_telegram_status_bot.py`
   - or via helper: `./ops/run_status_bot.sh` (auto-installs `requirements-step2-min.txt` if bot deps are missing)
3. Supported Telegram commands:
   - `/status` or `/state`: normalized control-plane snapshot
   - `/queue`: active/retired queue summary
   - `/health`: bot and snapshot freshness summary
   - `/teams`: current team-by-team status snapshot
   - `/progress`: development/control-plane rollout progress
   - `/nexttrade`: current next-best-trade readiness summary
   - `/digest`: compact control-plane and next-trade digest
   - `/cycle`: one read-only deliberation cycle recommendation
   - `/brain`: latest periodic brain-loop iteration status
   - `/performance`: seed-backed performance and brain-loop stats snapshot
   - `/refresh`: start refresh pipeline + decision chain in background (read-only, single-flight)
   - `/refreshstatus`: latest refresh pipeline summary (or running status if still in progress); stale refresh PID markers are auto-cleared
   - `/refreshreset`: clear stale refresh lock when no refresh is currently running
4. Team status seed snapshot:
   - `python3 scripts/step45_team_status_snapshot.py`
   - step45 derives control-plane context from step43 (runtime logs first, seed fallback)
5. Control-plane digest snapshot:
   - `python3 scripts/step46_control_plane_digest.py`
6. Read-only deliberation cycle:
   - `python3 scripts/step47_deliberation_cycle.py`
7. Periodic brain loop (read-only):
   - `python3 scripts/step48_periodic_brain_loop.py --iterations 5 --sleep-seconds 60`
   - or helper: `./ops/run_brain_loop.sh --iterations 5 --sleep-seconds 60`
8. Performance snapshot:
   - `python3 scripts/step49_performance_snapshot.py`
9. Refresh + decide chain:
   - `python3 scripts/step50_refresh_and_decide.py`

`step44` does not place orders. It is read-only and answers `/status`, `/state`, `/queue`, `/health`, `/teams`, `/progress`, `/nexttrade`, `/digest`, `/cycle`, `/brain`, `/performance`, `/refresh`, `/refreshstatus`, and `/refreshreset` using step43–step50 snapshots/logs.
