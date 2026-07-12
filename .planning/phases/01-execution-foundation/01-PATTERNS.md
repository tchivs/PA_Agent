# Phase 01: Execution Foundation - Pattern Map

**Mapped:** 2026-07-11  
**Scope:** NFR-02 gap closure — enforce a fresh venue-rule fetch before each order-validation decision.  
**Files classified:** 5 proposed implementation/test files; 7 source/test analogs read.  
**Analogs found:** 4 direct role/data-flow matches, 1 partial test match; no existing order-validation implementation exists.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `pa_agent/trading/application/validation.py` (new; filename is planner discretion) | service | synchronous request-response / transform | `pa_agent/trading/application/recovery.py` | role-match |
| `tests/fixtures/fake_exchange.py` (extend) | deterministic fake gateway | synchronous request-response | `ReconciliationOnlyGateway` in the same file | exact fixture pattern, partial gateway surface |
| `tests/unit/execution/test_order_validation.py` (new) | unit test | transform | `tests/unit/execution/test_models.py` | role-match |
| `tests/property/execution/test_rule_validation_properties.py` (new) | property test | transform | `tests/property/execution/test_decimal_invariants.py` | role-match |
| `tests/integration/execution/test_refresh_before_validation.py` (new) | integration test | request-response | `tests/integration/execution/test_uncertain_recovery.py` | role-match |

`pa_agent/trading/domain/models.py` and `pa_agent/trading/ports/gateway.py` are the existing canonical contract owners. The gap can be closed by consuming them; their existing types and gateway method do not need a parallel model or port.

## Pattern Assignments

### `pa_agent/trading/application/validation.py` — validation service (synchronous request-response / transform)

**Closest analog:** `pa_agent/trading/application/recovery.py:21-44` (`RecoveryService`).

Use constructor injection with keyword-only dependencies, private attributes, and a small immutable result if a result object is needed. The service, rather than the gateway, must own the orchestration order: fetch canonical rules first, then call deterministic validation with that returned observation.

```python
# pa_agent/trading/application/recovery.py:21-30
class RecoveryService:
    """Reconcile durable jobs using canonical lookup evidence and never submission.

    The service deliberately queries the gateway only with each job's first
    persisted client-order ID. It allocates no command, client, job, or claim
    identity, and does not expose a submission path.
    """

    def __init__(self, *, ledger: ExecutionLedger, gateway: TradingGateway) -> None:
        self._ledger = ledger
        self._gateway = gateway
```

```python
# pa_agent/trading/application/recovery.py:32-44
    def recover_startup(self) -> tuple[RecoveryResult, ...]:
        """Scan persisted unresolved jobs and reconcile each one from canonical evidence."""
        return tuple(
            self.reconcile_job(job) for job in self._ledger.list_unresolved_reconciliation_jobs()
        )

    def reconcile_job(self, job: ReconciliationJob) -> RecoveryResult:
        """Inspect one job by its durable client ID and append only legal evidence."""
        evidence = self._gateway.lookup_order_by_client_id(job.client_order_id)
        if evidence is None:
            return RecoveryResult(
                reconciliation_job_id=job.reconciliation_job_id,
                client_order_id=job.client_order_id,
                lifecycle_state=job.lifecycle_state,
                evidence_applied=False,
            )
```

**Required NFR-02 ordering:**

```text
ExecutionCommand
    -> gateway.get_instrument_rules(command.symbol)
    -> RuleObservation
    -> deterministic validation(command, observation.rules)
    -> accepted/rejected validation result
```

The lookup and validation must be adjacent in the same public validation operation. Do not cache `InstrumentRules`, accept rules as a caller-supplied optional parameter, or call validation before the lookup. This service must not submit, create a ledger admission, mutate lifecycle state, or add recovery behavior; those are separate Phase 01 concerns.

**Cautions:**

- `TradingGateway` is an ABC, so annotate the dependency as `TradingGateway`; tests may use a small duck-typed deterministic fake as the recovery tests do.
- Make a failed/unavailable rule lookup fail closed. A `GatewayUnavailableError` is an expected typed gateway failure, not a reason to reuse stale metadata.
- Validate that `observation.rules.symbol == command.symbol` before applying returned rules. `RuleObservation` carries the symbol indirectly through `InstrumentRules`; the current model does not establish cross-object equality for a command and an observation.
- The current `RuleObservation.observed_at` is evidence data, not a freshness policy. NFR-02's required freshness is best enforced as an immediate gateway invocation per validation attempt, not as a new inferred TTL/cached timestamp policy.
- Preserve `Decimal` values end to end. Never use `float`, `Decimal(float)`, or a `REAL` persistence boundary in validation.

