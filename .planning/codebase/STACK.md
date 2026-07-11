# Technology Stack

**Analysis Date:** 2026-07-11

## Evidence Convention

- **[Direct evidence]** is established from the cited repository manifest, configuration, source, or workflow.
- **[Inference]** is a conclusion drawn from direct evidence and is labelled as such.

## Languages

**Primary:**
- **Python 3.11+** — the application, tests, tooling, and package entry point are Python; `pyproject.toml` sets `requires-python = ">=3.11"`, `pa_agent/main.py` is the GUI entry point, and `tests/` contains the test suite. [Direct evidence]

**Secondary:**
- **JavaScript** — `tools/run_diag_node.js` is an isolated diagnostic utility, not a declared product runtime or build target. [Direct evidence]
- **JSON** — runtime settings and example configuration are JSON, including `config/settings.example.json`, `config/feishu.example.json`, and `config/tv_symbol_aliases.example.json`. [Direct evidence]
- **Markdown and plain-text strategy assets** — user/developer documentation is Markdown and prompt strategy material is read from `prompt_engineering/`; these are content assets rather than executable application code. [Direct evidence]

## Runtime

**Environment:**
- **CPython 3.11+** — required by `pyproject.toml`; the CI workflow pins Python 3.11 in `.github/workflows/ci.yml`. [Direct evidence]
- **Desktop Qt process** — `pa_agent/main.py` creates a `PyQt6.QtWidgets.QApplication`, applies the theme, builds `MainWindow`, and enters `app.exec()`. [Direct evidence]
- **Windows support for MT5** — `MetaTrader5` and `pywin32` are conditional dependencies only when `sys_platform == 'win32'`; `pa_agent/data/mt5.py` requires a running and logged-in MT5 terminal. [Direct evidence]
- **macOS/other platforms without MT5** — `MAC版本智能体部署方法.txt` directs users to the TradingView path and notes the Windows-only dependencies are skipped by their markers. [Direct evidence]

**Package Manager:**
- **pip/setuptools** — `pyproject.toml` uses `setuptools.build_meta` with `setuptools>=68` and `wheel`; installation commands in `README.md` and `.github/workflows/ci.yml` use `pip install -e`. [Direct evidence]
- **Lockfile: missing** — no Python lockfile (`poetry.lock`, `Pipfile.lock`, `requirements*.txt`) or JavaScript lockfile/package manifest was detected at the repository root; dependency resolution is version-range based through `pyproject.toml`. [Direct evidence]

## Frameworks

**Core:**
- **PyQt6 >=6.6** — desktop UI framework declared in `pyproject.toml`; initialized in `pa_agent/main.py` and used throughout `pa_agent/gui/`. [Direct evidence]
- **pyqtgraph >=0.13** — chart rendering dependency declared in `pyproject.toml` and imported by `pa_agent/gui/chart_widget.py`. [Direct evidence]
- **Pydantic >=2.7** — typed settings models and validation in `pa_agent/config/settings.py`. [Direct evidence]
- **OpenAI Python SDK >=1.40** — OpenAI-compatible LLM transport, imported by `pa_agent/ai/deepseek_client.py` and constructed by `pa_agent/ai/client_factory.py`. [Direct evidence]

**Data and validation:**
- **NumPy >=1.26 and pandas >=2.2** — numeric/chart and market-data transformations; examples include `pa_agent/gui/chart_widget.py`, `pa_agent/data/akshare_source.py`, and `pa_agent/data/yfinance_source.py`. [Direct evidence]
- **jsonschema >=4.22** — optional JSON-schema validation used by `pa_agent/ai/json_validator.py`. [Direct evidence]
- **tiktoken >=0.7** — token accounting in `pa_agent/ai/token_counter.py`, with a documented fallback when unavailable. [Direct evidence]
- **cryptography >=42** — AES-GCM handling for Windows WorkBuddy/Electron token recovery in `pa_agent/ai/workbuddy_connector.py`. [Direct evidence]

**Testing:**
- **pytest >=8** — test runner configured in `[tool.pytest.ini_options]` in `pyproject.toml`; test roots are `tests/`. [Direct evidence]
- **pytest-qt >=4.4** — Qt-aware test support declared in `pyproject.toml`. [Direct evidence]
- **Hypothesis >=6** — property-test support declared in `pyproject.toml` and used under `tests/property/`. [Direct evidence]

**Build/Dev:**
- **Ruff >=0.5** — lint tool configured in `pyproject.toml`; the `lint` target in `Makefile` runs `ruff check .`. [Direct evidence]
- **Black >=24.4** — formatter/checker configured in `pyproject.toml`; the `lint` target in `Makefile` runs `black --check .`. [Direct evidence]
- **GitHub Actions** — `.github/workflows/ci.yml` runs on pushes and pull requests targeting `main`, installs `.[dev]`, and verifies `import pa_agent`. It does not currently run `pytest`, Ruff, or Black. [Direct evidence]

## Key Dependencies

