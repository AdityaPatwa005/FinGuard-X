"""Deterministic, explainable rule evaluations for completed customer transfers.

This module returns independent rule outcomes only. Rule severities are
descriptive labels, not a combined risk score, alert, or response decision.
Defaults are conservative starting points and are not production-calibrated.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from transaction_features import (
    DEFAULT_MINIMUM_BASELINE_TRANSACTIONS,
    TransactionFeatureSet,
    extract_transaction_features,
)


class RuleOutcome(str, Enum):
    TRIGGERED = "TRIGGERED"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    NOT_EVALUATED = "NOT_EVALUATED"


class RuleSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RuleConfiguration:
    """Central, explicitly uncalibrated defaults for the initial rule set."""

    rapid_burst_minimum_count_5m: int = 5
    minimum_baseline_transactions: int = DEFAULT_MINIMUM_BASELINE_TRANSACTIONS
    unusual_amount_median_multiplier: Decimal = Decimal("4")
    unusual_amount_minimum_increase: Decimal = Decimal("10000.00")
    new_beneficiary_minimum_outgoing_count_1h: int = 6
    rapid_distribution_minimum_distinct_receivers_24h: int = 8
    outgoing_volume_window: Literal["1h", "24h"] = "24h"
    outgoing_volume_threshold: Decimal = Decimal("100000.00")

    def __post_init__(self) -> None:
        positive_ints = (
            ("rapid_burst_minimum_count_5m", self.rapid_burst_minimum_count_5m, 2),
            ("minimum_baseline_transactions", self.minimum_baseline_transactions, 1),
            ("new_beneficiary_minimum_outgoing_count_1h", self.new_beneficiary_minimum_outgoing_count_1h, 2),
            ("rapid_distribution_minimum_distinct_receivers_24h", self.rapid_distribution_minimum_distinct_receivers_24h, 2),
        )
        for name, value, minimum in positive_ints:
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}")

        decimals = (
            ("unusual_amount_median_multiplier", self.unusual_amount_median_multiplier),
            ("unusual_amount_minimum_increase", self.unusual_amount_minimum_increase),
            ("outgoing_volume_threshold", self.outgoing_volume_threshold),
        )
        for name, value in decimals:
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be a finite positive Decimal")
        if self.unusual_amount_median_multiplier <= Decimal("1"):
            raise ValueError("unusual_amount_median_multiplier must be greater than 1")
        if self.outgoing_volume_window not in ("1h", "24h"):
            raise ValueError("outgoing_volume_window must be '1h' or '24h'")


DEFAULT_RULE_CONFIGURATION = RuleConfiguration()


@dataclass(frozen=True)
class EvidenceItem:
    name: str
    value: Decimal | int | bool | str
    unit: str | None = None


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    version: str
    name: str
    description: str
    required_features: tuple[str, ...]
    minimum_history: str
    outcome: RuleOutcome
    severity: RuleSeverity
    explanation: str
    evidence: tuple[EvidenceItem, ...] = ()
    limitation: str | None = None


@dataclass(frozen=True)
class DetectionRun:
    transaction_id: UUID
    eligible: bool
    rule_results: tuple[RuleResult, ...]


@dataclass(frozen=True)
class _RuleSpec:
    rule_id: str
    version: str
    name: str
    description: str
    required_features: tuple[str, ...]
    minimum_history: str
    severity: RuleSeverity
    evaluator: Callable[..., RuleResult]


def _result(
    spec: _RuleSpec,
    outcome: RuleOutcome,
    explanation: str,
    *,
    evidence: tuple[EvidenceItem, ...] = (),
    limitation: str | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=spec.rule_id,
        version=spec.version,
        name=spec.name,
        description=spec.description,
        required_features=spec.required_features,
        minimum_history=spec.minimum_history,
        outcome=outcome,
        severity=spec.severity,
        explanation=explanation,
        evidence=evidence,
        limitation=limitation,
    )


def _not_evaluated(spec: _RuleSpec, reason: str) -> RuleResult:
    return _result(
        spec,
        RuleOutcome.NOT_EVALUATED,
        "Rule was not evaluated.",
        limitation=reason,
    )


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_money(value: object, *, allow_zero: bool = True) -> bool:
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    return value >= 0 if allow_zero else value > 0


def _eligibility_reason(features: TransactionFeatureSet) -> str | None:
    if features.context.transaction_type != "TRANSFER":
        return "Funding transactions are not customer-initiated transfer detections."
    if features.context.status != "COMPLETED":
        return "Only completed transfers are eligible for rule evaluation."
    if features.context.sender_account_id is None:
        return "The transfer has no sender account context."
    if features.context.currency != "INR":
        return "The initial rules support INR transfers only."
    if not _valid_money(features.context.amount, allow_zero=False):
        return "The evaluated amount is missing or invalid."
    return None


def _evaluate_rapid_burst(
    features: TransactionFeatureSet, config: RuleConfiguration, spec: _RuleSpec
) -> RuleResult:
    prior = features.velocity.prior_outgoing_transfer_5_minute_count
    if not _valid_count(prior):
        return _not_evaluated(spec, "Prior completed outgoing-transfer count for five minutes is unavailable or invalid.")
    measured = prior + 1  # The completed transaction under evaluation is included.
    evidence = (
        EvidenceItem("prior_outgoing_transfer_count_5m", prior, "transfers"),
        EvidenceItem("evaluated_transaction_included", True),
        EvidenceItem("outgoing_transfer_count_including_evaluated", measured, "transfers"),
        EvidenceItem("trigger_threshold", config.rapid_burst_minimum_count_5m, "transfers"),
    )
    if measured >= config.rapid_burst_minimum_count_5m:
        return _result(spec, RuleOutcome.TRIGGERED, "Outgoing transfer count reached the five-minute burst threshold.", evidence=evidence)
    return _result(spec, RuleOutcome.NOT_TRIGGERED, "Outgoing transfer count is below the five-minute burst threshold.", evidence=evidence)


def _evaluate_unusual_amount(
    features: TransactionFeatureSet, config: RuleConfiguration, spec: _RuleSpec
) -> RuleResult:
    behavior = features.customer_behavior
    count = behavior.historical_transfer_count
    if behavior.applicable is not True or not _valid_count(count):
        return _not_evaluated(spec, "Sender historical outgoing-transfer count is unavailable.")
    if count < config.minimum_baseline_transactions:
        return _result(
            spec,
            RuleOutcome.NOT_EVALUATED,
            "Sender historical baseline is below the configured minimum.",
            evidence=(
                EvidenceItem("historical_transfer_count", count, "transfers"),
                EvidenceItem("minimum_required_history", config.minimum_baseline_transactions, "transfers"),
            ),
            limitation=f"Insufficient sender history: {count} prior transfers; {config.minimum_baseline_transactions} required.",
        )
    if features.data_quality.outgoing_baseline_sufficient is not True:
        return _result(
            spec,
            RuleOutcome.NOT_EVALUATED,
            "Feature history quality does not confirm a reliable sender baseline.",
            evidence=(
                EvidenceItem("historical_transfer_count", count, "transfers"),
                EvidenceItem("minimum_required_history", config.minimum_baseline_transactions, "transfers"),
                EvidenceItem("feature_baseline_sufficient", False),
            ),
            limitation="Feature history quality marks the sender baseline insufficient.",
        )
    median = behavior.median_amount
    if not _valid_money(median, allow_zero=False):
        return _not_evaluated(spec, "Historical median amount is missing or invalid.")

    multiplier_threshold = median * config.unusual_amount_median_multiplier
    absolute_increase_threshold = median + config.unusual_amount_minimum_increase
    threshold = max(multiplier_threshold, absolute_increase_threshold)
    current = features.context.amount
    evidence = (
        EvidenceItem("current_transfer_amount", current, "INR"),
        EvidenceItem("historical_median_transfer_amount", median, "INR"),
        EvidenceItem("historical_transfer_count", count, "transfers"),
        EvidenceItem("median_multiplier", config.unusual_amount_median_multiplier, "x"),
        EvidenceItem("minimum_increase", config.unusual_amount_minimum_increase, "INR"),
        EvidenceItem("computed_trigger_threshold", threshold, "INR"),
    )
    if current >= threshold:
        return _result(spec, RuleOutcome.TRIGGERED, "Transfer amount materially exceeds the historical median-based threshold.", evidence=evidence)
    return _result(spec, RuleOutcome.NOT_TRIGGERED, "Transfer amount is below the historical median-based threshold.", evidence=evidence)


def _evaluate_new_beneficiary_context(
    features: TransactionFeatureSet, config: RuleConfiguration, spec: _RuleSpec
) -> RuleResult:
    beneficiary = features.beneficiary_behavior
    if beneficiary.applicable is not True or not isinstance(beneficiary.previously_received_from_sender, bool):
        return _not_evaluated(spec, "Prior sender-to-receiver transfer history is unavailable.")
    if beneficiary.previously_received_from_sender:
        return _result(
            spec,
            RuleOutcome.NOT_TRIGGERED,
            "The receiver has previously received a transfer from this sender.",
            evidence=(EvidenceItem("new_beneficiary", False),),
        )

    prior_velocity = features.velocity.prior_outgoing_transfer_1_hour_count
    if not _valid_count(prior_velocity):
        return _not_evaluated(spec, "Prior completed outgoing-transfer velocity for one hour is unavailable or invalid.")
    measured = prior_velocity + 1  # Include this transfer once.
    evidence = (
        EvidenceItem("new_beneficiary", True),
        EvidenceItem("prior_outgoing_transfer_count_1h", prior_velocity, "transfers"),
        EvidenceItem("outgoing_transfer_count_including_evaluated_1h", measured, "transfers"),
        EvidenceItem("independent_velocity_threshold", config.new_beneficiary_minimum_outgoing_count_1h, "transfers"),
    )
    if measured >= config.new_beneficiary_minimum_outgoing_count_1h:
        return _result(
            spec,
            RuleOutcome.TRIGGERED,
            "A new receiver coincides with elevated sender outgoing-transfer velocity.",
            evidence=evidence,
        )
    return _result(
        spec,
        RuleOutcome.NOT_TRIGGERED,
        "A new receiver alone is insufficient; outgoing-transfer velocity is below threshold.",
        evidence=evidence,
    )


def _evaluate_beneficiary_distribution(
    features: TransactionFeatureSet, config: RuleConfiguration, spec: _RuleSpec
) -> RuleResult:
    beneficiary = features.beneficiary_behavior
    prior_distinct = beneficiary.distinct_receivers_in_prior_24_hours
    seen_24h = beneficiary.receiver_seen_in_prior_24_hours
    if (
        beneficiary.applicable is not True
        or not _valid_count(prior_distinct)
        or not isinstance(seen_24h, bool)
    ):
        return _not_evaluated(spec, "Distinct receiver history or current receiver's 24-hour history is unavailable or invalid.")
    measured = prior_distinct + (0 if seen_24h else 1)
    evidence = (
        EvidenceItem("prior_distinct_receivers_24h", prior_distinct, "receivers"),
        EvidenceItem("receiver_seen_in_prior_24h", seen_24h),
        EvidenceItem("distinct_receivers_including_evaluated_24h", measured, "receivers"),
        EvidenceItem("trigger_threshold", config.rapid_distribution_minimum_distinct_receivers_24h, "receivers"),
    )
    if measured >= config.rapid_distribution_minimum_distinct_receivers_24h:
        return _result(spec, RuleOutcome.TRIGGERED, "Distinct receiver count reached the 24-hour distribution threshold.", evidence=evidence)
    return _result(spec, RuleOutcome.NOT_TRIGGERED, "Distinct receiver count is below the 24-hour distribution threshold.", evidence=evidence)


def _evaluate_high_outgoing_volume(
    features: TransactionFeatureSet, config: RuleConfiguration, spec: _RuleSpec
) -> RuleResult:
    prior = (
        features.outgoing_volume.prior_1_hour_amount
        if config.outgoing_volume_window == "1h"
        else features.outgoing_volume.prior_24_hour_amount
    )
    if not _valid_money(prior):
        return _not_evaluated(spec, f"Prior outgoing-transfer volume for {config.outgoing_volume_window} is unavailable or invalid.")
    cumulative = prior + features.context.amount
    evidence = (
        EvidenceItem("window", config.outgoing_volume_window),
        EvidenceItem("prior_outgoing_transfer_amount", prior, "INR"),
        EvidenceItem("evaluated_transfer_amount_included", features.context.amount, "INR"),
        EvidenceItem("cumulative_outgoing_amount_including_evaluated", cumulative, "INR"),
        EvidenceItem("trigger_threshold", config.outgoing_volume_threshold, "INR"),
    )
    if cumulative >= config.outgoing_volume_threshold:
        return _result(spec, RuleOutcome.TRIGGERED, "Cumulative outgoing transfer amount reached the configured window threshold.", evidence=evidence)
    return _result(spec, RuleOutcome.NOT_TRIGGERED, "Cumulative outgoing transfer amount is below the configured window threshold.", evidence=evidence)


_RULES = (
    _RuleSpec(
        rule_id="FGX.TRANSFER.RAPID_BURST",
        version="1.0",
        name="Rapid transaction burst",
        description="Detects excessive completed outgoing customer transfers within five minutes, including the evaluated transfer.",
        required_features=("velocity.prior_outgoing_transfer_5_minute_count", "context.amount", "context.status"),
        minimum_history="No baseline count; requires an available completed outgoing-transfer count for the prior five-minute window.",
        severity=RuleSeverity.HIGH,
        evaluator=_evaluate_rapid_burst,
    ),
    _RuleSpec(
        rule_id="FGX.TRANSFER.UNUSUAL_AMOUNT",
        version="1.0",
        name="Unusual transfer amount",
        description="Compares a transfer with the sender's median completed outgoing-transfer amount; this is a deterministic threshold, not a probability model.",
        required_features=("context.amount", "customer_behavior.historical_transfer_count", "customer_behavior.median_amount", "data_quality.outgoing_baseline_sufficient"),
        minimum_history="At least the configured minimum_baseline_transactions prior completed outgoing transfers.",
        severity=RuleSeverity.MEDIUM,
        evaluator=_evaluate_unusual_amount,
    ),
    _RuleSpec(
        rule_id="FGX.TRANSFER.NEW_BENEFICIARY_CONTEXT",
        version="1.0",
        name="New beneficiary with unusual context",
        description="Requires both a new receiver and elevated completed outgoing-transfer velocity; newness alone does not trigger.",
        required_features=("beneficiary_behavior.previously_received_from_sender", "velocity.prior_outgoing_transfer_1_hour_count"),
        minimum_history="No fixed count threshold for newness; requires complete prior sender-to-receiver history and hourly outgoing-transfer velocity.",
        severity=RuleSeverity.MEDIUM,
        evaluator=_evaluate_new_beneficiary_context,
    ),
    _RuleSpec(
        rule_id="FGX.TRANSFER.BENEFICIARY_DISTRIBUTION",
        version="1.0",
        name="Rapid beneficiary distribution",
        description="Detects a high count of distinct transaction receivers in the prior 24-hour window, including the evaluated receiver once.",
        required_features=("beneficiary_behavior.distinct_receivers_in_prior_24_hours", "beneficiary_behavior.receiver_seen_in_prior_24_hours"),
        minimum_history="No numeric minimum; requires a complete preceding 24-hour window.",
        severity=RuleSeverity.MEDIUM,
        evaluator=_evaluate_beneficiary_distribution,
    ),
    _RuleSpec(
        rule_id="FGX.TRANSFER.HIGH_OUTGOING_VOLUME",
        version="1.0",
        name="High outgoing volume",
        description="Detects cumulative completed outgoing transfer value over the selected supported window, including the evaluated transfer.",
        required_features=("context.amount", "outgoing_volume.prior_1_hour_amount or prior_24_hour_amount"),
        minimum_history="No numeric minimum; an empty complete window is represented as zero prior outgoing volume.",
        severity=RuleSeverity.HIGH,
        evaluator=_evaluate_high_outgoing_volume,
    ),
)


def _evaluate_one_rule(
    spec: _RuleSpec,
    features: TransactionFeatureSet,
    configuration: RuleConfiguration,
) -> RuleResult:
    reason = _eligibility_reason(features)
    if reason:
        return _not_evaluated(spec, reason)
    try:
        return spec.evaluator(features, configuration, spec)
    except Exception as exc:
        return _not_evaluated(
            spec,
            f"Rule evaluation failed safely ({type(exc).__name__}); feature values were unavailable or invalid.",
        )


def evaluate_rapid_transaction_burst(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> RuleResult:
    return _evaluate_one_rule(_RULES[0], features, configuration)


def evaluate_unusual_transfer_amount(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> RuleResult:
    return _evaluate_one_rule(_RULES[1], features, configuration)


def evaluate_new_beneficiary_context(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> RuleResult:
    return _evaluate_one_rule(_RULES[2], features, configuration)


def evaluate_rapid_beneficiary_distribution(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> RuleResult:
    return _evaluate_one_rule(_RULES[3], features, configuration)


def evaluate_high_outgoing_volume(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> RuleResult:
    return _evaluate_one_rule(_RULES[4], features, configuration)


def evaluate_transfer_features(
    features: TransactionFeatureSet,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> DetectionRun:
    """Evaluate every rule against one shared feature result, without side effects."""
    reason = _eligibility_reason(features)
    results = tuple(
        _not_evaluated(spec, reason)
        if reason
        else _evaluate_one_rule(spec, features, configuration)
        for spec in _RULES
    )
    return DetectionRun(features.context.transaction_id, reason is None, results)


def evaluate_transaction(
    db: Session,
    transaction_id: UUID,
    configuration: RuleConfiguration = DEFAULT_RULE_CONFIGURATION,
) -> DetectionRun:
    """Extract once using this configuration's history requirement, then evaluate."""
    features = extract_transaction_features(
        db,
        transaction_id,
        minimum_baseline_transactions=configuration.minimum_baseline_transactions,
    )
    return evaluate_transfer_features(features, configuration)
