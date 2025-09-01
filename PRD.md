# Trading Bot — Product Requirements Document (PRD)

Version: 1.0  
Owner: Razvan + ChatGPT (project collaborator)  
Status: Draft (ready for implementation)

---

## 1) Problem & Context

Develop a practical trading assistant that:
1) fetches market data on a schedule,
2) generates signals via pluggable strategies,
3) (optionally) routes paper/live orders via Interactive Brokers (IBKR),
4) logs everything for review and later backtesting.

This is an educational/experimental project, not production trading software.

---

## 2) Goals & Non-Goals

Goals (MVP)
- Poll symbols list at a configurable interval (e.g., 60s), optionally RTH-only.
- Run one or more strategies against the latest data and produce BUY/SELL/HOLD signals.
- Paper-trade execution with position tracking and basic risk controls.
- Optional IBKR connectivity (place simulated or small-sized real orders when explicitly enabled).
- Transparent logs, metrics, and a simple CLI (or very lightweight web UI).
- Deterministic configuration via `.env` and clear README/SUMMARY.

Stretch Goals (later)
- Backtesting with historical data, sharpe/winrate metrics.
- Multi-provider data abstraction (Yahoo/Polygon/Alpaca/etc).
- Strategy catalog (mean-reversion, momentum, breakout, pairs).
- GitHub Pages “report” for daily signal summaries.

Non-Goals (for now)
- High-frequency trading or sub-second latency.
- Options/futures, portfolio margining, complex order types.
- Full-blown OMS/EMS or risk engine; we’ll keep it minimal and auditable.

---

## 3) Target Users & Use Cases

Users
- You (project owner) and technical users comfortable with Python + Git.

Primary Use Cases
- Run periodic scans on a watchlist to surface buy/sell opportunities.
- Evaluate strategies safely (dry-run / paper) before any real execution.
- Log and review decisions; iterate on strategy code with confidence.
- Optional: place small-size orders with IBKR once confident.

---

## 4) Scope (MVP)

Functional
- Symbol management: read from ENV (SYMBOLS=AAPL,MSFT) and/or simple file.
- Data polling: timeframe (1m/5m/1d), RTH filter, retry/backoff on errors.
- Strategy interface: deterministic input → signal output (+ confidence).
- Signal bus: normalize and distribute signals to the bot.
- Execution (paper): position sizing, max open positions, per-trade cap.
- Execution (IBKR optional): place/cancel/modify simple MKT/LMT orders.
- Persistence: append-only trades/positions ledger (CSV or SQLite).
- Observability: structured logs (JSON or human-readable), minimal metrics.

Non-Functional
- Reliability: safe defaults (dry-run by default), fail-closed if config missing.
- Simplicity: minimal dependencies; runnable on a laptop.
- Maintainability: clear modules, tests for core logic.
- Security: no secrets in code; read from environment only.

Out of Scope (MVP)
- Multi-account routing; advanced risk models; portfolio optimization.

---

## 5) High-Level Architecture

Data Provider → Scanner → Strategy → Signal Bus → Bot (Risk/Orders) → Broker (IBKR or Paper)
- scanner.py: pulls latest bars/quotes, bundles inputs for strategies.
- strategy.py: interface + concrete strategies (e.g., mean-reversion).
- bot.py: consumes signals, checks risk, generates orders, updates ledger.
- ibkr.py: broker adapter (paper mode + real IBKR when enabled).
- utils.py: env, time, logging, math helpers.
- main.py: orchestrates scheduling, startup/shutdown.

---

## 6) Configuration (ENV)

