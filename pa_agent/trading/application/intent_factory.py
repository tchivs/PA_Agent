"""Pure conversion from frozen completed analysis to a candidate execution intent."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pa_agent.trading.domain.approval import (
    AnalysisRecommendation,
    CandidateExecutionIntent,
    ExecutionTarget,
    SourceAnalysisSnapshot,
    digest_analysis_recommendation,
)
from pa_agent.trading.domain.errors import ConversionRejection, ConversionRejectionReason
from pa_agent.trading.domain.models import (
    Mode,
    IsolatedMarginOrderContext,
    OrderType,
    ProductContext,
    ProductType,
    Side,
    SpotOrderContext,
    UsdtPerpetualOrderContext,
)


class IntentFactory:
    """Validate a frozen snapshot and create a non-submittable candidate proposal."""

    SOURCE_ANALYSIS_MAX_AGE = timedelta(seconds=60)

    def __init__(self, *, utc_now: Callable[[], datetime] | None = None) -> None:
        self._utc_now = utc_now or (lambda: datetime.now(UTC))

    def propose(
        self,
        snapshot: SourceAnalysisSnapshot,
        target: ExecutionTarget,
        context: ProductContext | None = None,
    ) -> CandidateExecutionIntent:
        """Return a Paper candidate with its immutable product context bound at conversion."""
        if type(snapshot) is not SourceAnalysisSnapshot:
            raise ConversionRejection(ConversionRejectionReason.INVALID_SNAPSHOT_TYPE)
        if type(target) is not ExecutionTarget:
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET)
        self._validate_snapshot(snapshot)
        self._validate_target(target)
        recommendation = snapshot.recommendation
        self._validate_recommendation(recommendation)
        context = self._validated_context(target, context)
        return CandidateExecutionIntent(
            source_id=snapshot.source_id,
            source_completed_at=snapshot.completed_at,
            source_schema_version=snapshot.schema_version,
            source_parser_version=snapshot.parser_version,
            source_decision_digest=snapshot.decision_digest,
            target=target,
            symbol=recommendation.symbol,
            side=recommendation.side,
            order_type=recommendation.order_type,
            quantity=recommendation.quantity,
            price=recommendation.price,
            risk_basis=recommendation.risk_basis,
            context=context,
        )

    def _validate_snapshot(self, snapshot: SourceAnalysisSnapshot) -> None:
        if not snapshot.source_id:
            raise ConversionRejection(ConversionRejectionReason.MISSING_SOURCE_ID)
        if not _is_aware(snapshot.completed_at):
            raise ConversionRejection(ConversionRejectionReason.INVALID_COMPLETION_TIME)
        now = self._utc_now()
        if not _is_aware(now) or snapshot.completed_at > now:
            raise ConversionRejection(ConversionRejectionReason.INVALID_COMPLETION_TIME)
        if now - snapshot.completed_at > self.SOURCE_ANALYSIS_MAX_AGE:
            raise ConversionRejection(ConversionRejectionReason.SOURCE_ANALYSIS_STALE)
        if not snapshot.schema_version or not snapshot.parser_version:
            raise ConversionRejection(ConversionRejectionReason.MISSING_SOURCE_VERSION)
        if not snapshot.decision_digest:
            raise ConversionRejection(ConversionRejectionReason.MISSING_DECISION_DIGEST)
        if snapshot.repaired:
            raise ConversionRejection(ConversionRejectionReason.REPAIRED_SOURCE)
        if snapshot.decision_digest != digest_analysis_recommendation(snapshot.recommendation):
            raise ConversionRejection(ConversionRejectionReason.DECISION_DIGEST_MISMATCH)

    @staticmethod
    def _validate_target(target: ExecutionTarget) -> None:
        if (
            not target.target_id
            or not target.account_id
            or target.mode is not Mode.PAPER
            or target.product not in ProductType
        ):
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET)

    @staticmethod
    def _validated_context(
        target: ExecutionTarget, context: ProductContext | None
    ) -> ProductContext:
        if context is None:
            if target.product is ProductType.SPOT:
                return SpotOrderContext()
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET)
        if type(context) not in (
            SpotOrderContext,
            IsolatedMarginOrderContext,
            UsdtPerpetualOrderContext,
        ):
            raise ConversionRejection(ConversionRejectionReason.MISSING_PRODUCT_CONTEXT)
        if context.product is not target.product:
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_TARGET)
        return context

    @staticmethod
    def _validate_recommendation(recommendation: AnalysisRecommendation) -> None:
        if not recommendation.symbol:
            raise ConversionRejection(ConversionRejectionReason.MISSING_PRODUCT_CONTEXT)
        if recommendation.side is None or type(recommendation.side) is not Side:
            raise ConversionRejection(ConversionRejectionReason.MISSING_DIRECTION)
        if type(recommendation.order_type) is not OrderType:
            raise ConversionRejection(ConversionRejectionReason.UNSUPPORTED_ORDER_TYPE)
        if recommendation.quantity is None or recommendation.quantity <= 0:
            raise ConversionRejection(ConversionRejectionReason.MISSING_QUANTITY_BASIS)
        if recommendation.risk_basis is None or recommendation.risk_basis <= 0:
            raise ConversionRejection(ConversionRejectionReason.MISSING_RISK_BASIS)
        if recommendation.order_type is OrderType.LIMIT:
            if recommendation.price is None or recommendation.price <= 0:
                raise ConversionRejection(ConversionRejectionReason.MISSING_PRICE_BASIS)
        elif recommendation.price is not None:
            raise ConversionRejection(ConversionRejectionReason.SEMANTIC_CONFLICT)


def _is_aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
