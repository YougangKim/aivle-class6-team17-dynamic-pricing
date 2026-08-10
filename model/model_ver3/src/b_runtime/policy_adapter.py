"""Policy adapters that preserve the exact B product and DTE order."""

from __future__ import annotations

import numpy as np

from .schemas import POLICY_SHAPE, validate_policy_matrix


def constant_matrix_policy(policy_matrix: np.ndarray):
    """Return the original B callable signature without changing the matrix."""
    matrix = validate_policy_matrix(policy_matrix).copy()

    def policy(store_id, date, hour, availability_matrix):
        del store_id, date, hour, availability_matrix
        return matrix.copy()

    return policy


def rule_policy_matrix(rule_vector) -> np.ndarray:
    """Build the 38x4 Rule policy from the delivered Code1 shared artifact."""
    vector = np.asarray(rule_vector, dtype=np.float64)
    if vector.shape != (POLICY_SHAPE[1],):
        raise ValueError(f"rule_vector must have shape ({POLICY_SHAPE[1]},); got {vector.shape}")
    return np.tile(vector, (POLICY_SHAPE[0], 1))
