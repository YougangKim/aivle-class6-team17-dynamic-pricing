"""Explicit non-official discriminator used by the current optimization experiment."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any


EXPERIMENTAL_ARTIFACT_SOURCE = (
    "B_TEAM_CODE2_BASELINES_SCOPE_ALIGNED_ABS_MARGIN_EXPERIMENTAL"
)


@dataclass
class ScopeAlignedExperimentalDiscriminator:
    """Scope-aligned baseline with a sign-safe relative improvement margin.

    The B simulation equations and original rule matrix are unchanged. The
    baseline scope is aligned to the candidate's store/current-time-to-close
    horizon, and the margin is applied as ``base + alpha * abs(base)`` so it
    always requires improvement. This is explicitly experimental and is never
    reported as the B team's official calibrated discriminator.
    """

    alpha: float = 0.03
    profit_threshold: float | None = None
    no_discount_profit: float | None = None
    rule_policy_profit: float | None = None
    baseline_profit: float | None = None
    threshold_scope: str | None = None
    threshold_version: str | None = None
    evaluation_start: str | None = None
    evaluation_end: str | None = None
    store_id: str | None = None

    discriminator_version: str = "code2-baseline-scope-aligned-abs-margin-experimental-v2"
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
        if not math.isfinite(none_profit) or not math.isfinite(rule_profit):
            raise ValueError("Experimental baseline profit is not finite")
        base = max(none_profit, rule_profit)
        threshold = base + float(self.alpha) * abs(base)
        self.no_discount_profit = none_profit
        self.rule_policy_profit = rule_profit
        self.baseline_profit = base
        self.profit_threshold = threshold
        self.store_id = str(no_discount_result["store_id"])
        self.evaluation_start = str(no_discount_result["evaluation_start"])
        self.evaluation_end = str(no_discount_result["evaluation_end"])
        self.threshold_scope = (
            f"store_id={self.store_id}; {self.evaluation_start}..{self.evaluation_end}; "
            "same inventory snapshot and current_store_to_close horizon"
        )
        signature = (
            f"{self.store_id}|{self.evaluation_start}|{self.evaluation_end}|"
            f"{none_profit:.12g}|{rule_profit:.12g}|{self.alpha:.12g}"
        )
        self.threshold_version = (
            "scope-aligned-abs-margin-v2-"
            + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
        )

    def evaluate(self, simulation_result: dict[str, Any]) -> dict[str, Any]:
        if not self.is_calibrated:
            raise RuntimeError("Scope-aligned experimental threshold has not been calibrated")
        profit = float(simulation_result["expected_profit"])
        threshold = float(self.profit_threshold)
        passed = profit >= threshold
        warnings = [
            "EXPERIMENTAL_SCOPE_ALIGNED_THRESHOLD_NOT_B_TEAM_OFFICIAL_APPROVAL",
            "FORMULA_USES_BASE_PROFIT_PLUS_ALPHA_TIMES_ABSOLUTE_BASE_PROFIT",
        ]
        if float(self.baseline_profit) < 0:
            warnings.append("NEGATIVE_BASELINE_REQUIRES_LOSS_REDUCTION_BY_THRESHOLD_MARGIN")
        return {
            "threshold_pass": bool(passed),
            "threshold_passed": bool(passed),
            "reject_reason": None if passed else "EXPECTED_PROFIT_BELOW_SCOPE_ALIGNED_EXPERIMENTAL_THRESHOLD",
            "profit_gap": float(profit - threshold),
            "revenue_gap": 0.0,
            "waste_gap": 0.0,
            "profit_threshold": threshold,
            "threshold_margin_alpha": float(self.alpha),
            "discriminator_version": self.discriminator_version,
            "threshold_version": str(self.threshold_version),
            "artifact_source": self.artifact_source,
            "artifact_paths": {
                "formula_lineage": "external/b_original/code2_package/01_code2_notebook.ipynb",
                "runtime_adapter": "src/model_b/experimental_discriminator.py",
            },
            "threshold_scope": str(self.threshold_scope),
            "experimental_discriminator": True,
            "threshold_formula": "base_profit + alpha * abs(base_profit)",
            "no_discount_baseline_profit": float(self.no_discount_profit),
            "rule_policy_baseline_profit": float(self.rule_policy_profit),
            "baseline_profit": float(self.baseline_profit),
            "baseline_profit_sign": (
                "NEGATIVE" if float(self.baseline_profit) < 0
                else ("ZERO" if float(self.baseline_profit) == 0 else "POSITIVE")
            ),
            "warnings": warnings,
        }
