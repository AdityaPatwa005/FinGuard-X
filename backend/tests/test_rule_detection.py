import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from rule_detection import (
    DEFAULT_RULE_CONFIGURATION,
    DetectionRun,
    RuleConfiguration,
    RuleOutcome,
    RuleSeverity,
    RuleResult,
    evaluate_high_outgoing_volume,
    evaluate_new_beneficiary_context,
    evaluate_rapid_beneficiary_distribution,
    evaluate_rapid_transaction_burst,
    evaluate_transaction,
    evaluate_transfer_features,
    evaluate_unusual_transfer_amount,
)
from transaction_features import (
    BeneficiaryBehaviorFeatures,
    CustomerBehaviorFeatures,
    FeatureDataQuality,
    OutgoingVolumeFeatures,
    TemporalFeatures,
    TransactionContext,
    TransactionFeatureSet,
    TransactionVelocityFeatures,
)


NOW = datetime(2025, 10, 20, 14, 30, tzinfo=timezone.utc)
SENDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
RECEIVER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
TX_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

RULE_RAPID = "FGX.TRANSFER.RAPID_BURST"
RULE_AMOUNT = "FGX.TRANSFER.UNUSUAL_AMOUNT"
RULE_NEW_BENEFICIARY = "FGX.TRANSFER.NEW_BENEFICIARY_CONTEXT"
RULE_DISTRIBUTION = "FGX.TRANSFER.BENEFICIARY_DISTRIBUTION"
RULE_VOLUME = "FGX.TRANSFER.HIGH_OUTGOING_VOLUME"


def make_features(
    *,
    transaction_type="TRANSFER",
    status="COMPLETED",
    amount=Decimal("100.00"),
    sender_id=SENDER_ID,
    prior_5m=0,
    prior_1h=0,
    velocity_5m=0,
    velocity_1h=0,
    prior_distinct=0,
    receiver_seen_24h=False,
    beneficiary_seen=False,
    history_count=5,
    average=Decimal("1000.00"),
    median=Decimal("1000.00"),
    baseline_sufficient=True,
    prior_volume_1h=Decimal("0.00"),
    prior_volume_24h=Decimal("0.00"),
):
    applicable = transaction_type == "TRANSFER"
    return TransactionFeatureSet(
        context=TransactionContext(
            transaction_id=TX_ID,
            amount=amount,
            transaction_type=transaction_type,
            currency="INR",
            status=status,
            sender_account_id=sender_id if applicable else None,
            receiver_account_id=RECEIVER_ID,
            timestamp=NOW,
        ),
        velocity=TransactionVelocityFeatures(
            focal_account_id=SENDER_ID if applicable else RECEIVER_ID,
            focal_account_role="sender" if applicable else "receiver",
            prior_5_minute_count=prior_5m,
            prior_1_hour_count=prior_1h,
            prior_24_hour_count=prior_1h,
            prior_outgoing_transfer_5_minute_count=velocity_5m if applicable else None,
            prior_outgoing_transfer_1_hour_count=velocity_1h if applicable else None,
        ),
        outgoing_volume=OutgoingVolumeFeatures(
            prior_volume_1h if applicable else None,
            prior_volume_24h if applicable else None,
        ),
        customer_behavior=CustomerBehaviorFeatures(
            applicable=applicable,
            historical_transfer_count=history_count if applicable else None,
            average_amount=average if applicable else None,
            median_amount=median if applicable else None,
            amount_deviation_from_average=(
                amount - average
                if applicable and isinstance(amount, Decimal) and average is not None
                else None
            ),
        ),
        beneficiary_behavior=BeneficiaryBehaviorFeatures(
            applicable=applicable,
            previously_received_from_sender=beneficiary_seen if applicable else None,
            receiver_seen_in_prior_24_hours=receiver_seen_24h if applicable else None,
            distinct_receivers_in_prior_24_hours=prior_distinct if applicable else None,
        ),
        temporal=TemporalFeatures(hour_utc=NOW.hour, weekday_utc=NOW.weekday()),
        data_quality=FeatureDataQuality(
            prior_account_activity_in_24_hours=prior_1h > 0,
            historical_outgoing_transfer_history_available=(history_count > 0) if applicable else None,
            outgoing_baseline_sufficient=baseline_sufficient if applicable else None,
            minimum_baseline_transactions=5,
        ),
    )


