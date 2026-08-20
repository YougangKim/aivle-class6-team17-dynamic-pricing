"""B-team customer/inventory simulation for one complete 38x4 policy.

This module deliberately does not decide whether a policy passes. The
scope-aligned judge is implemented separately in ``src.model_b`` so the
simulation and policy discriminator remain independently auditable.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from .artifact_loader import BArtifactBundle
from .customer_simulator import MatrixCustomerSimulator
from .inventory_engine import InventorySnapshotEngine
from .schemas import POLICY_SHAPE, REQUIRED_SIMULATION_RESULT_KEYS, validate_policy_matrix


class RealBPolicyEvaluator:
    """Run the B simulation once for a full product-by-DTE policy matrix."""

    backend_name = "REAL_B"

    def __init__(
        self,
        bundle: BArtifactBundle,
        parameter_overrides: dict[str, float] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bundle = bundle
        self.simulator = MatrixCustomerSimulator(bundle, parameter_overrides=parameter_overrides)
        self.logger = logger or logging.getLogger(__name__)
        self.evaluation_count = 0

    def run_simulation(
        self,
        store_state: dict[str, Any],
        policy_matrix: np.ndarray,
        active_mask: np.ndarray | None = None,
        evaluation_horizon: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        matrix = validate_policy_matrix(policy_matrix)
        mask = np.asarray(
            active_mask if active_mask is not None else store_state["availability_matrix"] > 0,
            dtype=bool,
        )
        if mask.shape != POLICY_SHAPE:
            raise ValueError(f"active_mask must have shape {POLICY_SHAPE}; got {mask.shape}")
        if (matrix < -1e-7).any() or (matrix > 0.40 + 1e-7).any():
            raise ValueError("Real B received a discount outside 0..0.40")
        matrix = np.clip(matrix, 0.0, 0.40)

        store_id = str(store_state["store_id"])
        date = pd.Timestamp(store_state["date"]).normalize()
        start_hour = int(store_state["hour"])
        close_hour = int(store_state["close_hour"])
        horizon = evaluation_horizon or {}
        scope = str(horizon.get("scope", "current_store_to_close"))
        if scope != "current_store_to_close":
            raise NotImplementedError(
                "This runtime entry point supports only current_store_to_close"
            )
        end_hour = min(int(horizon.get("end_hour", close_hour)), close_hour)

        active_count = int(mask.sum())
        self.logger.info("B BACKEND: REAL_B")
        self.logger.info("POLICY SHAPE: %s", POLICY_SHAPE)
        self.logger.info("ACTIVE POLICY CELLS: %d", active_count)
        self.logger.info("EVALUATION SCOPE: %s", scope)

        engine = InventorySnapshotEngine(
            availability=store_state["availability_matrix"],
            regular_price=store_state["regular_price_vector"],
            unit_cost=store_state["unit_cost_vector"],
            product_weight_kg=store_state["weight_vector"],
        )
        fresh = np.asarray(store_state["freshness_matrix"], dtype=np.float64)
        for hour in range(start_hour, end_hour + 1):
            if engine.availability.sum() <= 1e-12:
                break
            demand = self.simulator.demand_by_dte(
                store_id, date, hour, matrix, engine.availability, fresh
            )
            engine.sell(demand, matrix)
        engine.end_of_day()

        raw = engine.results()
        sold = float(raw["sold"])
        waste = float(raw["waste_qty"])
        result: dict[str, Any] = {
            "expected_demand": float(raw["demand"]),
            "expected_sales_qty": sold,
            "expected_revenue": float(raw["revenue"]),
            "expected_profit": float(raw["profit"]),
            "expected_waste_qty": waste,
            "expected_waste_rate": waste / max(sold + waste, 1e-9),
            "evaluation_scope": scope,
            "evaluation_start": f"{date.date().isoformat()}T{start_hour:02d}:00:00",
            "evaluation_end": f"{date.date().isoformat()}T{end_hour:02d}:59:59",
            "store_id": store_id,
            "policy_shape": list(POLICY_SHAPE),
            "active_cell_count": active_count,
            "baseline_policy_source": str(
                store_state.get("baseline_policy_source", "CURRENT_INVENTORY_DISCOUNT")
            ),
            "b_backend": self.backend_name,
            "accounting": {
                "cogs": float(raw["cogs"]),
                "waste_cost": float(raw["waste_cost"]),
                "disposal_fee": float(raw["disposal_fee"]),
            },
        }
        missing = [key for key in REQUIRED_SIMULATION_RESULT_KEYS if key not in result]
        if missing:
            raise RuntimeError(f"Real B simulation output missing required keys: {missing}")
        numeric = [result[key] for key in REQUIRED_SIMULATION_RESULT_KEYS]
        if not np.isfinite(np.asarray(numeric, dtype=float)).all():
            raise RuntimeError("Real B simulation output contains NaN or inf")
        if sold > float(np.asarray(store_state["availability_matrix"]).sum()) + 1e-7:
            raise RuntimeError("Real B expected_sales_qty exceeds available inventory")
        self.evaluation_count += 1
        return result

    # Compatibility for internal callers written before the two B stages were
    # separated. This is simulation only and never creates a pass/fail result.
    def evaluate_policy(
        self,
        store_state: dict[str, Any],
        policy_matrix: np.ndarray,
        active_mask: np.ndarray | None = None,
        evaluation_horizon: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.run_simulation(
            store_state, policy_matrix, active_mask, evaluation_horizon
        )
