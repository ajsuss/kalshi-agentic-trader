# Local Operator Runbook (Dry-Run Safe)

This runbook is the canonical local workflow for the rebuild-era Telegram operator app.

## 1) Safe reset
From repo root:

```bash
./ops/reset_local_runtime.sh --archive-logs
```

What this does:
- stops running Telegram app / legacy status bot / brain loop / refresh loop processes
- clears runtime offsets, pid markers, and transient output files
- archives runtime logs when `--archive-logs` is provided

What this does **not** do:
- does not modify `.env`
- does not delete secrets
- does not delete tracked `state/*.json`
- does not arm live trading

## 2) Bootstrap local environment

```bash
./ops/bootstrap_local.sh
```

This script:
- creates/verifies `.venv`
- installs dependencies
- validates required Telegram/Kalshi env values and secret file paths
- runs Telegram app self-check
- prints pass/fail/warn checklist

## 3) Start the canonical Telegram app

```bash
./ops/run_telegram_app.sh
```

Alternative equivalent:

```bash
python -m app.interfaces.telegram.main
```

## 4) Confirm app is working
- Send `/ping` and expect a `pong ...` response.
- Send `/help` and verify command list appears.
- Send `/policy` and verify it reports live-trading default as disabled.

## 5) First commands to send in Telegram
1. `/help` (read-only command list)
2. `/status` (control-plane snapshot)
3. `/team` (team status agent output)
4. `/digest` (high-level digest)
5. `/markets` (live read-only top candidates)
6. `/market <TICKER>`
7. `/event <EVENT_TICKER>`
8. `/scanstatus`
9. `/recommend`
10. `/candidates`
11. `/nexttrade`
12. `/why_nexttrade` (why top pick won)
13. `/review <TICKER> YES 1 0.50` (executor dry-run policy review)

## 6) Stop cleanly
- Press `Ctrl+C` in the terminal running `run_telegram_app.sh`, or run:

```bash
./ops/reset_local_runtime.sh
```

## 7) Dry-run vs live-disabled status
- Default mode is dry-run.
- No live execution is performed by Telegram commands in this runbook.
- Live mode requires explicit arming (`EXECUTION_MODE=live` and `KALSHI_LIVE_TRADING_ARMED=1`) plus executor/policy approval.

## 8) Temporary legacy wrappers still in migration
The following scripts remain temporary compatibility wrappers and now route into new modules:
- `scripts/step43_repo_state_snapshot.py`
- `scripts/step45_team_status_snapshot.py`
- `scripts/step46_control_plane_digest.py`
