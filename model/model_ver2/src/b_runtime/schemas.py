"""Authoritative schemas copied from the delivered Code2 implementation."""

from __future__ import annotations

from typing import Final

import numpy as np

PRODUCT_COUNT: Final[int] = 38
DTE_LABELS: Final[tuple[str, ...]] = ("당일만료", "D-1", "D-2", "D-3 이상")
POLICY_SHAPE: Final[tuple[int, int]] = (PRODUCT_COUNT, len(DTE_LABELS))
REQUIRED_SIMULATION_RESULT_KEYS: Final[tuple[str, ...]] = (
    "expected_demand",
    "expected_sales_qty",
    "expected_revenue",
    "expected_profit",
    "expected_waste_qty",
)

# Compatibility alias for callers that validate numerical simulation output.
# Threshold judgement intentionally lives in src.model_b, not in this runtime.
REQUIRED_RESULT_KEYS: Final[tuple[str, ...]] = REQUIRED_SIMULATION_RESULT_KEYS


def dte_bucket(days_to_expiry: float | int) -> int:
    """Map remaining days to the exact four Code2 buckets."""
    value = int(days_to_expiry)
    if value <= 0:
        return 0
    return 3 if value >= 3 else value


def validate_policy_matrix(policy_matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(policy_matrix, dtype=np.float64)
    if matrix.shape != POLICY_SHAPE:
        raise ValueError(f"policy_matrix must have shape {POLICY_SHAPE}; got {matrix.shape}")
    if not np.isfinite(matrix).all():
        raise ValueError("policy_matrix contains NaN or inf")
    return matrix
