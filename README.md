# Trading Bot

A modular trading assistant that fetches market data, scans symbols with pluggable strategies, and (optionally) routes orders via Interactive Brokers (IBKR).

⚠️ Disclaimer
This software is for educational purposes only and comes with no warranty. Trading involves substantial risk. Use at your own responsibility.

---

## Contents
- Features
- Architecture
- Quickstart
- Configuration
- Usage
- Project Structure
- Development
- CI / Automation
- Troubleshooting
- Roadmap
- Contributing
- License

---

## Features
- Live or delayed market data polling (configurable interval)
- Scanners to evaluate many symbols quickly
- Strategies as standalone modules (easy to add/replace)
- Optional IBKR connectivity for paper/live execution
- Simple logging, basic risk checks, and environment-based config

---

## Architecture

            +-----------------+
            |  Data Provider  |  <- external APIs / feeds
            +--------+--------+
                     |
                     v
+------------+   +-------+   +-----------+
|  scanner   +-->|  bus  +-->| strategy  |  -> signals (buy/sell/hold)
+------------+   +-------+   +-----------+
                                    |
                                    v
                               +---------+
                               |  bot    |  -> orders (paper / IBKR)
                               +---------+
                                    |
                                    v
                               +---------+
                               | broker  |  (IBKR)
                               +---------+

- scanner.py — symbol scanning & signal triggering
- strategy.py — strategy interface & implementations
- bot.py — turns signals into orders with basic risk checks
- ibkr.py — connection & order routing to Interactive Brokers
- utils.py — helpers (logging, time, parsing, etc.)
- main.py — orchestration/entry-point (if used)

---

## Quickstart

Prerequisites
- Python 3.10+
- Git
- (Optional) IBKR Gateway/TWS installed and running locally

Setup
1) git clone git@github.com:razvanmatei3586/trading-bot.git
2) cd trading-bot
3) Create and activate a virtualenv
   - python -m venv .venv
   - macOS/Linux:  source .venv/bin/activate
   - Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
4) Install dependencies
   - pip install -r requirements.txt
5) Create a local config
   - cp .env.example .env   (if you have one), then edit values

---

## Configuration

Set environment variables (via .env or your shell). Example:

# Data
DATA_PROVIDER=yahoo              # or polygon/alpaca/etc. if supported
DATA_API_KEY=your_key_if_needed
SYMBOLS=AAPL,MSFT,SPY

# Scheduling
POLL_INTERVAL_SEC=60
RTH_ONLY=true                    # Regular Trading Hours, if supported

# IBKR (optional)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497                   # default paper port
IBKR_CLIENT_ID=1
PAPER_TRADING=true               # safety valve

# App
LOG_LEVEL=INFO
TZ=Europe/Bucharest

IBKR note:
In TWS/Gateway, enable: Configure → API → Settings → “Enable ActiveX and Socket Clients” and confirm the port matches IBKR_PORT.

---

## Usage

Common entry points (adjust to your files):

- Run the main loop (scheduler/orchestrator)
  python main.py

- Scan a set of symbols without placing orders (dry-run)
  python scanner.py --symbols "AAPL,MSFT,SPY" --interval 1m --dry-run

- Run a specific strategy
  python strategy.py --name mean-reversion --symbols "AAPL,MSFT" --lookback 100

- Route paper orders via IBKR (if configured)
  python bot.py --execute --symbols "AAPL,MSFT"

Typical flags you might support:
--symbols "AAPL,MSFT"  (comma-separated symbols)
--interval 1m|5m|1d    (bar/timeframe)
--dry-run              (no orders, just evaluate signals)
--name <strategy>      (select strategy)
--lookback <n>         (bars to look back)

---

## Project Structure

See SUMMARY.md for a browsable index of files (it includes GitHub links and a CDN fallback).

Typical layout:
.
├── bot.py
├── ibkr.py
├── main.py
├── scanner.py
├── strategy.py
├── utils.py
├── requirements.txt
├── SUMMARY.md
└── scripts/
    ├── generate_summary.py
    └── (other utilities)

---

## Development

- Lint & format (if using Ruff)
  ruff check .
  ruff format .

- Tests (if using pytest)
  pytest -q

- Type checking (if using mypy)
  mypy .

Optional pre-commit:
  pip install pre-commit
  pre-commit install
(then it runs on every commit)

---

## CI / Automation

- SUMMARY auto-update: a GitHub Action regenerates SUMMARY.md on push so reviewers get fresh links.
- (Optional) GitHub Pages mirror: you can deploy selected files under /docs to get stable “Pages” links for code review.

If you add/modify workflows later, mention them here and add a status badge.

---

## Troubleshooting

- 403/permissions on CI auto-commit
  Ensure repo setting: Settings → Actions → General → Workflow permissions → “Read and write”.

- IBKR connection refused
  Make sure TWS/Gateway is running, API is enabled, correct host/port, and clientId is unique.

- Timezones / RTH
  Provider timestamps may be UTC; set TZ and/or convert times in your code. If RTH_ONLY=true, skip pre/post sessions.

- Rate limits or 429s
  Increase POLL_INTERVAL_SEC, reduce symbol count, or upgrade your data tier.

---

## Roadmap

- [ ] Backtesting module (historical data + metrics)
- [ ] More strategies (momentum, breakout, pair trading)
- [ ] Risk management (position sizing, max exposure, stops)
- [ ] Docker image & Compose stack
- [ ] Metrics export (Prometheus / CSV) and dashboards

---

## Contributing

Issues and PRs are welcome. Please run lint/format/tests before opening a PR.

---

## License

Choose a license (e.g., MIT) and add it as LICENSE.
