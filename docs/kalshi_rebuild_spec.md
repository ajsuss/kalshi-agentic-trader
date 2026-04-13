# Kalshi Agentic Trading System – Project Plan

## Introduction

This document outlines a comprehensive plan for building an **agentic trading system** for the Kalshi prediction market.  The goal is to create a modular framework that can **evolve over time** and support automated trading under strict risk‑management controls.  The system uses a **Telegram bot** as the primary interface and is inspired by the **clawbot / openclaw** concept—an “AI assistant running on your own infrastructure” that delegates real work to specialized **skills** or agents.  The original project repository (`kalshi‑agentic‑trader`) already contains a basic framework for reading Kalshi data, scanning markets, taking snapshots and delivering Telegram status updates.  However, significant work remains to realize the fully automated, multi‑agent vision described in the initial design prompt.

### Original Vision

The user’s original prompt described a multi‑tier trading framework with five teams—three **operational teams** (Algorithms, Information‑Media, and Deliberators) and two **oversight teams** (Budget Distributors and Executors).  Operational teams develop quantitative strategies, scrape news and sentiment, and craft high‑conviction theses.  Oversight teams allocate capital, evaluate performance and either approve or veto trades.  A human operator remains in the loop for high‑risk decisions, receiving alerts via a messaging app.  The prompt emphasised **strict logging**, **risk limits** and a structured communication hierarchy.

## Current Repository Overview

The existing repository already contains several important components: | Module/File | Purpose | |---|---| | `app/kalshi_agentic/config.py` | Loads configuration variables (Kalshi base URL, API keys, Telegram secrets) into a `Settings` dataclass. | | `app/kalshi_agentic/kalshi_client.py` | Wraps the Kalshi REST API and supports authenticated GET/POST calls. | | `app/kalshi_agentic/market_scan.py` | Fetches and summarises market pages, scoring markets based on heuristics. | | `app/kalshi_agentic/market_selection.py` | Retrieves and summarises specific markets or events. | | `app/kalshi_agentic/snapshots.py` | Provides snapshot functions to inspect account limits, event snapshots and market snapshots. | | `app/kalshi_agentic/telegram_notifier.py` | Implements a simple wrapper to send messages via Telegram. | | `scripts/step44_telegram_status_bot.py` | A long script that runs a Telegram bot.  It polls for updates and responds to commands such as `/status`, `/state`, `/queue`, `/health`, etc.  For each command, it launches the corresponding step script (e.g., `step43_repo_state_snapshot.py`) and returns the result.  It also manages refresh loops and offset state. | | `docs/codex_handoff.md` | Provides a high‑level description of the current control‑plane, emphasising that the system is still in **dry‑run** mode.  It lists available step scripts and emphasises safety invariants: no live trading by default, risk and execution safeguards must remain intact, and only small, reversible changes should be made. | | `state/codex_seed_state.json` | A fallback state file containing the number of active and retired candidates and a list of gating conditions. | | `state/team_status_seed.json` | Contains initial team statuses and progress metrics for each team. |

These components provide a solid foundation for **data ingestion**, **market scanning** and a **status bot**, but they do not yet implement the multi‑agent structure envisioned in the original prompt.  Moreover, much of the logic lives in ad‑hoc step scripts (e.g., `step45_team_status.py`, `step46_control_plane_digest.py`) that are either missing or incomplete.  The code is not yet organised into reusable “skills” and lacks a dynamic agent manager.

## Proposed Architecture

The objective is to evolve the existing framework into a **modular, agentic system** that can grow and adapt over time.  This new architecture borrows the idea of **clawbot skills**: each agent is a small, self‑contained module that performs a specific task.  Agents can be added, removed or updated without changing the core framework.

### 1. Modular Agents (Skills)

Create an `agents/` directory.  Each agent resides in its own Python module with two core components:

* **Manifest**: a simple JSON or Python dictionary describing the agent’s name, description, allowed commands and required inputs.  This will allow the system to discover available agents and present them to the Telegram bot.
* **Agent Class**: implements a `run()` method with a well‑defined signature (e.g., `def run(self, context: dict) -> dict`).  The context contains input parameters, state and configuration.  The agent returns a structured result and optionally side‑effects (e.g., logs, trade orders).  Agents should not directly perform external side effects (like placing trades); they should return an “intent” that the **Executor** verifies and executes.

Initial agents to build include:

1. **MarketScannerAgent**: wraps the existing `market_scan.fetch_markets_page` and `summarize_markets_page` functions to scan Kalshi markets, score them and return a ranked list.  This agent can take parameters such as market page number, filter criteria or scoring weights.
2. **MarketSelectionAgent**: uses `market_selection.fetch_event_by_ticker` and `summarize_event` to retrieve information for a specific event or market ticker and build a summary.  It will supply context to deliberators or algorithms.
3. **SnapshotAgent**: calls functions in `snapshots.py` to retrieve account limits and market snapshots and logs them.  Useful for health monitoring.
4. **TeamStatusAgent**: aggregates state information from `state/` files (or a database) and returns the current number of active and retired candidates, next best trade, and gating conditions.  This agent will replace the missing `step45_team_status.py` script.
5. **DigestAgent**: synthesizes outputs of other agents and produces a high‑level digest for the operator.  It will eventually replace `step46_control_plane_digest.py`.
6. **BrainLoopAgent**: orchestrates the iterative analysis process, combining scanning, selection and deliberation to create candidate trades.  It should coordinate with the **RiskGuard** and only output recommendations when risk constraints are satisfied.  This agent will replace `step48_brain_loop.py`.
7. **PerformanceAgent**: evaluates strategy performance (win rate, ROI, drawdown) to inform capital allocation.
8. **RefreshAgent**: refreshes market data and resets system state.  It will incorporate the logic found in `step50_refresh_and_decide.py`.