DATA_PROVIDER: yahoo (default)  
DATA_API_KEY: string (optional)  
SYMBOLS: comma-separated symbols  
POLL_INTERVAL_SEC: integer (e.g., 60)  
RTH_ONLY: true|false  
LOG_LEVEL: DEBUG|INFO|WARN|ERROR  
TZ: e.g., Europe/Bucharest  
PAPER_TRADING: true|false (default true)  
IBKR_HOST: 127.0.0.1  
IBKR_PORT: 7497 (paper) / 7496 (live)  
IBKR_CLIENT_ID: integer (e.g., 1)  
RISK_MAX_POSITION_VALUE: float (e.g., 1000 per position)  
RISK_MAX_CONCURRENT_POSITIONS: int (e.g., 5)

---

## 7) Functional Requirements & Acceptance Criteria

FR1: Data Polling
- The system shall fetch latest price/bar data for all configured symbols every POLL_INTERVAL_SEC.
- If RTH_ONLY=true, the system shall skip pre/post-market intervals for US equities.
- On transient errors, it shall retry with exponential backoff (max 3 attempts).
Acceptance: When running for 10 minutes with 3 symbols, logs show periodic fetches, and temporary failures recover without crash.

FR2: Strategy Execution
- Strategies shall implement a common interface (name, parameters, compute()).
- compute() returns: {signal: BUY|SELL|HOLD, confidence: 0..1, metadata: dict}.
- Multiple strategies can run; a default “demo” strategy is provided.
Acceptance: Strategy unit tests show deterministic outputs for fixed inputs; logs include signal + confidence.

FR3: Signal Bus
- Normalizes per-symbol strategy outputs into a unified stream with timestamps.
- Can be tapped to print or save signals for audit.
Acceptance: Signals for 2+ strategies appear in a single normalized stream, with symbol and UTC timestamp.

FR4: Paper Trading Engine
- Maintains a positions map and a trades ledger.
- Given a BUY/SELL signal and risk budget, it calculates quantity using last price and caps by RISK_MAX_POSITION_VALUE.
- Prevents exceeding RISK_MAX_CONCURRENT_POSITIONS.
Acceptance: End-to-end dry-run shows trades in ledger, positions table consistent, and caps enforced.

FR5: IBKR Integration (Optional)
- If PAPER_TRADING=false and IBKR_* set, the bot can submit MKT or LMT orders.
- Provides basic order status tracking and cancellation on shutdown.
- Fails closed (no orders) if connection not available.
Acceptance: With Gateway running, a tiny test order can be placed and reported as filled/canceled in logs.

FR6: Persistence & Logs
- Trades and positions shall be persisted to CSV or SQLite (pick one; CSV is simplest).
- All actions (fetch, signal, order) shall be logged with level INFO+.
Acceptance: After a session, CSV/DB contains the operations; logs are readable and complete.

FR7: CLI
- Provide CLI flags on key modules (scanner, strategy, bot, main).
- Provide --dry-run to ensure no orders are placed.
Acceptance: Invoking “python scanner.py --symbols AAPL --dry-run” prints signals without creating trades.

---

## 8) Data & Interfaces

Data shapes (conceptual)
- Bar: symbol, ts, open, high, low, close, volume
- Quote (optional): symbol, ts, bid, ask, last
- Signal: symbol, ts, strategy, signal (BUY/SELL/HOLD), confidence (0..1), meta
- OrderRequest: symbol, side (BUY/SELL), qty, type (MKT|LMT), limit_price?, idempotency_key
- OrderStatus: id, status (NEW|FILLED|CANCELED|REJECTED), filled_qty, avg_price
- Position: symbol, qty, avg_cost, mkt_value, unrealized_pnl
- Trade (ledger): ts, symbol, side, qty, price, order_id, strategy, note

Module interfaces (Pythonic, simplified)
- Strategy.compute(bars) → Signal
- Bot.on_signal(signal) → Optional[OrderRequest]
- Broker.place(order_req) → OrderStatus
- Broker.get_position(symbol) → Position
- Ledger.append(trade) → None

---

## 9) Risk Controls (MVP)

