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


def rule_policy_matrix() -> np.ndarray:
    return np.tile(np.asarray([0.40, 0.30, 0.20, 0.00], dtype=np.float64), (POLICY_SHAPE[0], 1))
