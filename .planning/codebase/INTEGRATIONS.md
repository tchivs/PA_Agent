# External Integrations

**Analysis Date:** 2026-07-11

## Evidence Convention

- **[Direct evidence]** is established from the cited repository manifest, configuration, or implementation.
- **[Inference]** is a conclusion drawn from that evidence and is explicitly marked.
- Secret-bearing local configuration files are identified by path and field name only; their contents are not inspected.

## APIs & External Services

### AI and LLM providers

**OpenAI-compatible provider route:**
- **DeepSeek (default) and user-selected compatible gateways** — `pa_agent/config/settings.py` defaults `provider.base_url` to `https://api.deepseek.com`; `pa_agent/ai/deepseek_client.py` initializes the `openai.OpenAI` SDK and streams completions; `pa_agent/ai/client_factory.py` selects this client unless the Cursor model alias is active. [Direct evidence]
  - SDK/Client: `openai>=1.40` from `pyproject.toml`, used in `pa_agent/ai/deepseek_client.py`.
  - Auth: `provider.api_key` in ignored `config/settings.json`; configured through `config/settings.example.json` and `pa_agent/config/settings.py`.
  - Boundary: model and base URL are user-configurable; the UI validates an HTTP(S) base URL in `pa_agent/gui/settings_dialog.py`.

**MiMo compatibility:**
- **Xiaomi MiMo API** — `pa_agent/ai/mimo_compat.py` defines `https://api.xiaomimimo.com/v1` and a token-plan URL, and adapts the OpenAI-compatible reasoning payload. [Direct evidence]
  - SDK/Client: the same `openai` client through `pa_agent/ai/deepseek_client.py`.
  - Auth: the configured `provider.api_key` field in `config/settings.json`.

**Provider-specific compatibility branches:**
- **KKAI, PackyAPI, and MiniMax** — `pa_agent/ai/deepseek_client.py` recognizes their base-URL domains to tailor request/token behavior; `pa_agent/gui/settings_dialog.py` presents PackyAPI as a base-URL example. [Direct evidence]
  - SDK/Client: `openai` through `pa_agent/ai/deepseek_client.py`.
  - Auth: the generic `provider.api_key` setting.
  - [Inference] These are supported routing/compatibility cases, not separately provisioned SDK integrations, because no vendor-specific package or fixed credentials are declared in `pyproject.toml`.

**Cursor:**
- **Cursor SDK model route** — the `openclaw_cs` model alias routes `pa_agent/ai/client_factory.py` to `CursorSdkClient` in `pa_agent/ai/cursor_sdk_client.py`; the connector documents a Cursor API key requirement and clears `base_url` in `pa_agent/ai/cursor_connector.py`. [Direct evidence]
  - SDK/Client: `cursor-sdk>=0.1.0` declared in `pyproject.toml` and imported by `pa_agent/ai/cursor_sdk_client.py`.
  - Auth: Cursor key entered as `provider.api_key` in the ignored settings file; the connector expects the `crsr_` prefix.
  - Local process boundary: the client patches and starts the Cursor SDK bridge subprocess in `pa_agent/ai/cursor_sdk_client.py`.

**QClaw/OpenClaw:**
- **Locally running QClaw Gateway** — `pa_agent/ai/qclaw_connector.py` discovers `~/.qclaw/openclaw.json`, reads its gateway endpoint/token, probes the local `/v1/models` route, and configures the `openclaw` provider alias. [Direct evidence]
  - SDK/Client: the generic OpenAI-compatible path in `pa_agent/ai/deepseek_client.py`; gateway probing uses lazy `httpx` imports in `pa_agent/ai/qclaw_connector.py`.
  - Auth: the gateway token is read from the local QClaw configuration, not from a repository file.
  - Local relay: `pa_agent/ai/qclaw_relay.py` can expose an HTTP relay on `127.0.0.1` (default port 19004) that forwards to QClaw’s internal `127.0.0.1:19000/proxy/llm`; `pa_agent/ai/qclaw_relay_manager.py` asks the QClaw gateway to start it.

