"""Scope-aligned discriminator used by the current operational optimization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any


EXPERIMENTAL_ARTIFACT_SOURCE = "B_TEAM_LATEST_SCOPE_ALIGNED_OPERATIONAL_DISCRIMINATOR"


def standardize_judgement(raw: dict[str, Any]) -> dict[str, Any]:
    """Expose the stable judgement fields consumed by Model A and infrastructure."""
    passed = bool(raw["threshold_pass"])
    return {
        "threshold_pass": passed,
        "threshold_passed": passed,
        "reject_reason": raw.get("reject_reason"),
        "profit_gap": float(raw.get("profit_gap", 0.0)),
        "revenue_gap": float(raw.get("revenue_gap", 0.0)),
        "waste_gap": float(raw.get("waste_gap", 0.0)),
    }


@dataclass
class ScopeAlignedExperimentalDiscriminator:
    """Operational Rule-aligned approval for one store and one close horizon."""

    alpha: float = 0.03
    profit_threshold: float | None = None
    no_discount_profit: float | None = None
    rule_policy_profit: float | None = None
    rule_waste_rate: float | None = None
    waste_target: float | None = None
    baseline_profit: float | None = None
    threshold_scope: str | None = None
    threshold_version: str | None = None
    evaluation_start: str | None = None
    evaluation_end: str | None = None
    store_id: str | None = None

    discriminator_version: str = "code2-latest-rule-scope-aligned-operational-v1"
    artifact_source: str = EXPERIMENTAL_ARTIFACT_SOURCE

    @property
    def is_calibrated(self) -> bool:
        return self.profit_threshold is not None

    def calibrate(
        self,
        no_discount_result: dict[str, Any],
        rule_policy_result: dict[str, Any],
    ) -> None:
        scope_keys = ("evaluation_scope", "evaluation_start", "evaluation_end", "store_id")
        mismatched = [
            key for key in scope_keys
            if str(no_discount_result.get(key)) != str(rule_policy_result.get(key))
        ]
        if mismatched:
            raise ValueError(f"Experimental baseline scopes differ: {mismatched}")
        none_profit = float(no_discount_result["metrics"]["expected_profit"])
        rule_profit = float(rule_policy_result["metrics"]["expected_profit"])
        rule_waste = float(rule_policy_result["metrics"]["expected_waste_rate"])
        if not all(math.isfinite(value) for value in (none_profit, rule_profit, rule_waste)):
            raise ValueError("Experimental baseline profit is not finite")
        self.no_discount_profit = none_profit
        self.rule_policy_profit = rule_profit
        self.baseline_profit = rule_profit
        threshold = rule_profit + float(self.alpha) * abs(rule_profit)
        self.profit_threshold = threshold
        self.rule_waste_rate = rule_waste
        self.waste_target = math.ceil(rule_waste * 1000.0) / 1000.0
        self.store_id = str(no_discount_result["store_id"])
        self.evaluation_start = str(no_discount_result["evaluation_start"])
        self.evaluation_end = str(no_discount_result["evaluation_end"])
        self.threshold_scope = (
            f"store_id={self.store_id}; {self.evaluation_start}..{self.evaluation_end}; "
            "same inventory snapshot and current_store_to_close horizon"
        )
        signature = (
            f"{self.store_id}|{self.evaluation_start}|{self.evaluation_end}|"
            f"{none_profit:.12g}|{rule_profit:.12g}|{rule_waste:.12g}|{self.alpha:.12g}"
        )
        self.threshold_version = (
            "scope-aligned-rule-profit-waste-v1-"
            + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
        )

    def evaluate(self, simulation_result: dict[str, Any]) -> dict[str, Any]:
        if not self.is_calibrated:
            raise RuntimeError("Scope-aligned experimental threshold has not been calibrated")
        profit = float(simulation_result["expected_profit"])
        threshold = float(self.profit_threshold)
        waste_rate = float(simulation_result["expected_waste_rate"])
        passed = waste_rate <= float(self.waste_target) and profit >= threshold
        warnings = [
            "SCOPE_ALIGNED_OPERATIONAL_RULE_BASELINE",
            "FORMULA_USES_RULE_PROFIT_PLUS_ALPHA_TIMES_ABSOLUTE_RULE_PROFIT",
        ]
        if float(self.baseline_profit) < 0:
            warnings.append("NEGATIVE_BASELINE_REQUIRES_LOSS_REDUCTION_BY_THRESHOLD_MARGIN")
        return {
            "threshold_pass": bool(passed),
            "threshold_passed": bool(passed),
            "reject_reason": None if passed else (
                "EXPECTED_WASTE_ABOVE_RULE_SCOPE_TARGET"
                if waste_rate > float(self.waste_target)
                else "EXPECTED_PROFIT_BELOW_RULE_SCOPE_THRESHOLD"
            ),
            "profit_gap": float(profit - threshold),
            "revenue_gap": 0.0,
            "waste_gap": float(self.waste_target - waste_rate),
            "profit_threshold": threshold,
            "threshold_margin_alpha": float(self.alpha),
            "discriminator_version": self.discriminator_version,
            "threshold_version": str(self.threshold_version),
            "artifact_source": self.artifact_source,
            "artifact_paths": {
                "formula_lineage": "src/model_b/experimental_discriminator.py",
                "runtime_adapter": "src/model_b/experimental_discriminator.py",
            },
            "threshold_scope": str(self.threshold_scope),
            "experimental_discriminator": True,
            "threshold_formula": "rule_profit + 0.03 * abs(rule_profit); waste_rate <= ceil(rule_waste_rate * 1000) / 1000",
            "no_discount_baseline_profit": float(self.no_discount_profit),
            "rule_policy_baseline_profit": float(self.rule_policy_profit),
            "baseline_profit": float(self.baseline_profit),
            "rule_waste_rate": float(self.rule_waste_rate),
            "waste_target": float(self.waste_target),
            "baseline_profit_sign": (
                "NEGATIVE" if float(self.baseline_profit) < 0
                else ("ZERO" if float(self.baseline_profit) == 0 else "POSITIVE")
            ),
            "warnings": warnings,
        }
