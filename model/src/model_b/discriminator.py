"""Adapter for the policy judge delivered by the B team in Code2.

The B delivery did not contain a serialized ``params_discriminator.json``.
The authoritative judge is therefore loaded from the delivered Code2 notebook
and its delivered ``policy_comparison.csv`` output. No rebuilt, uncalibrated,
mock, or request-local threshold is accepted as a silent replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from src.b_runtime.artifact_loader import BArtifactError


ARTIFACT_SOURCE = "B_TEAM_ORIGINAL_CODE2_PACKAGE"
CODE2_RELATIVE_ROOT = Path("external") / "b_original" / "code2_package"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_code2_source(notebook_path: Path) -> str:
    try:
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BArtifactError(f"Cannot read original B discriminator notebook: {notebook_path}: {exc}") from exc
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
    )


@dataclass(frozen=True)
class OriginalCode2Discriminator:
    """Exact Code2 ``judge`` comparison backed by delivered source/output."""

    profit_threshold: float
    alpha: float
    discriminator_version: str
    threshold_version: str
    artifact_source: str
    artifact_paths: dict[str, str]
    threshold_scope: str
    warnings: tuple[str, ...]

    @classmethod
    def load(cls, project_root: str | Path) -> "OriginalCode2Discriminator":
        root = Path(project_root).resolve()
        source_root = root / CODE2_RELATIVE_ROOT
        notebook_path = source_root / "01_code2_notebook.ipynb"
        comparison_path = source_root / "03_code2_outputs" / "policy_comparison.csv"
        summary_path = source_root / "03_code2_outputs" / "run_summary_nb2.md"
        required = (notebook_path, comparison_path, summary_path)
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise BArtifactError(
                "Original B discriminator files are missing; no rebuilt/mock threshold is allowed. "
                "Required: " + ", ".join(missing)
            )

        source = _read_code2_source(notebook_path)
        required_source_fragments = (
            "BASE_PROFIT = max(R_RULE['profit'], R_NONE['profit'])",
            "THRESHOLD_A = BASE_PROFIT * (1 + ALPHA) if BASE_PROFIT > 0 else BASE_PROFIT * (1 - ALPHA)",
            "def judge(policy, threshold=None, verbose=True):",
            "ok = r['profit'] > th",
        )
        missing_fragments = [item for item in required_source_fragments if item not in source]
        if missing_fragments:
            raise BArtifactError(
                "Original Code2 discriminator source signature changed or is incomplete: "
                + repr(missing_fragments)
            )
        match = re.search(r"(?m)^ALPHA\s*=\s*([0-9]*\.?[0-9]+)", source)
        if match is None:
            raise BArtifactError("Original Code2 ALPHA threshold margin was not found")
        alpha = float(match.group(1))

        comparison = pd.read_csv(comparison_path, encoding="utf-8-sig")
        if not {"정책", "이익"}.issubset(comparison.columns):
            raise BArtifactError("Original policy_comparison.csv must contain 정책 and 이익 columns")
        no_discount = comparison[comparison["정책"].astype(str).str.contains("무할인", regex=False)]
        rule_based = comparison[comparison["정책"].astype(str).str.contains("룰 기반", regex=False)]
        if len(no_discount) != 1 or len(rule_based) != 1:
            raise BArtifactError(
                "Original policy_comparison.csv must contain one no-discount and one rule-policy row"
            )
        no_discount_profit = float(no_discount.iloc[0]["이익"])
        rule_profit = float(rule_based.iloc[0]["이익"])
        base_profit = max(no_discount_profit, rule_profit)
        threshold = base_profit * (1.0 + alpha) if base_profit > 0 else base_profit * (1.0 - alpha)

        summary = summary_path.read_text(encoding="utf-8")
        if "임계점 = 기준선" not in summary:
            raise BArtifactError("Original Code2 summary does not contain the threshold audit line")

        notebook_hash = _sha256(notebook_path)
        comparison_hash = _sha256(comparison_path)
        calibrated_params_path = source_root / "params_discriminator.json"
        warnings: list[str] = [
            "ORIGINAL_CODE2_THRESHOLD_SCOPE_IS_2025_12_ALL_STORES; "
            "CURRENT_RUNTIME_SIMULATION_SCOPE_IS_CURRENT_STORE_TO_CLOSE",
        ]
        if not calibrated_params_path.exists():
            warnings.append(
                "B_TEAM_FINAL_PARAMS_DISCRIMINATOR_JSON_NOT_DELIVERED; "
                "no rebuilt or uncalibrated params file is used"
            )

        return cls(
            profit_threshold=float(threshold),
            alpha=alpha,
            discriminator_version=f"code2-judge-{notebook_hash[:12]}",
            threshold_version=f"code2-threshold-{comparison_hash[:12]}-alpha-{alpha:g}",
            artifact_source=ARTIFACT_SOURCE,
            artifact_paths={
                "discriminator_source": str(notebook_path),
                "threshold_source": str(comparison_path),
                "threshold_audit": str(summary_path),
            },
            threshold_scope="2025-12-01/2025-12-31; all delivered stores",
            warnings=tuple(warnings),
        )

    def evaluate(self, simulation_result: dict[str, Any]) -> dict[str, Any]:
        profit = float(simulation_result["expected_profit"])
        # This strict comparison is copied from the delivered Code2 judge:
        # ok = r['profit'] > th
        passed = profit > self.profit_threshold
        return {
            "threshold_pass": bool(passed),
            "threshold_passed": bool(passed),
            "reject_reason": None if passed else "EXPECTED_PROFIT_NOT_ABOVE_ORIGINAL_CODE2_THRESHOLD",
            "profit_gap": float(profit - self.profit_threshold),
            "revenue_gap": 0.0,
            "waste_gap": 0.0,
            "profit_threshold": float(self.profit_threshold),
            "threshold_margin_alpha": float(self.alpha),
            "discriminator_version": self.discriminator_version,
            "threshold_version": self.threshold_version,
            "artifact_source": self.artifact_source,
            "artifact_paths": dict(self.artifact_paths),
            "threshold_scope": self.threshold_scope,
            "warnings": list(self.warnings),
        }


def standardize_judgement(raw: dict[str, Any]) -> dict[str, Any]:
    """Preserve legacy A feedback keys while exposing the explicit alias."""
    passed = bool(raw["threshold_pass"])
    return {
        "threshold_pass": passed,
        "threshold_passed": passed,
        "reject_reason": raw.get("reject_reason"),
        "profit_gap": float(raw.get("profit_gap", 0.0)),
        "revenue_gap": float(raw.get("revenue_gap", 0.0)),
        "waste_gap": float(raw.get("waste_gap", 0.0)),
    }