### Canonical rules and observations — consume, do not duplicate

**Source:** `pa_agent/trading/domain/models.py:75-102,264-277,345-353`.

```python
# pa_agent/trading/domain/models.py:75-92
def decimal_from_canonical(value: Decimal | str) -> Decimal:
    """Parse an exact finite Decimal, rejecting floats and non-canonical numeric types."""
    if isinstance(value, float):
        raise DecimalValueError("binary float is not a trading-domain value")
    if not isinstance(value, (Decimal, str)):
        raise DecimalValueError("trading Decimal values must be Decimal instances or text")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DecimalValueError("invalid trading Decimal") from exc
    if not parsed.is_finite():
        raise DecimalValueError("trading Decimal values must be finite")
    return parsed


def decimal_to_canonical(value: Decimal | str) -> str:
    """Return stable fixed-point text for a finite canonical Decimal value."""
    return format(decimal_from_canonical(value), "f")
```

```python
# pa_agent/trading/domain/models.py:263-277
@dataclass(frozen=True)
class InstrumentRules:
    """Canonical venue rules used by later deterministic validation."""

    symbol: str
    price_tick: Decimal | str
    quantity_step: Decimal | str
    minimum_quantity: Decimal | str = Decimal("0")
    minimum_notional: Decimal | str = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("price_tick", "quantity_step", "minimum_quantity", "minimum_notional"):
            _decimal_field(self, name)
        _require_positive(self, "price_tick")
        _require_positive(self, "quantity_step")
```

```python
# pa_agent/trading/domain/models.py:345-353
@dataclass(frozen=True)
class RuleObservation:
    """Timestamped immutable instrument-rule observation."""

    rules: InstrumentRules
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
```

**Apply to:** the new validator and all its tests. Use the existing `InstrumentRules` exactly as the canonical rule input: `price_tick`, `quantity_step`, `minimum_quantity`, and `minimum_notional` are already normalized to finite `Decimal` values; tick and step are already positive. A new validator must not introduce a second rule DTO or reparse venue payloads.

**Command input source:** `pa_agent/trading/domain/models.py:168-196`.

```python
@dataclass(frozen=True)
class ExecutionCommand:
    """Immutable operator-approved canonical order command before gateway execution."""

    command_id: str
    logical_command_key: str
    client_order_id: str
    mode: Mode
    account_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal | str
    context: ProductContext
    price: Decimal | str | None = None
```

A limit-order validation has a canonical `price`; a market command intentionally has `price is None` (`models.py:183-192`). Do not invent a price-tick check for a market order without a separately specified venue rule/price source.

### `TradingGateway.get_instrument_rules` — existing metadata port

**Source:** `pa_agent/trading/ports/gateway.py:31-57` (`TradingGateway`).

```python
class TradingGateway(ABC):
    """Synchronous, canonical-only boundary implemented by future venue adapters.

    Adapters normalize any venue payload before returning from this contract and
    raise only ``TradingGatewayError`` subclasses for expected gateway failures.
    A future coordinator MUST validate its admissible durable ledger claim
    immediately before every call to :meth:`submit_order`; that admission stays
    outside this adapter port.
    """

    @abstractmethod
    def get_capabilities(self) -> GatewayCapabilities:
        """Return the normalized products and recovery features this gateway supports."""

    @abstractmethod
    def get_server_time(self) -> TimeObservation:
        """Return observed venue server time as canonical UTC evidence."""

    @abstractmethod
    def get_quote(self, symbol: str) -> QuoteObservation:
        """Return the current canonical bid and ask observation for ``symbol``."""

    @abstractmethod
    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        """Return current canonical trading rules for ``symbol``."""
```

**Contract test analog:** `tests/unit/execution/test_gateway_contract.py:30-79` verifies both abstract surface and canonical annotations.

```python
expected_operations = {
    "get_capabilities",
    "get_server_time",
    "get_quote",
    "get_instrument_rules",
    "get_account_snapshot",
    "submit_order",
    "cancel_order",
    "lookup_order_by_client_id",
    "list_open_orders",
    "list_fills",
    "reconcile",
}
...
"get_instrument_rules": {"symbol": str, "return": RuleObservation},
```

**Caution:** This port already promises *current* rules, but current source has no caller that uses it for order validation. The targeted trading-only search found `InstrumentRules`, `RuleObservation`, and this port declaration, but no validation function/service or refresh-before-validation call path. Do not hide ordering enforcement in a docstring-only contract test; give the validation service a behavioral test that invokes this method on every validation call.

### `tests/fixtures/fake_exchange.py` — deterministic rule-aware fake gateway