**WorkBuddy / CodeBuddy:**
- **Tencent WorkBuddy Copilot API** — `pa_agent/ai/workbuddy_connector.py` defaults to `https://copilot.tencent.com/v2` and maps the `openclaw_wb` alias to its internal model selection. [Direct evidence]
  - SDK/Client: the generic OpenAI-compatible client for requests; connectivity checks use lazy `httpx` imports in `pa_agent/ai/workbuddy_connector.py`.
  - Auth: WorkBuddy auth session data, a local `~/.workbuddy/.wb_token` override, or environment variables; Windows Electron session recovery uses DPAPI plus `cryptography` AES-GCM in `pa_agent/ai/workbuddy_connector.py`.

### Market data and exchanges

**MetaTrader 5:**
- **MT5 desktop terminal / user’s broker feed** — `pa_agent/data/mt5.py` initializes the local terminal, reads terminal metadata, symbols, ticks, and K-lines. [Direct evidence]
  - SDK/Client: `MetaTrader5>=5.0` is declared only for Windows in `pyproject.toml`.
  - Auth: no broker credentials are read by this repository; the terminal must already be open and logged in, per `pa_agent/data/mt5.py`.
  - Scope: this adapter reads data; it does not call the trading execution port. [Direct evidence]

**TradingView:**
- **TradingView market-data service** — `pa_agent/data/tradingview.py` uses `tvDatafeed` to retrieve historical bars over its WebSocket-backed client, supports anonymous or username/password construction, and probes configured exchanges. [Direct evidence]
  - SDK/Client: `tvdatafeed` is declared as the Git dependency `git+https://github.com/rongardF/tvdatafeed.git` in `pyproject.toml`.
  - Auth: optional username/password constructor parameters in `pa_agent/data/tradingview.py`; no TradingView credential field is present in `config/settings.example.json`.
  - Exchanges: presets in `pa_agent/data/tradingview.py` include FX, equities, futures, and crypto venues; `pa_agent/data/market_defaults.py` includes Binance, Bitstamp, Coinbase, Bybit, OKX, Bitfinex, Huobi, and Kraken only as TradingView symbol/exchange hints. [Direct evidence]

**China-market data:**
- **AkShare** — `pa_agent/data/akshare_source.py` uses the `akshare` package for A-share OHLCV and spot data. [Direct evidence]
  - SDK/Client: `akshare>=1.14` in `pyproject.toml`.
  - Auth: none observed in the source path.
- **Baostock** — `pa_agent/data/akshare_source.py` enables the fallback only when `PA_AGENT_BAOSTOCK_FALLBACK` is truthy; `pa_agent/data/eastmoney_baostock.py` also uses Baostock for older history. [Direct evidence]
  - SDK/Client: `baostock>=0.8` in `pyproject.toml`.
  - Auth: none observed in the source path.
- **EastMoney public quote APIs** — `pa_agent/data/eastmoney_source.py` uses the internal client at `pa_agent/data/eastmoney_client.py` to poll public quote, K-line, order-book, hot-stock, and related endpoints; `pa_agent/data/eastmoney_extended.py` adds data-center, news, notice, report, and money-flow endpoints. [Direct evidence]
  - SDK/Client: `curl_cffi>=0.13` is preferred for browser TLS impersonation in `pa_agent/data/eastmoney_client.py`; code falls back to a lazy `requests` import.
  - Auth: no credential input is used; the implementation sends public web headers/referers and rotates public hosts.
- **Tushare Pro** — `pa_agent/data/tushare_source.py` calls `ts.pro_bar` and `ts.pro_api(...).stk_mins` for A-share bars. [Direct evidence]
  - SDK/Client: `tushare>=1.4` in `pyproject.toml`.
  - Auth: `tushare.token` in ignored `config/settings.json`, falling back to the `TUSHARE_TOKEN` environment variable.
- **Yahoo Finance through yfinance** — `pa_agent/data/yfinance_source.py` implements futures, equity, and crypto bar retrieval through `yf.Ticker(...).history(...)`. [Direct evidence]
  - SDK/Client: lazy `yfinance` import in `pa_agent/data/yfinance_source.py`.
  - Auth: none observed.
  - [Inference] This adapter is optional and not reproducibly installed by the repository’s direct manifest because `yfinance` is absent from `pyproject.toml` and `pa_agent.egg-info/requires.txt`.