def result_for(run: DetectionRun, rule_id: str) -> RuleResult:
    return next(result for result in run.rule_results if result.rule_id == rule_id)


class RuleDetectionTests(unittest.TestCase):
    def test_default_configuration_is_conservative_and_rule_severities_are_static(self):
        config = DEFAULT_RULE_CONFIGURATION
        self.assertEqual(config.rapid_burst_minimum_count_5m, 5)
        self.assertEqual(config.minimum_baseline_transactions, 5)
        self.assertEqual(config.unusual_amount_median_multiplier, Decimal("4"))
        self.assertEqual(config.unusual_amount_minimum_increase, Decimal("10000.00"))
        self.assertEqual(config.new_beneficiary_minimum_outgoing_count_1h, 6)
        self.assertEqual(config.rapid_distribution_minimum_distinct_receivers_24h, 8)
        self.assertEqual(config.outgoing_volume_window, "24h")
        self.assertEqual(config.outgoing_volume_threshold, Decimal("100000.00"))
        run = evaluate_transfer_features(make_features())
        severities = {result.rule_id: result.severity for result in run.rule_results}
        self.assertTrue(all(result.required_features for result in run.rule_results))
        self.assertTrue(all(result.minimum_history for result in run.rule_results))
        self.assertEqual(severities[RULE_RAPID], RuleSeverity.HIGH)
        self.assertEqual(severities[RULE_AMOUNT], RuleSeverity.MEDIUM)
        self.assertEqual(severities[RULE_NEW_BENEFICIARY], RuleSeverity.MEDIUM)
        self.assertEqual(severities[RULE_DISTRIBUTION], RuleSeverity.MEDIUM)
        self.assertEqual(severities[RULE_VOLUME], RuleSeverity.HIGH)

    def test_rapid_burst_includes_current_transfer_at_inclusive_threshold(self):
        run = evaluate_transfer_features(make_features(velocity_5m=4))
        result = result_for(run, RULE_RAPID)
        self.assertEqual(result.outcome, RuleOutcome.TRIGGERED)
        evidence = {item.name: item.value for item in result.evidence}
        self.assertEqual(evidence["outgoing_transfer_count_including_evaluated"], 5)
        below = result_for(evaluate_transfer_features(make_features(velocity_5m=3)), RULE_RAPID)
        self.assertEqual(below.outcome, RuleOutcome.NOT_TRIGGERED)

    def test_unusual_amount_threshold_boundary_and_zero_variance(self):
        at_threshold = make_features(amount=Decimal("40000.00"), median=Decimal("10000.00"))
        below = make_features(amount=Decimal("39999.99"), median=Decimal("10000.00"))
        self.assertEqual(result_for(evaluate_transfer_features(at_threshold), RULE_AMOUNT).outcome, RuleOutcome.TRIGGERED)
        self.assertEqual(result_for(evaluate_transfer_features(below), RULE_AMOUNT).outcome, RuleOutcome.NOT_TRIGGERED)

        # A constant historical baseline needs no variance division or normality assumption.
        constant = make_features(amount=Decimal("20.00"), average=Decimal("10.00"), median=Decimal("10.00"))
        self.assertEqual(result_for(evaluate_transfer_features(constant), RULE_AMOUNT).outcome, RuleOutcome.NOT_TRIGGERED)
        unusual = make_features(amount=Decimal("10010.00"), average=Decimal("10.00"), median=Decimal("10.00"))
        self.assertEqual(result_for(evaluate_transfer_features(unusual), RULE_AMOUNT).outcome, RuleOutcome.TRIGGERED)

    def test_unusual_amount_explicitly_reports_insufficient_history(self):
        features = make_features(history_count=4, baseline_sufficient=False)
        result = result_for(evaluate_transfer_features(features), RULE_AMOUNT)
        self.assertEqual(result.outcome, RuleOutcome.NOT_EVALUATED)
        self.assertIn("4 prior transfers", result.limitation)
        self.assertIn("5 required", result.limitation)
        evidence = {item.name: item.value for item in result.evidence}
        self.assertEqual(evidence["historical_transfer_count"], 4)
        self.assertEqual(evidence["minimum_required_history"], 5)

    def test_new_beneficiary_alone_does_not_trigger_but_velocity_context_does(self):
        alone = result_for(
            evaluate_transfer_features(make_features(beneficiary_seen=False, velocity_1h=0)),
            RULE_NEW_BENEFICIARY,
        )
        self.assertEqual(alone.outcome, RuleOutcome.NOT_TRIGGERED)
        self.assertIn("alone is insufficient", alone.explanation)

        at_threshold = result_for(
            evaluate_transfer_features(make_features(beneficiary_seen=False, velocity_1h=5)),
            RULE_NEW_BENEFICIARY,
        )
        self.assertEqual(at_threshold.outcome, RuleOutcome.TRIGGERED)
        evidence_names = {item.name for item in at_threshold.evidence}
        self.assertIn("new_beneficiary", evidence_names)
        self.assertIn("outgoing_transfer_count_including_evaluated_1h", evidence_names)
        self.assertNotIn("current_transfer_amount", evidence_names)
        self.assertNotIn("unusual_amount_threshold", evidence_names)

        known = result_for(
            evaluate_transfer_features(make_features(beneficiary_seen=True, velocity_1h=9)),
            RULE_NEW_BENEFICIARY,
        )
        self.assertEqual(known.outcome, RuleOutcome.NOT_TRIGGERED)

    def test_beneficiary_distribution_counts_current_receiver_once(self):
        new_receiver_at_threshold = make_features(prior_distinct=7, receiver_seen_24h=False)
        seen_receiver = make_features(prior_distinct=7, receiver_seen_24h=True)
        self.assertEqual(
            result_for(evaluate_transfer_features(new_receiver_at_threshold), RULE_DISTRIBUTION).outcome,
            RuleOutcome.TRIGGERED,
        )
        self.assertEqual(
            result_for(evaluate_transfer_features(seen_receiver), RULE_DISTRIBUTION).outcome,
            RuleOutcome.NOT_TRIGGERED,
        )

    def test_high_outgoing_volume_is_decimal_safe_and_window_configurable(self):
        at_threshold = make_features(amount=Decimal("0.01"), prior_volume_24h=Decimal("99999.99"))
        below = make_features(amount=Decimal("0.01"), prior_volume_24h=Decimal("99999.98"))
        self.assertEqual(result_for(evaluate_transfer_features(at_threshold), RULE_VOLUME).outcome, RuleOutcome.TRIGGERED)
        self.assertEqual(result_for(evaluate_transfer_features(below), RULE_VOLUME).outcome, RuleOutcome.NOT_TRIGGERED)
        evidence = {
            item.name: item.value
            for item in result_for(evaluate_transfer_features(at_threshold), RULE_VOLUME).evidence
        }
        self.assertEqual(
            evidence["cumulative_outgoing_amount_including_evaluated"],
            Decimal("100000.00"),
        )

        one_hour = RuleConfiguration(outgoing_volume_window="1h", outgoing_volume_threshold=Decimal("50.00"))
        one_hour_result = result_for(
            evaluate_transfer_features(
                make_features(amount=Decimal("1.00"), prior_volume_1h=Decimal("49.00")),
                one_hour,
            ),
            RULE_VOLUME,
        )
        self.assertEqual(one_hour_result.outcome, RuleOutcome.TRIGGERED)

    def test_overlapping_rules_keep_separate_rule_evidence_without_alert_deduplication(self):
        features = make_features(
            amount=Decimal("40000.00"),
            median=Decimal("10000.00"),
            average=Decimal("10000.00"),
            velocity_5m=4,
            velocity_1h=5,
            beneficiary_seen=False,
            prior_distinct=7,
            receiver_seen_24h=False,
            prior_volume_24h=Decimal("60000.00"),
        )
        run = evaluate_transfer_features(features)
        triggered = [result for result in run.rule_results if result.outcome == RuleOutcome.TRIGGERED]
        self.assertEqual(len(triggered), 5)
        self.assertEqual(len({result.rule_id for result in triggered}), 5)
        self.assertTrue(all(result.evidence for result in triggered))
        self.assertFalse(hasattr(run, "risk_score"))
        self.assertFalse(hasattr(run, "alerts"))

    def test_funding_and_noncompleted_transactions_are_not_evaluated(self):
        for features in (
            make_features(transaction_type="FUNDING"),
            make_features(status="FAILED"),
            make_features(status="PENDING"),
            make_features(sender_id=None),
        ):
            run = evaluate_transfer_features(features)
            self.assertFalse(run.eligible)
            self.assertEqual(len(run.rule_results), 5)
            self.assertTrue(all(row.outcome == RuleOutcome.NOT_EVALUATED for row in run.rule_results))
            self.assertTrue(all(row.limitation for row in run.rule_results))

    def test_missing_and_invalid_values_only_invalidate_the_relevant_rules(self):
        missing_velocity = replace(
            make_features(velocity_5m=None),
            customer_behavior=CustomerBehaviorFeatures(True, 5, Decimal("1000"), Decimal("1000"), Decimal("0")),
        )
        run = evaluate_transfer_features(missing_velocity)
        self.assertEqual(result_for(run, RULE_RAPID).outcome, RuleOutcome.NOT_EVALUATED)
        self.assertEqual(result_for(run, RULE_AMOUNT).outcome, RuleOutcome.NOT_TRIGGERED)
        self.assertEqual(result_for(run, RULE_VOLUME).outcome, RuleOutcome.NOT_TRIGGERED)

        missing_beneficiary = replace(
            make_features(),
            beneficiary_behavior=BeneficiaryBehaviorFeatures(True, None, None, None),
        )
        beneficiary_run = evaluate_transfer_features(missing_beneficiary)
        self.assertEqual(result_for(beneficiary_run, RULE_NEW_BENEFICIARY).outcome, RuleOutcome.NOT_EVALUATED)
        self.assertEqual(result_for(beneficiary_run, RULE_DISTRIBUTION).outcome, RuleOutcome.NOT_EVALUATED)

        invalid_amount = make_features(amount=float("nan"))
        invalid_run = evaluate_transfer_features(invalid_amount)
        self.assertFalse(invalid_run.eligible)
        self.assertTrue(all(row.outcome == RuleOutcome.NOT_EVALUATED for row in invalid_run.rule_results))

    def test_rule_exceptions_are_reported_without_suppressing_other_results(self):
        features = replace(make_features(beneficiary_seen=True), velocity=None)
        run = evaluate_transfer_features(features)
        self.assertEqual(result_for(run, RULE_RAPID).outcome, RuleOutcome.NOT_EVALUATED)
        self.assertEqual(result_for(run, RULE_AMOUNT).outcome, RuleOutcome.NOT_TRIGGERED)
        self.assertEqual(result_for(run, RULE_NEW_BENEFICIARY).outcome, RuleOutcome.NOT_TRIGGERED)

    def test_repeated_evaluation_is_deterministic_and_extracts_once(self):
        features = make_features(velocity_5m=4)
        self.assertEqual(evaluate_transfer_features(features), evaluate_transfer_features(features))
        with patch("rule_detection.extract_transaction_features", return_value=features) as extractor:
            result = evaluate_transaction(object(), TX_ID)
        extractor.assert_called_once()
        self.assertEqual(result, evaluate_transfer_features(features))

    def test_each_rule_is_independently_callable(self):
        features = make_features(
            amount=Decimal("40000.00"),
            median=Decimal("10000.00"),
            velocity_5m=4,
            velocity_1h=5,
            beneficiary_seen=False,
            prior_distinct=7,
            receiver_seen_24h=False,
            prior_volume_24h=Decimal("60000.00"),
        )
        individual = (
            evaluate_rapid_transaction_burst(features),
            evaluate_unusual_transfer_amount(features),
            evaluate_new_beneficiary_context(features),
            evaluate_rapid_beneficiary_distribution(features),
            evaluate_high_outgoing_volume(features),
        )
        all_rules = evaluate_transfer_features(features).rule_results
        self.assertEqual(individual, all_rules)

    def test_configuration_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            RuleConfiguration(rapid_burst_minimum_count_5m=1)
        with self.assertRaises(ValueError):
            RuleConfiguration(minimum_baseline_transactions=0)
        with self.assertRaises(ValueError):
            RuleConfiguration(unusual_amount_median_multiplier=Decimal("1"))
        with self.assertRaises(ValueError):
            RuleConfiguration(outgoing_volume_threshold=Decimal("NaN"))
        with self.assertRaises(ValueError):
            RuleConfiguration(outgoing_volume_window="30d")
if __name__ == "__main__":
    unittest.main()