**Closest analog:** `ReconciliationOnlyGateway`, `tests/fixtures/fake_exchange.py:9-30`.

```python
class ReconciliationOnlyGateway:
    """Return scripted lookup evidence and fail if recovery tries to submit an order."""

    def __init__(self, evidence_by_client_order_id: Mapping[str, GatewayEvidence | None]) -> None:
        self._evidence_by_client_order_id = dict(evidence_by_client_order_id)
        self.lookup_client_order_ids: list[str] = []
        self.submit_call_count = 0

    def lookup_order_by_client_id(self, client_order_id: str) -> GatewayEvidence | None:
        """Record the persisted client ID lookup and return its scripted evidence."""
        self.lookup_client_order_ids.append(client_order_id)
        return self._evidence_by_client_order_id.get(client_order_id)

    def set_evidence(self, client_order_id: str, evidence: GatewayEvidence | None) -> None:
        """Replace one deterministic lookup response for a later recovery attempt."""
        self._evidence_by_client_order_id[client_order_id] = evidence
```

Extend this fixture file with a deliberately minimal rule fake (or a separately named sibling fake) that:

1. accepts a scripted sequence/mapping of `RuleObservation` values or a typed `GatewayUnavailableError`,
2. appends every requested symbol to `instrument_rule_symbols`, and
3. consumes one scripted response per call so two validation attempts prove two fresh lookups.

Keep it synchronous, in-memory, credential-free, and deterministic. Do not turn it into a broad concrete implementation of all eleven `TradingGateway` methods; the existing fake intentionally implements only the recovery surface it exercises. A rule fake should similarly implement only `get_instrument_rules` unless a test genuinely needs more.

### `tests/unit/execution/test_order_validation.py` — deterministic rule semantics

**Closest analog:** `tests/unit/execution/test_models.py:37-97` and `tests/fixtures/execution_factories.py:12-27`.

```python
# tests/fixtures/execution_factories.py:12-27
def make_spot_command(**overrides: object) -> ExecutionCommand:
    """Build a valid immutable spot command with deterministic identifiers."""
    values: dict[str, object] = {
        "command_id": "command-001",
        "logical_command_key": "logical-command-001",
        "client_order_id": "client-order-001",
        "mode": Mode.PAPER,
        "account_id": "paper-account",
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("0.125"),
        "price": Decimal("42000.50"),
        "context": SpotOrderContext(),
    }
    values.update(overrides)
    return ExecutionCommand(**values)  # type: ignore[arg-type]
```

```python
# tests/unit/execution/test_models.py:37-49

def test_decimal_ingress_accepts_decimal_and_text_but_rejects_unsafe_values() -> None:
    """Canonical execution values reject floats and non-finite numeric inputs."""
    decimal_command = make_spot_command(quantity=Decimal("0.125"), price=Decimal("42.50"))
    text_command = make_spot_command(quantity="0.125", price="42.50")

    assert decimal_command.quantity == Decimal("0.125")
    assert text_command.price == Decimal("42.50")

    for value in (0.125, "NaN", Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(DecimalValueError):
            make_spot_command(quantity=value)
```

Use the deterministic `make_spot_command` factory, explicit `Decimal("...")` values, fixed `datetime(..., tzinfo=UTC)` observations, short behavioral assertions, and `pytest.raises` for invalid cases. Unit coverage should directly exercise the pure rule calculation: valid limit command; off-tick price; off-step quantity; below minimum quantity; below minimum notional; symbol mismatch; and any explicitly chosen boundary/equality semantics.

**Caution:** There is no existing rule-validation algorithm to copy. The planner must specify the exact acceptance rule (for example, whether off-tick values are rejected versus quantized). Do not silently round a command during validation; a validator that changes a command conflicts with the immutable-command pattern and obscures the operator-approved request.

### `tests/property/execution/test_rule_validation_properties.py` — Decimal boundary properties

**Closest analog:** `tests/property/execution/test_decimal_invariants.py:19-38`.

```python
FINITE_DECIMALS = st.decimals(allow_nan=False, allow_infinity=False, places=6)


@given(FINITE_DECIMALS)
def test_finite_decimals_round_trip_through_canonical_domain_serialization(value: Decimal) -> None:
    """Canonical Decimal text is stable through parsing and command serialization."""
    text = decimal_to_canonical(value)
    command_value = value.copy_abs() if value else Decimal("1")
    command_text = decimal_to_canonical(command_value)
    command = make_spot_command(quantity=command_text)

    assert decimal_to_canonical(decimal_from_canonical(text)) == text
    assert command.to_canonical_dict()["quantity"] == command_text
```