### Notifications

**Feishu/Lark:**
- **Feishu custom bot and Open Platform APIs** — `pa_agent/notify/feishu_notifier.py` posts interactive decision cards to a configured webhook, optionally signs requests with HMAC-SHA256, obtains a tenant access token, and uploads chart images to the Feishu API. [Direct evidence]
  - SDK/Client: lazy `requests` imports in `pa_agent/notify/feishu_notifier.py` and the Feishu settings dialog at `pa_agent/gui/feishu_settings_dialog.py`.
  - Auth: `feishu.webhook_url`, optional `feishu.secret`, `feishu.app_id`, and `feishu.app_secret` in ignored `config/settings.json`; documented by `config/feishu.example.json`.
  - Callback direction: outbound only; no Feishu event receiver is implemented.

**PushPlus:**
- **PushPlus notification API** — `pa_agent/notify/pushplus_notifier.py` POSTs HTML notifications to `https://www.pushplus.plus/send`. [Direct evidence]
  - SDK/Client: lazy `requests` import in `pa_agent/notify/pushplus_notifier.py`.
  - Auth: `pushplus.token` in ignored `config/settings.json`, with `PUSHPLUS_TOKEN` as an environment fallback.

## Data Storage

**Databases:**
- **Local SQLite only** — `pa_agent/config/paths.py` defines the execution ledger at `trade_records/execution/execution_ledger.sqlite3`; `pa_agent/trading/persistence/sqlite_connection.py` opens it with the standard-library `sqlite3` module and enforces foreign keys, WAL mode, FULL synchronous durability, and a 5000 ms busy timeout. [Direct evidence]
  - Connection: local filesystem path, not a network connection string.
  - Client: Python standard-library `sqlite3`; no ORM is used by the execution ledger.
- **External database providers: Not detected** — a source scan found no Postgres, MySQL, Redis, Supabase, Firebase, or cloud database integration under `pa_agent/`. [Direct evidence]

**File Storage:**
- **Local filesystem** — `pa_agent/config/paths.py` centralizes `records/pending/`, `experience/`, `logs/`, `trade_records/`, and `config/`; `pa_agent/records/pending_writer.py` writes JSON/JSONL analysis records. [Direct evidence]
- **Cloud/object storage: Not detected** — no S3 or equivalent client integration was found under `pa_agent/`. [Direct evidence]

**Caching:**
- **Process-memory caches only** — examples include Tushare snapshot cache fields in `pa_agent/data/tushare_source.py`, EastMoney snapshot caching in `pa_agent/data/eastmoney_source.py`, and Feishu’s in-process token cache in `pa_agent/notify/feishu_notifier.py`. [Direct evidence]
- **External cache: None detected** — no Redis, Memcached, or similar client is present under `pa_agent/`. [Direct evidence]

## Authentication & Identity

**Application user authentication:**
- **Not applicable / not detected** — the product is a local desktop application started by `pa_agent/main.py`; no login UI, application user database, OAuth callback server, or session middleware is present. [Direct evidence]

**Service authentication:**
- **Configured API keys** — generic LLM provider, Tushare, Feishu, PushPlus, Cursor, QClaw, and WorkBuddy use the credentials described in their service sections. [Direct evidence]
- **Local configuration policy** — `.gitignore` excludes `config/settings.json`, `.env*`, `config/secret.key`, and related credential-bearing files; `.githooks/pre-commit` blocks them from commits. [Direct evidence]
- **Settings model caveat** — `pa_agent/config/settings.py` exposes both `api_key` and `api_key_encrypted`, but its load migration removes a legacy encrypted-key field and keeps `api_key` in the runtime model. No repository source implementing encryption for the provider key was found in the `pa_agent/` search. [Direct evidence]

## Monitoring & Observability

**Error Tracking:**
- **Hosted error tracking: None detected** — no Sentry, Datadog, OpenTelemetry, Prometheus, or equivalent client was found under `pa_agent/`. [Direct evidence]