**Critical application dependencies:**
- **`PyQt6` / `pyqtgraph`** — desktop application shell and interactive K-line visualization in `pa_agent/main.py` and `pa_agent/gui/chart_widget.py`. [Direct evidence]
- **`openai`** — streaming chat-completions client for the configurable OpenAI-compatible provider in `pa_agent/ai/deepseek_client.py`. [Direct evidence]
- **`pydantic` / `jsonschema`** — settings model validation in `pa_agent/config/settings.py` and response-schema validation in `pa_agent/ai/json_validator.py`. [Direct evidence]
- **`numpy` / `pandas`** — numerical and OHLCV operations in `pa_agent/indicators/`, `pa_agent/data/`, and `pa_agent/gui/chart_widget.py`. [Direct evidence]
- **`tiktoken`** — token counting in `pa_agent/ai/token_counter.py`. [Direct evidence]

**Market-data and provider dependencies:**
- **`MetaTrader5 >=5.0`** (Windows only) — reads broker-terminal symbols, ticks, and K-lines through `pa_agent/data/mt5.py`. [Direct evidence]
- **`tvdatafeed` from `git+https://github.com/rongardF/tvdatafeed.git`** — TradingView data access in `pa_agent/data/tradingview.py`; this is a VCS dependency, not a registry-pinned release. [Direct evidence]
- **`akshare >=1.14`, `baostock >=0.8`, `tushare >=1.4`, and `curl_cffi >=0.13`** — China-market data routes and HTTP impersonation in `pa_agent/data/akshare_source.py`, `pa_agent/data/eastmoney_baostock.py`, `pa_agent/data/tushare_source.py`, and `pa_agent/data/eastmoney_client.py`. [Direct evidence]
- **`cursor-sdk >=0.1.0`** — optional Cursor-backed LLM route in `pa_agent/ai/cursor_sdk_client.py`. [Direct evidence]

**Source imports not declared as direct project dependencies:**
- **`requests` and `httpx`** — lazy imports appear in `pa_agent/notify/feishu_notifier.py`, `pa_agent/notify/pushplus_notifier.py`, `pa_agent/data/eastmoney_client.py`, `pa_agent/ai/qclaw_connector.py`, `pa_agent/ai/qclaw_relay_manager.py`, and `pa_agent/ai/workbuddy_connector.py`, but neither package is listed in `pyproject.toml` or `pa_agent.egg-info/requires.txt`. [Direct evidence]
- **`yfinance`** — `pa_agent/data/yfinance_source.py` implements an optional source but `yfinance` is absent from `pyproject.toml` and `pa_agent.egg-info/requires.txt`. [Direct evidence]
- **[Inference]** These three packages may be available transitively in some environments, but their corresponding features are not reproducibly installed by the project’s declared dependency set alone.

## Configuration

**Environment:**
- **Primary runtime settings** — `pa_agent/config/paths.py` centralizes `config/settings.json`; `pa_agent/config/settings.py` loads, validates, migrates, and saves it. The file exists locally but is ignored by `.gitignore`; this mapping does not inspect its contents. [Direct evidence]
- **Templates** — copy `config/settings.example.json` to `config/settings.json` for provider, data-source, validation, Feishu, PushPlus, and Tushare configuration, as documented in `config/README.md`. [Direct evidence]
- **Repository secret policy** — `.gitignore` excludes `.env*`, `config/settings.json`, local Feishu settings, and key material; `.githooks/pre-commit` rejects these paths and recognizable API-key additions. [Direct evidence]
- **Runtime filesystem locations** — `pa_agent/config/paths.py` defines `records/pending/`, `experience/`, `logs/`, `trade_records/`, and the execution SQLite ledger at `trade_records/execution/execution_ledger.sqlite3`. [Direct evidence]

**Build:**
- **Packaging and tool settings** — all build, dependency, pytest, Black, and Ruff configuration is in `pyproject.toml`. [Direct evidence]
- **Task aliases** — `Makefile` defines `run`, `test`, `lint`, and `setup-secrets`; no `setup.py`, `setup.cfg`, Dockerfile, Compose file, `tox.ini`, `noxfile.py`, or project-level pre-commit configuration was detected. [Direct evidence]

## Execution Commands

```bash
pip install -e .                 # Install the desktop application
pip install -e ".[dev]"         # Install application plus test/lint tooling
python -m pa_agent.main          # Start the PyQt application
python run.py                    # Alternate launcher with IPython/Spyder handling
pa-agent                         # Installed console script from pyproject.toml
make run                         # Equivalent module launcher
make test                        # pytest -q
make lint                        # ruff check . && black --check .
pytest -m "not e2e"              # Contributor-documented focused test selection
```

The commands above are defined or documented in `pyproject.toml`, `Makefile`, `README.md`, `run.py`, `CONTRIBUTING.md`, and `pa_agent.egg-info/entry_points.txt`. [Direct evidence]

## Platform Requirements

**Development:**
- Python 3.11+ and pip editable installation are required by `pyproject.toml`, `README.md`, and `CONTRIBUTING.md`. [Direct evidence]
- Windows development requiring MT5 data needs a running, authenticated MetaTrader 5 terminal, according to `pa_agent/data/mt5.py` and `CONTRIBUTING.md`. [Direct evidence]
- TradingView use requires the VCS-hosted `tvdatafeed` dependency to be installable; `MAC版本智能体部署方法.txt` calls out GitHub access for this install. [Direct evidence]

**Production:**
- The repository packages a local desktop application; no hosted deployment manifest, container image, server runtime, or deployment-platform configuration was detected. [Direct evidence]
- Logs, analysis artifacts, experience data, trade exports, and the execution ledger are local runtime data under paths defined in `pa_agent/config/paths.py`. [Direct evidence]

---

*Stack analysis: 2026-07-11*