Keep `pytestmark = pytest.mark.property` at module level, use Hypothesis `@given`, and generate bounded finite Decimal values. The high-value property for this gap is that exact multiples of a positive tick/step are accepted and values displaced by a non-zero fractional increment are rejected without float conversion. Keep generated values bounded and normalize them with existing canonical Decimal helpers before constructing commands.

### `tests/integration/execution/test_refresh_before_validation.py` — fresh lookup ordering

**Closest analog:** `tests/integration/execution/test_uncertain_recovery.py:16-91`.

```python
pytestmark = pytest.mark.integration


def test_recovery_after_reopen_queries_only_first_client_id_and_never_submits(
    execution_database_path: Path,
) -> None:
    ...
    gateway = ReconciliationOnlyGateway({admission.client_order_id: None})
    recovery = RecoveryService(ledger=reopened, gateway=gateway)

    results = recovery.recover_startup()
    ...
    assert gateway.lookup_client_order_ids == [admission.client_order_id]
    assert gateway.submit_call_count == 0
```

Use the same marker/import/factory style, but this NFR-02 test should remain offline and should not require SQLite unless the selected public validation entry point actually depends on it. Construct the injected validation service with the scripted rule fake and assert all of the following:

1. one validation attempt asks `get_instrument_rules(command.symbol)` before returning a validation outcome;
2. two validation attempts ask twice (and can observe different scripted rule sets), proving no in-service stale-rule cache;
3. a gateway rule-fetch failure returns/raises the chosen typed failure and does not validate using a prior successful observation; and
4. a mismatched-symbol observation is rejected before the returned rules are applied.

The existing recovery integration test demonstrates the desired causal style: observe actual fake call history and assert the externally visible result, rather than asserting source text or mocking an internal implementation detail.

## Shared Patterns

### Canonical errors and fail-closed boundaries

**Source:** `pa_agent/trading/domain/errors.py:4-21` and `pa_agent/trading/ports/gateway.py:21-28`.

```python
class TradingDomainError(Exception):
    """Base class for canonical execution-domain validation failures."""


class DecimalValueError(TradingDomainError, TypeError):
    """Raised when a value is not a finite, exact trading Decimal."""
```

```python
class TradingGatewayError(TradingDomainError):
    """Base typed failure a gateway may raise without exposing transport details."""


class GatewayUnavailableError(TradingGatewayError):
    """Raised when a gateway cannot obtain requested canonical evidence."""
```

The validator should surface a typed domain validation failure for deterministic rule rejection and preserve typed gateway failures for unavailable fresh metadata. Do not return a permissive fallback result, silently use stale rules, or leak raw venue exceptions/payloads.

### Existing validation ordering is lifecycle-only, not order-rule validation

**Source:** `pa_agent/trading/domain/lifecycle.py:61-99`.

```python
def assert_transition(
    previous: OrderState,
    event: LifecycleEvent,
    *,
    evidence: GatewayEvidence | None = None,
) -> OrderState:
    """Validate and return the next state without mutating storage or gateway state.

    Local timeout, cancellation, stream-gap, and malformed-acknowledgement events
    only retain an explicitly unresolved state.  Terminal states always require
    normalized external evidence whose state agrees with the requested transition.
    """
```

This is the project’s pure-validation precedent: a deterministic function validates supplied canonical inputs and makes no persistence/gateway mutation. It is not an order-rule validation analog and must not be repurposed to conceal metadata refresh. Keep the new pure rule check separate; let the injected application service enforce the fetch-before-check sequence.

## No Analog Found

| Needed behavior | Search scope | Result and planner direction |
|---|---|---|
| Order rule validator | `pa_agent/trading`, `tests/unit/execution`, `tests/property/execution`, `tests/integration/execution` | No order-validation function/service exists. Create one small pure deterministic rule-check function plus the injected service that fetches `RuleObservation` immediately before invoking it. |
| Freshness cache/TTL policy | same trading-only scope | No cache or rule-age policy exists. Do not introduce a speculative TTL; prove freshness by gateway invocation per validation attempt. |
| Rule-aware gateway fake | `tests/fixtures/fake_exchange.py` | Only reconciliation lookup is currently faked. Add the smallest scripted `get_instrument_rules` fake necessary for ordering tests. |

## Metadata

**Analog search scope:** `pa_agent/trading/`; `tests/fixtures/execution_factories.py`; `tests/fixtures/fake_exchange.py`; `tests/unit/execution/`; `tests/property/execution/`; `tests/integration/execution/`.  
**Files read:** 17 phase/source/test artifacts.  
**Pattern extraction date:** 2026-07-11.
