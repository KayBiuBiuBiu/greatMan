# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

A monorepo containing multiple personal projects across different platforms and languages:

- **stock-price-alert** — Python quantitative stock monitoring tool (multi-strategy, stock screening, risk control, backtesting)
- **TicketAssistant** — Python script for ticket purchase assistance (Damai/Big麦 automation)
- **social-heat-crawler** — Python tool for social media trend research (Douyin, Xiaohongshu) with browser automation
- **projects/wechat-mini/** — WeChat Mini Program projects (family party games, meal suggestions, pet feeding assistant)
- **templates/** — Reusable starter templates
- **shared/** — Shared utilities and code
- **archive/** — Retired or experimental work

## Development Conventions

See `docs/CONVENTIONS.md` for workspace structure. Key principles:

- Projects are organized by platform: `projects/wechat-mini/`, `projects/mobile-app/`, `projects/web-app/`, `projects/backend/`
- Time-based naming: `yyyy-mm-dd-project-name` (e.g., `2026-04-26-family-party-games`)
- Each project has: `README.md`, `docs/`, `.env.example`, `CHANGELOG.md`
- Git strategy: monorepo for dependency sharing

## Common Development Tasks

### stock-price-alert (Python)

**Setup:**
```bash
cd stock-price-alert
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**Running:**
```bash
python run_alert.py                      # Main monitoring loop
python run_alert.py --scan               # Stock screening
python run_alert.py --once --no-notify   # Single poll, no notifications
python run_alert.py --backtest-code 600711  # Run backtest for a stock code
python quant_cli.py daily-select         # Quantitative daily screening
```

**Testing:**
```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/
```

**Key Files:**
- `run_alert.py` — Main entry point
- `stock_scanner.py` — Stock screening logic
- `quote_eastmoney.py` — Market data (EastMoney API)
- `strategy_engine.py` — Trading signals and strategy
- `risk_control.py` — Position sizing, stop loss, take profit
- `config.json` / `config.example.json` — Configuration
- `quant_core/` — Quantitative core (data, strategy, screening, backtesting, risk control layers)

**Config Notes:**
- `run_only_in_trading_hours` (default `true`) — Skip HTTP requests outside market hours
- `kline_store` — Local SQLite caching for daily K-lines (default `enabled: true`)
- `data_health` — HTTP failure tracking and exponential backoff (default `enabled: true`)
- `logging` — JSON-line logging to `logs/run_alert.jsonl` (default `enabled: true`)
- Schema validation: `config_schema.json` validates config.json on startup

### TicketAssistant (Python)

**Setup:**
```bash
cd TicketAssistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Running:**
```bash
python main.py
```

First run opens Chrome for QR code login; Cookie is saved to `cookies.json` for reuse.

**Ordering Modes:**
- `order_mode: api` — Uses Alipay mtop H5 signing (no reverse-engineering needed for browser, requires `_m_h5_tk` Cookie)
- `order_mode: browser` — Selenium-based clicking (slower ~2–3s, no sign required)

### social-heat-crawler (Python)

**Setup:**
```bash
cd social-heat-crawler
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**Running:**
```bash
# Save login state (first time)
python scripts/save_login_state.py --platform xiaohongshu
python scripts/save_login_state.py --platform douyin

# Crawl content + score + export top N
python scripts/run_crawl.py --platform xiaohongshu --keyword "旅行" --top 5
python scripts/run_crawl.py --platform douyin --keyword "旅行" --top 5

# (Optional) Rewrite text using LLM
python scripts/run_rewrite_text.py

# Semi-automated publishing
python scripts/run_prepare_publish.py --platform xiaohongshu
```

**Key Concepts:**
- Uses Playwright with saved browser state (`storage_state_*.json`)
- Heat score algorithm in `scoring.py` based on engagement metrics
- Deduplication by MD5 fingerprint of title + first image URL
- Selector updates live in `crawlers/selectors_xhs.py` and `crawlers/selectors_douyin.py`
- `--demo` mode runs export/sorting without Playwright (useful for dependency checking)

**Environment Variables:**
- `SHT_XHS_EMULATE_MOBILE` — 0 for desktop UA (matches Codegen), 1 for mobile
- `XHS_DEBUG=1` — Save failed selector HTML to debug dir
- `NO_COLOR=1` — Disable terminal colors

### family-party-games (WeChat Mini Program)

**Setup:**
1. Open WeChat Developer Tools
2. Import project: select `projects/wechat-mini/2026-04-26-family-party-games`
3. Compile type: MiniProgram, AppID: `wxce58d943a0f4a80e`
4. Enable Cloud Development and deploy `cloudfunctions/roomService`
5. Click "Compile"

**Structure:**
- `app.js` / `app.json` — App entry and config
- `pages/` — Page components (index, play, setup, undercover)
- `packageGames/` — Lazy-loaded game packages
- `cloudfunctions/roomService/` — Backend cloud functions for multiplayer sync
- `data/game-data.js` — Game content (word pairs, tasks, trivia)
- `utils/` — Utility functions (random, storage)
- `docs/` — Game database specs and debugging guides

**Building/Compiling:**
- Use WeChat Developer Tools (no npm/build step; WXML is native)
- Organize game logic in `packageGames/<game-name>/` for code splitting
- Cloud functions go in `cloudfunctions/<service>/`

## Architecture Notes

### stock-price-alert Data Pipeline

1. **Quote Fetch** — `quote_eastmoney.py` pulls real-time quotes and K-lines from EastMoney
2. **Strategy Engine** — `strategy_engine.py` evaluates signals (moving averages, box patterns)
3. **Risk Control** — `risk_control.py` calculates position sizing, stop loss, take profit
4. **Notifications** — Multi-channel: macOS notifications, email, WeChat Work (企微)
5. **Logging** — Optional JSON-line logging to `logs/run_alert.jsonl` for observability
6. **Data Health** — `data_health.py` tracks HTTP failures per host with exponential backoff

### social-heat-crawler Flow

1. **Login State** — Browser automation stores `storage_state.json` (Playwright managed)
2. **Crawl** — Playwright navigates, scrolls, collects DOM data using CSS selectors
3. **Score** — Heat algorithm combines likes, comments, shares, saves
4. **Dedup** — Fingerprint-based deduplication across runs
5. **Export** — JSON + local media files
6. **Publish** — Optional text rewrite; semi-automated launch of creator center

### family-party-games Multiplayer Flow

1. **Room Creation** — Host generates 4-digit PIN and creates room via cloud function
2. **Room Join** — Guests enter PIN and join the same room
3. **Sync** — Cloud function broadcasts game state to all participants
4. **Game Play** — Each game (Undercover, Drawing, etc.) implements turn-based logic
5. **Results** — Final scores/records stored locally or in cloud

## Configuration and Secrets

- **Environment Variables:** Each project has `.env.example` — copy to `.env` for local overrides
- **Credentials:** Do NOT commit `.env`, `cookies.json`, or API keys
- **Config Validation:** `stock-price-alert` uses `config_schema.json` to validate on startup

## Testing

### stock-price-alert
```bash
cd stock-price-alert
python3 -m pytest tests/ -v
```

Tests cover sector BK caching, trend slippage detection, HTTP mocking with `responses`, and deduplication logic.

### Others
- **social-heat-crawler** — Manual Playwright testing (browser-based)
- **family-party-games** — WeChat Developer Tools simulator
- **TicketAssistant** — Manual integration testing with live Damai API

## Git and PR Strategy

- Use conventional commits: `feat(project-name):`, `fix()`, `chore()`, `docs()`
- Prefix commit messages with affected project for monorepo clarity
- Example: `feat(stock-price-alert): add sector-based position sizing`

## Performance and Observability

### stock-price-alert
- **Kline Caching** — Local SQLite for daily K reduces EastMoney API load
- **Realtime Hub** — Background thread polls quotes (optional, default enabled)
- **Data Health** — HTTP failure tracking prevents cascade outages; exponential backoff
- **Logging** — JSON structured logs to `logs/run_alert.jsonl` (rotating)
- **Trend Suppression** — Post-outage trend alerts are suppressed for N rounds to reduce noise

### social-heat-crawler
- **Deduplication** — Fingerprint-based, persists across runs to prevent re-crawling
- **Playwright Overhead** — Browser startup ~500ms; use `--demo` for quick export-only runs
- **Selector Fallback** — CSS selectors have multiple candidates; logs warnings on partial failures
- **Headless/Headed** — Toggle `headless` in `.env` for debugging or manual interaction

## Useful Scripts and Utilities

### stock-price-alert
- `python run_alert.py --check-bk` — Verify watchlist sector mappings
- `python run_alert.py --test-notify` — Test notification channels (macOS, email, WeChat)
- `python auto_tune_accuracy.py --dry-run --days 7` — Backtest-driven parameter tuning preview
- `python ml_train.py --days 180 --model-out data/ml_bearish_nb.json` — Train bearish probability model

### social-heat-crawler
- `--search-sort hot|new|general` — Filter by trending/latest/default
- `--min-heat <score>` — Filter by minimum heat score before exporting top N
- `--no-dedup` — Skip fingerprint deduplication
- `--food-pack` — Use food-specific keyword set (Xiaohongshu only)
- `--demo` — Export-only mode (no Playwright)

## Troubleshooting

**stock-price-alert**
- Market hours check: `run_only_in_trading_hours` defaults to `true`; set to `false` to poll 24/7
- Config validation errors: Check `config_schema.json` and error path in startup message
- API failures: Check `data_health` logging and `sources.ssl_verify` for certificate issues

**social-heat-crawler**
- Selectors broken after site redesign: Update CSS in `crawlers/selectors_xhs.py` or `crawlers/selectors_douyin.py`
- Login expired: Delete `data/storage_state_*.json` and re-run `save_login_state.py`
- 404 on search: Try `SHT_XHS_SEARCH_URL_MODE=minimal` or reduce VPN/frequency

**TicketAssistant**
- Sign generation failed: Ensure `_m_h5_tk` Cookie exists after login; retry or update `sign.method` in config
- Order API changed: Check `damai_api.order_*` fields against live browser requests

**family-party-games**
- Cloud function deployment failed: Ensure Cloud Development is enabled and `roomService` folder exists
- Room sync not working: Check WeChat Developer Tools console for cloud function errors
