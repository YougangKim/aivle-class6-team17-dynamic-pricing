"""Matrix convergence state independent of optimization implementation."""

from dataclasses import dataclass
import numpy as np


def policy_change_metrics(previous, current, active_mask):
    delta = (np.asarray(current) - np.asarray(previous))[np.asarray(active_mask, bool)]
    if not delta.size:
        return {"max_active_cell_change": 0.0, "mean_active_cell_change": 0.0, "policy_l1_change": 0.0, "policy_l2_change": 0.0}
    return {"max_active_cell_change": float(np.abs(delta).max()), "mean_active_cell_change": float(np.abs(delta).mean()), "policy_l1_change": float(np.abs(delta).sum()), "policy_l2_change": float(np.sqrt(np.square(delta).sum()))}


@dataclass
class ConvergenceTracker:
    patience: int
    policy_tolerance: float
    objective_tolerance: float
    count: int = 0

    def update(self, threshold_pass, changes, objective_improvement):
        stable = bool(threshold_pass) and changes["max_active_cell_change"] <= self.policy_tolerance and abs(float(objective_improvement)) <= self.objective_tolerance
        self.count = self.count + 1 if stable else 0
        return self.count >= self.patience


@dataclass
class PassedPolicyConvergenceTracker:
    """Count only consecutive pairs of actual-B-passed, stable policies."""

    patience: int = 3
    policy_tolerance: float = 0.01
    objective_relative_tolerance: float = 0.001
    objective_epsilon: float = 1.0
    count: int = 0
    consecutive_pass_count: int = 0
    objective_relative_improvement: float | None = None

    def update(self, previous_pass, current_pass, changes, previous_profit, current_profit):
        self.consecutive_pass_count = self.consecutive_pass_count + 1 if current_pass else 0
        if previous_profit is None:
            self.objective_relative_improvement = None
            self.count = 0
            return False
        relative = abs(float(current_profit) - float(previous_profit)) / max(abs(float(previous_profit)), float(self.objective_epsilon))
        self.objective_relative_improvement = float(relative)
        stable = (
            bool(previous_pass) and bool(current_pass)
            and float(changes["max_active_cell_change"]) <= float(self.policy_tolerance) + 1e-12
            and relative <= float(self.objective_relative_tolerance) + 1e-12
        )
        self.count = self.count + 1 if stable else 0
        if not current_pass:
            self.consecutive_pass_count = 0
        return self.count >= int(self.patience)