Agents should be stateless except for context and environment variables.  Persistent state (queue of candidates, active trades, historical logs) must be stored in a designated `state/` directory or database.

### 2. Agent Manager

Implement an **AgentManager** class responsible for:

* **Discovery**: scanning the `agents/` directory for available agent manifests and loading their classes dynamically.
* **Registration**: maintaining a registry of agents and exposing metadata (name, description, parameters) to the rest of the system.
* **Execution**: invoking an agent by name, passing context, and capturing results and logs.  The manager should implement safe exception handling and timeouts to prevent runaway tasks.

### 3. Oversight Components

Create a `governance/` package with two key modules:

* **BudgetDistributor**: tracks each team’s performance and allocates the bankroll.  It should load performance metrics from `state/performance.json` (generated by `PerformanceAgent`) and apply simple rules (e.g., allocate more to teams with higher ROI and lower drawdown).  The distributor returns a `budget_allocation` dictionary.  Future improvements could incorporate reinforcement learning.
* **Executor**: the final gatekeeper for trade execution.  It accepts trade intents from agents (e.g., “buy 10 contracts of event X at price Y”) and either approves or rejects them based on capital usage, risk limits and gating conditions.  If an intent is rejected or flagged as suspicious, the executor logs the rationale and sends a notification to the human operator via Telegram.  Actual trade execution should be encapsulated in a `kalshi_trading.py` module with clearly defined functions for placing, modifying or cancelling orders.  In the early stages, this module should return a mock response without placing real trades; the doc emphasises that the current system is **dry‑run** and no live trading should occur until risk safeguards are thoroughly tested.

### 4. Communication Layer

Refactor `step44_telegram_status_bot.py` into a reusable **TelegramBot** class located in `app/telegram_bot.py`.  The bot should:

1. **Register Commands Dynamically**: fetch the list of available agents from `AgentManager` and create commands such as `/run_scanner` or `/run_snapshot` automatically.  In addition, implement high‑level commands like `/digest`, `/brain`, `/budget`, `/performance`, `/refresh`, etc.
2. **Handle Conversations**: for commands that require parameters (e.g., selecting a market), implement interactive messages or simple parsing to extract arguments.
3. **Dispatch and Collect Results**: call the appropriate agent via `AgentManager` and send the structured result back to the chat.  For long‑running tasks, acknowledge receipt and optionally provide progress updates.
4. **Notify on Risk Flags**: integrate with the **Executor** to alert the operator if a proposed trade is blocked or flagged.
5. **Persistence**: maintain the Telegram offset to avoid processing duplicate messages and store conversation history as needed.

### 5. State and Logging

Develop a `state_manager.py` module to centralize reading and writing of state files (active candidates, retired candidates, budgets, performance metrics).  This avoids ad‑hoc JSON reading and ensures atomic updates.  Use the existing `JsonlLogger` class for structured logs, but extend it to include timestamps and agent names for better traceability.  All agent inputs and outputs should be logged; this satisfies the **Global Logging** requirement of the original prompt.

### 6. Risk Management and Gating

Implement a `risk_guard.py` module containing reusable functions to evaluate the safety of candidate trades and update gating conditions.  Example checks include:

* **Position Size Limit**: ensure each trade uses less than a configurable fraction of the bankroll.
* **Daily Loss Limit**: stop trading if cumulative daily losses exceed a threshold.
* **Market Freshness**: similar to the existing `freshness_guard`, avoid markets that are about to close or have stale data.
* **Execution Gate**: ensure market liquidity and spreads are acceptable before placing a trade.

The **Executor** should call these functions before approving any trade intent.  Rejected intents should be logged with the reason and, if necessary, forwarded to the human for manual review (via Telegram).

### 7. Documentation and User Guides

Create comprehensive documentation in `docs/` explaining:

1. **Agent Framework**: how to write a new agent (manifest format, `run()` signature, context fields), how to test it locally and how to integrate it with the Agent Manager.
2. **Oversight Modules**: how budgets are calculated, how the executor makes decisions, and how to adjust risk parameters.
3. **Deployment Guide**: step‑by‑step instructions for setting up the environment (Python version, dependencies), configuring API keys and Telegram tokens, and running the bot.  Include commands to start long‑running loops such as the brain loop (e.g., `scripts/run_brain_loop.sh`).
4. **Human‑in‑the‑Loop Workflow**: guidelines for responding to alerts, overriding trades and adjusting budgets.  Provide sample Telegram commands for everyday tasks (checking status, refreshing data, running digest, etc.).

