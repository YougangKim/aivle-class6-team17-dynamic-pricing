"""REAL_B adapter with explicit simulation and discriminator stages."""

from __future__ import annotations

import logging
import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from src.b_runtime import BArtifactError, RealBPolicyEvaluator, load_b_artifacts
from src.b_runtime.policy_adapter import rule_policy_matrix
from src.contracts.b_modes import (
    ORIGINAL_CODE2,
    SCOPE_ALIGNED_EXPERIMENTAL,
    backend_for_mode,
    model_version_for_mode,
)
from src.contracts.mappings import POLICY_SHAPE
from src.contracts.schemas import ContractError, ErrorCode
from src.model_a.constraints import build_executable_rule_policy, policy_caps
from .discriminator import (
    OriginalCode2Discriminator,
    standardize_judgement,
)
from .experimental_discriminator import ScopeAlignedExperimentalDiscriminator
from .metrics_calculator import standardize_metrics


class RealBService:
    """One B service instance used consistently for all iterations of a request."""

    def __init__(
        self,
        project_root: str | Path,
        logger: logging.Logger | None = None,
        parameter_overrides: dict[str, float] | None = None,
        discriminator_mode: str = SCOPE_ALIGNED_EXPERIMENTAL,
    ) -> None:
        self.root = Path(project_root)
        self.discriminator_mode = str(discriminator_mode).upper()
        self.backend = backend_for_mode(self.discriminator_mode)
        self.b_model_version = model_version_for_mode(self.discriminator_mode)
        try:
            bundle = load_b_artifacts(
                self.root / "external" / "b_original" / "nb1_results",
                self.root / "data",
                discriminator_params_path=(
                    self.root / "external" / "b_original" / "code2_package"
                    / "03_code2_outputs" / "params_discriminator.json"
                ),
            )
            original_discriminator = (
                OriginalCode2Discriminator.load(self.root)
                if self.discriminator_mode == ORIGINAL_CODE2
                else None
            )
        except BArtifactError as exc:
            raise ContractError(
                ErrorCode.B_ARTIFACT_LOAD_ERROR, str(exc), "B_INITIALIZATION"
            ) from exc
        self.bundle = bundle
        self.raw = RealBPolicyEvaluator(
            bundle, parameter_overrides=parameter_overrides, logger=logger
        )
        self.original_discriminator = original_discriminator
        self.executable_rule_policy_hash: str | None = None
        self.discriminator = (
            ScopeAlignedExperimentalDiscriminator()
            if self.discriminator_mode == SCOPE_ALIGNED_EXPERIMENTAL
            else original_discriminator
        )

    @property
    def evaluation_count(self) -> int:
        return self.raw.evaluation_count

    @staticmethod
    def _validate_policy_and_mask(policy_matrix, active_mask):
        matrix = np.asarray(policy_matrix, np.float32)
        mask = np.asarray(active_mask, bool)
        if matrix.shape != POLICY_SHAPE or mask.shape != POLICY_SHAPE:
            raise ContractError(
                ErrorCode.POLICY_SHAPE_ERROR,
                f"policy/mask must have shape {POLICY_SHAPE}",
                "B_EVALUATION",
            )
        return matrix, mask

    def run_b_simulation(
        self,
        request: dict[str, Any],
        policy_matrix,
        active_mask,
        evaluation_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run only the B customer/inventory/accounting simulation."""
        matrix, mask = self._validate_policy_and_mask(policy_matrix, active_mask)
        options = dict(evaluation_options or {})
        store_state = options.pop("store_state", None)
        if store_state is None:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR,
                "store_state is required by the current snapshot evaluator",
                "B_SIMULATION",
            )
        try:
            raw = self.raw.run_simulation(
                store_state,
                matrix,
                mask,
                {"scope": "current_store_to_close", **options},
            )
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR, str(exc), "B_SIMULATION"
            ) from exc
        metrics = standardize_metrics(raw)
        return {
            "b_backend": self.backend,
            "b_model_version": self.b_model_version,
            "evaluation_scope": raw["evaluation_scope"],
            "evaluation_start": raw["evaluation_start"],
            "evaluation_end": raw["evaluation_end"],
            "store_id": raw["store_id"],
            "policy_shape": list(POLICY_SHAPE),
            "active_cell_count": int(mask.sum()),
            "baseline_policy_source": raw["baseline_policy_source"],
            "metrics": metrics,
            "simulation_version": "code1-code2-equations-current-snapshot-v2",
            "simulation_artifact_source": "B_TEAM_ORIGINAL_NB1_RESULTS",
            "runtime_beta_disc_ops": float(self.raw.simulator.runtime_beta_disc_ops),
            "rule_policy_source": str(self.bundle.artifact_dir / "params_customer_sim.json") + "#shared.rule_vec",
            "rule_policy_values": [float(value) for value in self.bundle.params["shared"]["rule_vec"]],
            "discriminator_params_source": str(self.bundle.discriminator_params_path),
            "warnings": (
                ["EXPERIMENTAL_SCOPE_ALIGNED_THRESHOLD_ENABLED"]
                if self.discriminator_mode == SCOPE_ALIGNED_EXPERIMENTAL
                else list(self.original_discriminator.warnings if self.original_discriminator else ())
            ),
        }

    def _ensure_scope_aligned_threshold(
        self,
        candidate_policy: np.ndarray,
        candidate_simulation: dict[str, Any],
        active_mask: np.ndarray,
        evaluation_options: dict[str, Any] | None,
    ) -> None:
        if self.discriminator_mode != SCOPE_ALIGNED_EXPERIMENTAL:
            return
        discriminator = self.discriminator
        if discriminator.is_calibrated:
            return
        options = dict(evaluation_options or {})
        store_state = options.pop("store_state", None)
        if store_state is None:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR,
                "store_state is required to calibrate the scope-aligned experimental threshold",
                "B_DISCRIMINATOR_CALIBRATION",
            )
        horizon = {"scope": "current_store_to_close", **options}

        def evaluate_baseline(matrix: np.ndarray) -> dict[str, Any]:
            raw = self.raw.run_simulation(store_state, matrix, active_mask, horizon)
            return {
                "metrics": standardize_metrics(raw),
                "evaluation_scope": raw["evaluation_scope"],
                "evaluation_start": raw["evaluation_start"],
                "evaluation_end": raw["evaluation_end"],
                "store_id": raw["store_id"],
            }

        if np.allclose(candidate_policy, 0.0, atol=1e-8):
            # The explicit pipeline baseline is already the complete zero
            # policy. Reuse that one B simulation instead of evaluating it a
            # second time merely to calibrate the discriminator.
            no_discount = {
                "metrics": candidate_simulation.get("metrics") or candidate_simulation,
                "evaluation_scope": candidate_simulation["evaluation_scope"],
                "evaluation_start": candidate_simulation["evaluation_start"],
                "evaluation_end": candidate_simulation["evaluation_end"],
                "store_id": candidate_simulation["store_id"],
            }
        else:
            no_discount = evaluate_baseline(np.zeros(POLICY_SHAPE, np.float32))
        caps = policy_caps(
            store_state["regular_price_vector"],
            store_state["unit_cost_vector"],
            store_state["product_max_discount_vector"],
        )
        executable_rule = build_executable_rule_policy(
            self.bundle.params["shared"]["rule_vec"], active_mask, caps
        )
        self.executable_rule_policy_hash = hashlib.sha256(
            np.asarray(executable_rule, np.float32).tobytes()
        ).hexdigest()
        original_rule = evaluate_baseline(executable_rule)
        discriminator.calibrate(no_discount, original_rule)

    def run_policy_discriminator(
        self,
        request: dict[str, Any],
        policy_matrix,
        simulation_result: dict[str, Any],
        active_mask,
        evaluation_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the selected original or explicit experimental B discriminator."""
        self._validate_policy_and_mask(policy_matrix, active_mask)
        metrics = simulation_result.get("metrics") or simulation_result
        try:
            self._ensure_scope_aligned_threshold(
                np.asarray(policy_matrix, np.float32),
                simulation_result,
                np.asarray(active_mask, bool),
                evaluation_options,
            )
            raw = self.discriminator.evaluate(metrics)
        except Exception as exc:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR, str(exc), "B_DISCRIMINATOR"
            ) from exc
        result = {
            "judgement": standardize_judgement(raw),
            "discriminator_version": raw["discriminator_version"],
            "threshold_version": raw["threshold_version"],
            "artifact_source": raw["artifact_source"],
            "artifact_paths": raw["artifact_paths"],
            "threshold_scope": raw["threshold_scope"],
            "profit_threshold": raw["profit_threshold"],
            "waste_target": raw.get("waste_target"),
            "executable_rule_policy_hash": self.executable_rule_policy_hash,
            "threshold_margin_alpha": raw["threshold_margin_alpha"],
            "warnings": raw["warnings"],
        }
        for key in (
            "experimental_discriminator", "threshold_formula",
            "no_discount_baseline_profit", "rule_policy_baseline_profit",
            "baseline_profit", "baseline_profit_sign", "rule_waste_rate",
            "waste_target", "runtime_beta_disc_ops", "rule_policy_source",
            "rule_policy_values", "discriminator_params_source",
        ):
            if key in raw:
                result[key] = raw[key]
        return result

    def evaluate_policy(
        self,
        request,
        policy_matrix,
        active_mask,
        evaluation_options=None,
    ) -> dict[str, Any]:
        """Compose simulation then discriminator without duplicating either."""
        simulation = self.run_b_simulation(
            request, policy_matrix, active_mask, evaluation_options
        )
        discriminator = self.run_policy_discriminator(
            request, policy_matrix, simulation, active_mask, evaluation_options
        )
        judgement = discriminator["judgement"]
        metrics = simulation["metrics"]
        warnings = list(dict.fromkeys(simulation["warnings"] + discriminator["warnings"]))
        return {
            **simulation,
            **{key: value for key, value in discriminator.items() if key not in {"warnings"}},
            "warnings": warnings,
            # Flat aliases are provided for infrastructure consumers while the
            # existing nested metrics/judgement envelope remains unchanged for A.
            "expected_demand": metrics["expected_demand"],
            "expected_sales_qty": metrics["expected_sales_qty"],
            "expected_revenue": metrics["expected_revenue"],
            "expected_profit": metrics["expected_profit"],
            "expected_waste_qty": metrics["expected_waste_qty"],
            "expected_waste_rate": metrics["expected_waste_rate"],
            "threshold_passed": judgement["threshold_passed"],
            "reject_reason": judgement["reject_reason"],
        }