**Logs:**
- **Rotating local files plus console** — `pa_agent/util/logging.py` creates `logs/pa_agent.log` using a 5 MiB rotating file handler with 10 backups and masks the configured API key; `pa_agent/config/paths.py` also defines `logs/crash.log`. [Direct evidence]
- **Crash diagnostics** — `pa_agent/main.py` enables crash diagnostics before the Qt application starts. [Direct evidence]

## CI/CD & Deployment

**Hosting:**
- **Not detected** — no deployment-platform configuration, Dockerfile, Compose manifest, container configuration, or hosting target is present at the repository root. [Direct evidence]

**CI Pipeline:**
- **GitHub Actions** — `.github/workflows/ci.yml` runs on `main` pushes and pull requests, uses `windows-latest`, pins uv 0.9.30 and Python 3.11, synchronizes `uv.lock`, then verifies `import pa_agent` through `uv run --frozen`. [Direct evidence]
- **Deployment automation: None detected** — the workflow contains no publish, release, deployment, or environment-secrets step. [Direct evidence]

## Environment Configuration

**Required or optional environment variables:**
- `TUSHARE_TOKEN` — fallback credential for `pa_agent/data/tushare_source.py`.
- `TUSHARE_ADJ` — daily Tushare adjustment override in `pa_agent/data/tushare_source.py`.
- `PUSHPLUS_TOKEN` — fallback notification token in `pa_agent/notify/pushplus_notifier.py` and `pa_agent/config/settings.py`.
- `PA_AGENT_BAOSTOCK_FALLBACK` — opt-in Baostock fallback in `pa_agent/data/akshare_source.py`.
- `PA_AGENT_ROOT` — Cursor SDK workspace override in `pa_agent/ai/cursor_sdk_client.py`.
- `WORKBUDDY_CONFIG_DIR`, `WORKBUDDY_AUTH_FILE`, `WORKBUDDY_API_TOKEN`, `CODEBUDDY_AUTH_TOKEN`, `ACC_AUTH_TOKEN`, `WORKBUDDY_API_ENDPOINT`, `WORKBUDDY_API_URL`, `ACC_PRODUCT_CONFIG_V3`, `CLIENT_INFO_PRODUCT_NAME`, and `LOCALAPPDATA` — WorkBuddy detection, credential, and endpoint inputs in `pa_agent/ai/workbuddy_connector.py`.
- `OPENCLAW_CONFIG_PATH` and `OPENCLAW_STATE_DIR` — environment injected when `pa_agent/ai/qclaw_relay_manager.py` invokes the local OpenClaw CLI. [Direct evidence]

**Secrets location:**
- Primary local secret boundary: ignored `config/settings.json`, described by `config/settings.example.json` and `config/README.md`. [Direct evidence]
- Optional environment secret boundary: process environment variables listed above; `.env` files are ignored by `.gitignore`, but no environment-file loader is imported in `pa_agent/`. [Direct evidence]
- External desktop-state boundary: local QClaw and WorkBuddy files beneath the user home/application-data directories are read only by their connectors; they are outside this repository. [Direct evidence]

## Webhooks & Callbacks

**Incoming:**
- **No product inbound webhook/API server** — no Flask, FastAPI, aiohttp, Socket.IO, or externally bound HTTP server was found under `pa_agent/`. [Direct evidence]
- **Local-only exception:** `pa_agent/ai/qclaw_relay.py` starts a standard-library HTTP server only on `127.0.0.1` for local QClaw relay health, models, and forwarded chat-completions requests. [Direct evidence]

**Outgoing:**
- **Feishu custom-bot webhook** — outbound interactive-card POSTs in `pa_agent/notify/feishu_notifier.py`. [Direct evidence]
- **PushPlus send endpoint** — outbound notification POSTs in `pa_agent/notify/pushplus_notifier.py`. [Direct evidence]
- **LLM and market-data requests** — outbound SDK/HTTP/WebSocket traffic is implemented by the provider and data-source modules listed above. [Direct evidence]

---

*Integration audit: 2026-07-11*
