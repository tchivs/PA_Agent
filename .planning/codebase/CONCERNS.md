# Codebase Concerns

**Analysis Date:** 2026-07-11

## Severity Guide

- **Critical:** a release can bypass the repository's automated behavioral checks.
- **High:** a local credential, availability, or trading-analysis correctness boundary can fail with limited containment.
- **Medium:** a dependency, integration, or lifecycle fault requires a specific environment or failure mode but has material operational cost.
- **Low:** a maintainability issue that increases the cost and risk of future changes.

The items below are ranked by observed impact. **Verified facts** are directly evidenced by repository code or configuration; **risk/inference** statements describe the bounded consequence of those facts.

## Tech Debt

### Critical — CI installs the project but does not execute its test suite

- **Files:** `.github/workflows/ci.yml`, `pyproject.toml`, `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/property/`
- **Verified facts:** The sole CI job installs `.[dev]` and runs `python -c "import pa_agent; print('OK')`; it has no `pytest` or other test-execution step. `pyproject.toml` configures pytest with `tests` as the test path, and the repository contains unit, integration, end-to-end, and property test directories.
- **Impact:** Pull requests can merge with a broken tested behavior despite the repository already containing a test suite for it.
- **Fix approach:** Add focused CI jobs that run the existing pytest suite on the supported Python version, with a separate opt-in job or marker exclusion for tests requiring live credentials. Make the test job required before merge.

### High — Sensitive settings are persisted as ordinary JSON

- **Files:** `pa_agent/config/settings.py`, `pa_agent/config/paths.py`, `.gitignore`
- **Verified facts:** `FeishuSettings` has `webhook_url`, `secret`, `app_id`, and `app_secret`; `TushareSettings` and `PushPlusSettings` have token fields. `save_settings()` serializes `settings.model_dump()` directly with `json.dumps()` to `config/settings.json`. The file is ignored by `.gitignore`, but no encryption or restrictive file-mode operation is present in `save_settings()`.
- **Impact:** Credentials are plaintext on the local filesystem. Git exclusion reduces accidental commits but does not protect a copied profile, backup, shared host, or permissive filesystem.
- **Fix approach:** Keep non-sensitive preferences in `config/settings.json`; move credentials to an OS credential store or explicitly supplied environment variables. Provide a migration path, redact secrets in UI/export paths, and set owner-only permissions when a local compatibility file remains necessary.

### Medium — Core decision logic is concentrated in several very large modules and continues after guard failures

- **Files:** `pa_agent/ai/decision_nodes.py`, `pa_agent/ai/stage2_normalizer.py`, `pa_agent/ai/prompt_assembler.py`, `pa_agent/gui/main_window.py`
- **Verified facts:** These modules are respectively 3,071, 1,816, 1,953, and 4,386 lines. `decision_nodes.py` and `stage2_normalizer.py` contain multiple calculation/normalization paths that catch conversion or general exceptions and continue with defaults or a partial output (for example `decision_nodes.py:1467-1472`, `decision_nodes.py:2873-2875`, `stage2_normalizer.py:1599-1602`, and `stage2_normalizer.py:1808-1810`).
- **Impact:** Rule changes have a large blast radius, and a failed guard can leave a decision payload usable-looking but missing a derived constraint. This is an inference from the observed continuation behavior, not a reproduced wrong trade decision.
- **Fix approach:** Extract pure, independently tested decision rules and post-processing passes into bounded modules. Return typed diagnostics for recoverable rule failures; reserve broad exception handling for a top-level boundary that records a user-visible degraded-state marker.

## Known Bugs

No independently reproduced product defect is documented in this map. The following verified failure modes merit treatment as operational bugs when encountered.

### High — A stopped refresh loop can remain active as a tracked zombie