## Roadmap for Codex

To implement this architecture, Codex should follow a phased approach.  Each phase builds upon the previous one and should be committed to the repository with clear commit messages.

### Phase 1 – Cleanup & Modularization

1. **Create an `agents/` directory** and an abstract `BaseAgent` class defining the interface (`manifest`, `run()`).
2. **Refactor existing functionality into agents**:
   - Move `market_scan` logic into `MarketScannerAgent`.
   - Move `market_selection` functions into `MarketSelectionAgent`.
   - Move snapshot functions into `SnapshotAgent`.
3. **Implement `AgentManager`** capable of loading these agents.
4. **Set up the `state_manager`** to load and update JSON state files atomically.
5. **Add unit tests** for each agent to verify that they return structured outputs when given sample contexts.

### Phase 2 – Governance & Risk

1. **Implement `BudgetDistributor`** with a simple rule‑based allocation based on ROI and drawdown.
2. **Implement `RiskGuard`** with the checks described above.
3. **Implement `Executor`** to receive trade intents and apply risk checks.  For now it should return mock responses and log all decisions.
4. **Add `TeamStatusAgent` and `PerformanceAgent`** to generate performance metrics and team status reports (replacing the missing step scripts).

### Phase 3 – Telegram Bot Refactor

1. **Develop `TelegramBot` class** that loads commands dynamically from `AgentManager` and oversight modules.
2. **Replace `step44_telegram_status_bot.py`** with this new class and update the `ops/run_status_bot.sh` script to point to it.
3. **Implement interactive command handling** for parameters (e.g., allow `/scan page=1 filter=policy` syntax).
4. **Integrate risk‑alert notifications**: connect `Executor` so that flagged trades generate immediate Telegram messages to the operator.

### Phase 4 – Brain Loop & Advanced Agents

1. **Implement `BrainLoopAgent`** that orchestrates scanning, selection and decision making across multiple agents.  It should accept a context with budget information and return recommended trade intents.  Initially, it can call `MarketScannerAgent` and `MarketSelectionAgent` in sequence.
2. **Extend agents** to support more strategies.  For example, create `NewsSentimentAgent` to pull news via an external API (e.g., Twitter or Tavily) and provide sentiment scores; `DeliberationAgent` to synthesise data from multiple sources; `RapidResponseAgent` to execute quick trades with pre‑approved budgets.
3. **Implement performance feedback loops**: update the `BudgetDistributor` based on `PerformanceAgent` outputs.

### Phase 5 – Documentation and Deployment

1. **Write detailed docs** on adding new agents and customizing budgets and risk parameters.
2. **Create example config files** for `.env` variables, API keys and Telegram tokens.
3. **Update `README.md`** to explain how to run the bot in dry‑run mode and how to enable live trading once comfortable with risk safeguards.
4. **Provide sample usage scenarios** (e.g., scanning markets, running a daily digest) with expected outputs.

## Prompt for Codex

When you are ready to engage Codex to work on this project, provide the following structured prompt (update `repo_path` and branch names as needed):

> **Prompt to Codex**
>
> *Repository:* `ajsuss/kalshi‑agentic‑trader` (branch `codex‑cloud‑onboarding`)
>
> *Objective:* Refactor the project into a modular, agentic system as described in `docs/kalshi_project_plan.md`.  Implement the `agents` framework, Agent Manager, governance modules, risk guard, Telegram bot refactor, and new agents as outlined in the plan.  Write unit tests and update documentation accordingly.  Maintain the safety invariants from the original `codex_handoff.md` (no live trading by default; risk and execution safeguards intact).
>
> *Tasks:*  
> 1. Set up the `agents/` directory and implement the `BaseAgent` abstract class.  
> 2. Convert existing functionality into modular agents (MarketScannerAgent, MarketSelectionAgent, SnapshotAgent, etc.) and implement the `AgentManager`.  
> 3. Create governance modules (`BudgetDistributor`, `Executor`) and the `RiskGuard`.  
> 4. Implement the `state_manager` and unify logging.  
> 5. Refactor the Telegram bot to dynamically register commands and integrate risk alerts.  
> 6. Add new agents for team status, performance, digest and brain loop.  
> 7. Write documentation and unit tests for all components.
>
> *Constraints:*  
> – Do not remove existing risk‑management logic without adding equivalent or stronger safeguards.  
> – Maintain compatibility with the current dry‑run mode; live trading should only be enabled via an explicit configuration flag.  
> – All new modules must log their inputs, outputs and decisions.  
> – Use the existing Kalshi API client for data ingestion; do not hard‑code API keys or secrets.  
>
> *Deliverables:* Updated code implementing the agentic framework, new documentation in `docs/`, and tests verifying agent outputs and risk checks.

Providing this prompt to Codex will guide it to implement the architecture detailed in this plan.  You can then iterate on the implementation, add new agents, adjust risk parameters and refine strategies.  The modular design ensures that your Kalshi trading system can grow organically and remain maintainable while preserving strong safety controls.