"""Rolling-replanning guards built on FINAL_RELEASE policy constraints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.contracts.schemas import ContractError, ErrorCode
from src.contracts.store_schedule import resolve_store_schedule
from src.model_a.constraints import (
    execution_lower_bounds,
    policy_caps,
    previous_policy_lower_bounds,
)
from src.model_a.service import build_runtime_state


@dataclass(frozen=True)
class RollingConstraintContext:
    decision_timestamp: str
    active_mask: np.ndarray
    policy_caps: np.ndarray
    previous_lower_bounds: np.ndarray | None


def canonical_decision_timestamp(request: dict[str, Any]) -> str:
    """Canonicalize and cross-check the full decision timestamp in a request."""
    decision = request["decision"]
    try:
        timestamp = pd.Timestamp(decision["decision_timestamp"])
    except (TypeError, ValueError) as exc:
        raise ContractError(
            ErrorCode.INPUT_SCHEMA_ERROR,
            "decision.decision_timestamp must be a valid timestamp",
            "ROLLING_INPUT_VALIDATION",
        ) from exc
    if pd.isna(timestamp):
        raise ContractError(
            ErrorCode.INPUT_SCHEMA_ERROR,
            "decision.decision_timestamp must be a valid timestamp",
            "ROLLING_INPUT_VALIDATION",
        )
    if str(decision["date"]) != timestamp.date().isoformat() or int(decision["hour"]) != int(timestamp.hour):
        raise ContractError(
            ErrorCode.INPUT_SCHEMA_ERROR,
            "decision.date/hour must match decision_timestamp",
            "ROLLING_INPUT_VALIDATION",
        )
    return timestamp.isoformat()


def build_rolling_constraint_context(
    request: dict[str, Any], project_root: str | Path
) -> RollingConstraintContext:
    """Calculate live caps/mask and reject non-monotone infeasible requests."""
    timestamp = canonical_decision_timestamp(request)
    decision = request["decision"]
    # This existing FINAL_RELEASE validator enforces the close-hour exclusive
    # boundary, including 21:xx allowed / 22:00 rejected for close_hour=22.
    resolve_store_schedule(project_root, str(decision["store_id"]), timestamp)
    state = build_runtime_state(request, project_root)
    caps = policy_caps(
        state.store_state["regular_price_vector"],
        state.store_state["unit_cost_vector"],
        state.store_state["product_max_discount_vector"],
    )
    lower = previous_policy_lower_bounds(request, state.active_mask, caps)
    return RollingConstraintContext(timestamp, state.active_mask, caps, lower)


def as_policy_matrix(value: Any) -> np.ndarray:
    """Convert a normalized scalar or 38x4 request value to a matrix."""
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 0:
        return np.full((38, 4), float(array), dtype=np.float32)
    if array.shape != (38, 4):
        raise ContractError(
            ErrorCode.POLICY_SHAPE_ERROR,
            "previous_discount_rate must be one rate or a [38, 4] matrix",
            "ROLLING_INPUT_VALIDATION",
        )
    return array.astype(np.float32, copy=False)


def verify_publishable_policy(policy: Any, context: RollingConstraintContext) -> np.ndarray:
    """Assert that the B-evaluated policy is exactly executable and monotone."""
    matrix = np.asarray(policy, dtype=np.float32)
    if matrix.shape != (38, 4):
        raise ContractError(
            ErrorCode.POLICY_SHAPE_ERROR,
            "published policy must have shape [38, 4]",
            "ROLLING_PUBLISH_VALIDATION",
        )
    if not np.isfinite(matrix).all():
        raise ContractError(
            ErrorCode.POLICY_OPTIMIZATION_ERROR,
            "published policy contains NaN or Inf",
            "ROLLING_PUBLISH_VALIDATION",
        )
    if np.any(matrix[~context.active_mask] != 0.0):
        raise ContractError(
            ErrorCode.POLICY_OPTIMIZATION_ERROR,
            "published policy assigns a nonzero discount to an inactive cell",
            "ROLLING_PUBLISH_VALIDATION",
        )
    if np.any(matrix[context.active_mask] > context.policy_caps[context.active_mask] + 1e-7):
        raise ContractError(
            ErrorCode.POLICY_OPTIMIZATION_ERROR,
            "published policy exceeds current policy_caps",
            "ROLLING_PUBLISH_VALIDATION",
        )
    if context.previous_lower_bounds is not None and np.any(
        matrix[context.active_mask]
        < context.previous_lower_bounds[context.active_mask] - 1e-7
    ):
        raise ContractError(
            ErrorCode.POLICY_OPTIMIZATION_ERROR,
            "published policy decreases a previous ESL discount",
            "ROLLING_PUBLISH_VALIDATION",
        )
    return matrix


def lower_bound_from_matrix(
    previous_policy: Any, context: RollingConstraintContext
) -> np.ndarray:
    """Expose the same executable lower-bound logic for ledger policies."""
    return execution_lower_bounds(
        as_policy_matrix(previous_policy), context.active_mask, context.policy_caps
    )