- **Files:** `pa_agent/gui/main_window.py`, `pa_agent/data/refresh_loop.py`, `pa_agent/data/tradingview.py`
- **Verified facts:** `_stop_refresh_loop()` waits only `_WORKER_JOIN_TIMEOUT_MS`; if the `RefreshLoop` is still running, it disconnects its signals and appends it to `_zombie_loops` rather than terminating it (`pa_agent/gui/main_window.py:744-803`). `_start_refresh_loop()` subsequently reaps completed zombies and starts a fresh loop (`pa_agent/gui/main_window.py:697-738`). `RefreshLoop.run()` calls a data source synchronously, and cancellation is checked only between calls (`pa_agent/data/refresh_loop.py:54-119`). The TradingView adapter explicitly documents a potentially blocked receive and attempts socket closure to unblock it (`pa_agent/data/tradingview.py:143-157`).
- **Symptoms:** During a blocked provider call, a symbol/source switch can leave the old worker alive while a new refresh loop starts.
- **Trigger:** A data-source call does not return before the bounded stop wait.
- **Workaround:** Restart the application if repeated source switches leave stale fetch activity or resources behind.
- **Fix approach:** Give each source fetch a cancellable deadline at the transport boundary, wait for worker termination before replacing a source when safe, and expose the count/age of zombie loops in diagnostics. Preserve the existing signal-disconnect protection while preventing indefinite background work.

## Security Considerations

### High — The QClaw relay has no request authentication and accepts arbitrary local POST bodies

- **Files:** `pa_agent/ai/qclaw_relay.py`, `pa_agent/ai/qclaw_relay_manager.py`
- **Verified facts:** `ProxyHandler.do_POST()` reads every request body, forwards all headers except three hop-by-hop headers, and never checks `Authorization` or another credential (`pa_agent/ai/qclaw_relay.py:29-69`). The server binds to `127.0.0.1`, which is an important remote-exposure constraint (`pa_agent/ai/qclaw_relay.py:23`, `pa_agent/ai/qclaw_relay.py:151`). The manager's verification client sends an authorization header, but the relay does not validate it (`pa_agent/ai/qclaw_relay_manager.py:74-93`).
- **Risk/inference:** Any process able to connect to the local loopback port can use the relay as the application's QClaw upstream proxy; a separate local account normally cannot connect to a process bound only to another network namespace, but other processes under the same desktop/session commonly can.
- **Current mitigation:** Loopback-only binding prevents direct remote-network access.
- **Recommendations:** Require a relay-specific bearer token in `do_POST()`, reject requests without it before reading a large body, and keep the token out of request logs. Bind to a per-user IPC transport where the deployment supports it.

### High — QClaw credentials are placed in command and gateway-message arguments

- **Files:** `pa_agent/ai/qclaw_relay_manager.py`, `pa_agent/ai/qclaw_relay.py`
- **Verified facts:** `_start_relay_via_openclaw_gateway()` embeds `token` in a `/exec ... --token {token}` message (`pa_agent/ai/qclaw_relay_manager.py:106-118`) and passes the same value to the OpenClaw command as `--token` (`pa_agent/ai/qclaw_relay_manager.py:120-139`). The relay accepts the token through its command-line parser (`pa_agent/ai/qclaw_relay.py:138-143`).
- **Risk/inference:** Command-line arguments and gateway message payloads can be captured by process inspection, shell history, diagnostics, or external gateway logs, depending on the host and gateway configuration.
- **Recommendations:** Pass the credential via an inherited, narrowly scoped environment variable or protected runtime file descriptor; avoid including it in user-visible command strings. Test that startup failure logs never contain the token.

### Medium — Installation is not reproducible and contains an unpinned VCS dependency

- **Files:** `pyproject.toml`
- **Verified facts:** `tvdatafeed` is declared as `git+https://github.com/rongardF/tvdatafeed.git` without a commit/tag revision. The repository has no detected `poetry.lock`, `uv.lock`, `Pipfile.lock`, `requirements*.txt`, or other dependency lockfile.
- **Risk/inference:** Reinstalling at different times can resolve different Git contents and transitive dependency versions, changing market-data behavior or breaking startup without a source-code change in this repository.
- **Recommendations:** Pin the VCS dependency to a reviewed commit (or publish/use a versioned package), add a lockfile for the supported installer, and make CI install from the locked resolution.

