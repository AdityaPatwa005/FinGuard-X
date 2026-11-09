"""Versioned, explainable incident risk assessment without severity summation."""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable
from uuid import UUID


class RiskBand(str, Enum):
    LOW = "LOW"
    GUARDED = "GUARDED"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class IncidentDetectionEvidence:
    detection_id: UUID
    rule_id: str
    evaluation_outcome: str
    evidence: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class RiskScoringPolicy:
    """Engineering weights; these values are not calibrated fraud probabilities."""

    version: str = "1.0"
    velocity_weight: int = 30
    amount_anomaly_weight: int = 25
    beneficiary_behavior_weight: int = 25
    transaction_volume_weight: int = 20
    guarded_minimum: int = 25
    elevated_minimum: int = 50
    critical_minimum: int = 75

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 24:
            raise ValueError("Risk policy version must contain 1 to 24 characters")
        weights = (
            self.velocity_weight,
            self.amount_anomaly_weight,
            self.beneficiary_behavior_weight,
            self.transaction_volume_weight,
        )
        if any(isinstance(weight, bool) or not isinstance(weight, int) or weight < 0 for weight in weights):
            raise ValueError("Risk family weights must be nonnegative integers")
        if sum(weights) > 100:
            raise ValueError("Risk family weights must sum to no more than 100")
        boundaries = (self.guarded_minimum, self.elevated_minimum, self.critical_minimum)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in boundaries):
            raise ValueError("Risk band boundaries must be integers")
        if not (1 <= self.guarded_minimum < self.elevated_minimum < self.critical_minimum <= 100):
            raise ValueError("Risk band boundaries must increase from 1 through 100")

    @property
    def family_weights(self) -> dict[str, int]:
        return {
            "velocity": self.velocity_weight,
            "amount_anomaly": self.amount_anomaly_weight,
            "beneficiary_behavior": self.beneficiary_behavior_weight,
            "transaction_volume": self.transaction_volume_weight,
        }


DEFAULT_RISK_SCORING_POLICY = RiskScoringPolicy()


@dataclass(frozen=True)
class RiskFamilyContribution:
    family: str
    weight: int
    rule_ids: tuple[str, ...]
    detection_ids: tuple[UUID, ...]
    overlapping_detection_count: int
    evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class IncidentRiskAssessment:
    score: int
    band: RiskBand
    policy_version: str
    explanation: str
    family_contributions: tuple[RiskFamilyContribution, ...]

    def to_json(self) -> list[dict[str, object]]:
        return [
            {
                "family": contribution.family,
                "weight": contribution.weight,
                "rule_ids": list(contribution.rule_ids),
                "detection_ids": [str(value) for value in contribution.detection_ids],
                "overlapping_detection_count": contribution.overlapping_detection_count,
                "evidence": list(contribution.evidence),
            }
            for contribution in self.family_contributions
        ]


RULE_EVIDENCE_FAMILIES = {
    "FGX.TRANSFER.RAPID_BURST": "velocity",
    "FGX.TRANSFER.UNUSUAL_AMOUNT": "amount_anomaly",
    # This composite rule is counted in beneficiary behavior only; its hourly
    # velocity evidence is not separately added to the velocity family's weight.
    "FGX.TRANSFER.NEW_BENEFICIARY_CONTEXT": "beneficiary_behavior",
    "FGX.TRANSFER.BENEFICIARY_DISTRIBUTION": "beneficiary_behavior",
    "FGX.TRANSFER.HIGH_OUTGOING_VOLUME": "transaction_volume",
}


def risk_band_for_score(score: int, policy: RiskScoringPolicy = DEFAULT_RISK_SCORING_POLICY) -> RiskBand:
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("Risk score must be an integer between 0 and 100")
    if score >= policy.critical_minimum:
        return RiskBand.CRITICAL
    if score >= policy.elevated_minimum:
        return RiskBand.ELEVATED
    if score >= policy.guarded_minimum:
        return RiskBand.GUARDED
    return RiskBand.LOW


def assess_incident_risk(
    detections: Iterable[IncidentDetectionEvidence],
    policy: RiskScoringPolicy = DEFAULT_RISK_SCORING_POLICY,
) -> IncidentRiskAssessment:
    """Weight each evidence family once, independent of severity or replay count."""
    grouped: dict[str, dict[UUID, IncidentDetectionEvidence]] = {}
    for detection in detections:
        if detection.evaluation_outcome != "TRIGGERED":
            continue
        family = RULE_EVIDENCE_FAMILIES.get(detection.rule_id, "unclassified")
        grouped.setdefault(family, {})[detection.detection_id] = detection

    weights = policy.family_weights
    contributions = tuple(
        RiskFamilyContribution(
            family=family,
            weight=weights.get(family, 0),
            rule_ids=tuple(sorted({row.rule_id for row in rule_ids.values()})),
            detection_ids=tuple(sorted(rule_ids, key=str)),
            overlapping_detection_count=max(0, len(rule_ids) - 1),
            evidence=tuple(
                {
                    "detection_id": str(detection_id),
                    "rule_id": rule_ids[detection_id].rule_id,
                    "values": list(rule_ids[detection_id].evidence),
                }
                for detection_id in sorted(rule_ids, key=str)
            ),
        )
        for family, rule_ids in sorted(grouped.items())
    )
    score = min(100, sum(contribution.weight for contribution in contributions))
    band = risk_band_for_score(score, policy)
    contributing = [item for item in contributions if item.weight > 0]
    if contributing:
        family_text = ", ".join(f"{item.family} (+{item.weight})" for item in contributing)
        overlap_count = sum(item.overlapping_detection_count for item in contributions)
        overlap_text = (
            f" Duplicate family evidence was counted once ({overlap_count} overlapping detection(s))."
            if overlap_count
            else ""
        )
        explanation = (
            f"Score {score}/100 from independent evidence families: {family_text}. "
            f"Family weights are capped at one contribution each under policy {policy.version}."
            f"{overlap_text}"
        )
    else:
        explanation = f"Score 0/100; no mapped triggered evidence families under policy {policy.version}."
    return IncidentRiskAssessment(score, band, policy.version, explanation, contributions)