- Hard caps:
  - Per-trade maximum notional (RISK_MAX_POSITION_VALUE).
  - Max concurrent open positions (RISK_MAX_CONCURRENT_POSITIONS).
- Dry-run default.
- No averaging down; no pyramiding (MVP).
- Optional stop placeholder: fixed percentage or ATR-based (later).

Acceptance: With caps set low, bot never exceeds limits despite repeated BUY signals.

---

## 10) Observability

- Logging: INFO for normal ops, DEBUG for development.
- Health line every N cycles: “ok: symbols=3 next=60s”.
- Optional metrics counters in memory (fetched_bars_total, signals_total, orders_total).

---

## 11) Security & Compliance

- Secrets only via environment; no keys in repo.
- IBKR usage gated by PAPER_TRADING flag; explicit opt-in for live trading.
- Educational disclaimer in README.

---

## 12) Performance

- Symbol count target (MVP): 10–50 symbols per minute on laptop.
- Single-threaded acceptable; later, parallel fetch by batch if needed.
- Latency target: produce signals within 1 polling interval.

---

## 13) Testing

Unit Tests
- Strategy logic (deterministic fixtures).
- Risk sizing (edge cases: zero price, tiny caps).
- Signal normalization.

Integration Smoke Tests
- End-to-end dry-run with 3 symbols for 5 cycles → trades ledger populated.
- IBKR connector: connection open/close, no-op in dry-run.

---

## 14) Rollout & Milestones

M1: MVP loop working (fetch → strategy → signal → paper trades → logs)  
M2: IBKR optional execution path + ledger persistence  
M3: Backtesting scaffolding + additional strategies  
M4: Pages report / dashboards (optional)

---

## 15) Success Metrics

- Technical: zero crashes in a 60-minute run; retries recover transient failures.
- Usability: can add a new strategy file with <30 lines and run it without touching core modules.
- Safety: no live orders unless PAPER_TRADING=false and broker is reachable.

---

## 16) Dependencies

- Python 3.10+, requests/httpx (if provider needs), pandas (optional), ib_insync or IB API (if used).
- IBKR Gateway/TWS (optional), market data provider (Yahoo by default).

---

## 17) Open Questions

- Which historical source for backtesting (Yahoo vs. paid API)?
- Preferred persistence (CSV vs SQLite) for trades/positions?
- Minimal web UI now or CLI-only for MVP?
- Consolidated clock/scheduler vs. OS cron?

---

## 18) Glossary

- RTH: Regular Trading Hours.
- Paper trading: simulated execution with real prices but no capital at risk.
- Signal: strategy output indicating action tendency.

---

## 19) Acceptance Demo (What we will show)

- Start bot in dry-run; observe periodic data fetches and signals for 3 symbols.
- Enable paper trading; see trades ledger updates and risk caps enforced.
- (If desired) connect IBKR paper and submit a tiny test order, then cancel.

---

## 20) Risks & Mitigations

- Data reliability: add retries and clear error logs; allow switching providers.
- Overfitting strategies: keep simple baselines and insist on out-of-sample tests.
- IBKR connectivity quirks: fail closed; implement basic status polling.

---

## 21) File Map (expected)

- main.py — scheduler/entrypoint
- scanner.py — polling + packaging inputs for strategies
- strategy.py — base interface + 1–2 concrete strategies
- bot.py — risk checks, order sizing, calls broker
- ibkr.py — adapter (paper + live)
- utils.py — env/log/time helpers
- requirements.txt, README.md, SUMMARY.md
- scripts/ — generate_summary.py, mirror_for_pages.py (optional)
- tests/ — unit/integration tests (to be added)

---

## 22) Future Work

- Backtesting engine with metrics (CAGR, Sharpe, MaxDD).
- Portfolio sizing (Kelly fraction, volatility scaling).
- Multi-asset support and multiple brokers.
- Dockerization.

---

## 23) Legal

This project is for educational use only and is not financial advice. Use at your own risk.

---