## Performance Bottlenecks

### Medium — Compact stock-context requests fan out while the underlying HTTP client serializes access

- **Files:** `pa_agent/data/eastmoney_extended.py`, `pa_agent/data/eastmoney_client.py`
- **Verified facts:** `_build_compact_stock_context()` submits 20 tasks to an eight-worker `ThreadPoolExecutor` (`pa_agent/data/eastmoney_extended.py:759-807`), and `fetch_portal_datacenter_bundle()` adds a nested four-worker pool (`pa_agent/data/eastmoney_extended.py:685-703`). The shared EastMoney client gates host requests with `_request_slots = Semaphore(1)` and applies process-wide throttling (`pa_agent/data/eastmoney_client.py:57-65`, `pa_agent/data/eastmoney_client.py:250-302`).
- **Impact:** The fan-out does not produce equivalent network parallelism; queued tasks retain worker threads while serialized retries and timeouts determine the end-to-end latency. Under a degraded upstream this can delay completion significantly.
- **Improvement path:** Use an explicit request budget and a single orchestration layer: group endpoints by host/priority, cap the queue, set an overall deadline, and return a completeness status rather than flooding a serialized transport with futures.

## Fragile Areas

### High — Cursor integration monkey-patches private SDK internals and the process-wide subprocess constructor

- **Files:** `pa_agent/ai/cursor_sdk_client.py`, `pyproject.toml`, `tests/unit/test_cursor_sdk_client.py`
- **Verified facts:** The client overwrites private `cursor_sdk._store_callback` and `cursor_sdk._tool_callback` attributes, private bridge functions, and `subprocess.Popen` globally (`pa_agent/ai/cursor_sdk_client.py:71-140`). The declared dependency range is `cursor-sdk>=0.1.0`, so it permits later versions. A unit test calls the patch function and launches a bridge (`tests/unit/test_cursor_sdk_client.py:41-45`), but the CI workflow does not execute that test.
- **Why fragile:** A private SDK rename or a changed bridge launch path can make the integration silently skip a patch, fail during launch, or affect unrelated subprocesses in the application process.
- **Safe modification:** Treat the SDK boundary as an adapter: pin and test the compatible SDK version, confine any compatibility patch behind a version check, and avoid rebinding global `subprocess.Popen`. Prefer an SDK-supported launch hook or a dedicated subprocess wrapper.
- **Test coverage:** A targeted test exists at `tests/unit/test_cursor_sdk_client.py`; it is not exercised by the current `.github/workflows/ci.yml` workflow.

### Medium — Partial EastMoney context is indistinguishable from genuinely empty data at the return boundary

- **Files:** `pa_agent/data/eastmoney_extended.py`
- **Verified facts:** Each failed compact-context future is converted to `[]` or `None` and the method still returns `ctx` (`pa_agent/data/eastmoney_extended.py:799-814`). The portal bundle likewise populates missing report keys as empty lists (`pa_agent/data/eastmoney_extended.py:693-703`). The cache stores the resulting context for 60 seconds regardless of how many fields failed (`pa_agent/data/eastmoney_extended.py:706-730`).
- **Why fragile:** A caller receiving `[]` or `None` cannot tell an upstream outage from a confirmed absence using the returned object alone. This is a data-provenance ambiguity, not evidence that a particular analysis has been wrong.
- **Safe modification:** Return per-field status/error metadata and a `complete`/`partial` indicator, and cache only successful fields or cache failures with a short, explicit negative-cache TTL. Let prompt/UI code show unavailable data rather than implying absence.
- **Test coverage:** Add deterministic tests for a mixed-success fan-out and cache behavior after a partial failure.

## Scaling Limits

### EastMoney request throughput is deliberately process-global and low

- **Files:** `pa_agent/data/eastmoney_client.py`, `pa_agent/data/eastmoney_extended.py`
- **Current capacity:** Normal mode permits one in-flight EastMoney request and enforces a 0.45-second inter-request interval; bulk mode permits two requests with a 0.95-second interval (`pa_agent/data/eastmoney_client.py:57-65`, `pa_agent/data/eastmoney_client.py:161-165`).
- **Limit:** A compact context can request 20 endpoints (`pa_agent/data/eastmoney_extended.py:762-783`), so a single analysis competes with refresh and screening operations for the same global request slot.
- **Scaling path:** Introduce a source-aware scheduler with request priorities (live bars before enrichment), coalescing per-symbol requests, deadlines, and observable queue metrics. Preserve provider throttling as a rate-limit policy rather than an implicit global bottleneck.

## Dependencies at Risk

### `tvdatafeed` VCS install

- **Files:** `pyproject.toml`, `pa_agent/data/tradingview.py`
- **Risk:** The VCS dependency is unpinned, while the adapter relies on its WebSocket behavior and explicitly handles blocked receives (`pa_agent/data/tradingview.py:143-157`).
- **Impact:** A changed upstream package can alter connection behavior outside the reviewable dependency resolution.
- **Migration plan:** Pin a reviewed commit immediately; maintain a small adapter contract test around `TradingViewSource` before upgrading.

### `cursor-sdk` permissive pre-1.0 range

- **Files:** `pyproject.toml`, `pa_agent/ai/cursor_sdk_client.py`
- **Risk:** `cursor-sdk>=0.1.0` is combined with patches to private module APIs.
- **Impact:** Version drift can break the patch points or bridge startup.
- **Migration plan:** Pin a known-compatible version, fail fast with a precise compatibility error, and remove monkey patches when the SDK offers a supported fix.

## Missing Critical Features

### CI test execution gate

- **Problem:** The current required workflow checks installation only and does not run the existing automated tests.
- **Files:** `.github/workflows/ci.yml`, `pyproject.toml`, `tests/`
- **Blocks:** The project cannot use its existing unit, integration, end-to-end, and property suites as a release-confidence gate.

### Authenticated and bounded local relay protocol

- **Problem:** The relay has no authentication, body-size limit, or short request deadline; it uses the single-threaded `HTTPServer` with a 600-second upstream timeout.
- **Files:** `pa_agent/ai/qclaw_relay.py`
- **Blocks:** The application has no strong containment against another local process using or monopolizing the relay.

## Test Coverage Gaps

### Relay implementation behavior

- **What's not tested:** No test matching the relay server implementation (`ProxyHandler`, authentication behavior, request size/deadline handling, or upstream forwarding) was found under `tests/`; the QClaw route test mocks `ensure_qclaw_relay` at `tests/unit/test_qclaw_agent_route.py:41-45`.
- **Files:** `pa_agent/ai/qclaw_relay.py`, `pa_agent/ai/qclaw_relay_manager.py`, `tests/unit/test_qclaw_agent_route.py`
- **Risk:** Relay authorization and failure containment can regress without a focused behavioral test, and the current CI workflow would not run such a test even if added.
- **Priority:** High

### Refresh-loop shutdown under a blocked data source

- **What's not tested:** `tests/unit/test_refresh_loop_warmup.py` verifies only that `RefreshLoop` requests enough bars for indicator warmup. No test matching `_stop_refresh_loop` or `_reap_zombie_loops` was found, and no shutdown/cancellation behavior is exercised by that warmup test.
- **Files:** `pa_agent/gui/main_window.py`, `pa_agent/data/refresh_loop.py`, `tests/`
- **Risk:** Changes to cancellation, source switching, or provider timeouts can reintroduce stale worker/resource leaks without deterministic coverage.
- **Priority:** Medium

---

*Concerns audit: 2026-07-11*
