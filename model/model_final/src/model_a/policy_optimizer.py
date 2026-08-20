"""Bounded Adam inner loop over the 38x4 policy tensor."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from src.model_a.constraints import project_policy_tensor_


class OuterInnerPolicyOptimizer:
    def __init__(self, options: dict[str, Any], caps: np.ndarray, lower_bounds: np.ndarray | None = None) -> None:
        self.options = options; self.caps = np.asarray(caps, np.float32)
        self.lower_bounds = None if lower_bounds is None else np.asarray(lower_bounds, np.float32)
        self.seed = int(options["seed"]); self.rng = np.random.default_rng(self.seed); torch.manual_seed(self.seed)
        self.policy_lr = float(options.get("policy_learning_rate", 0.02))
        self.trust_region = float(options.get("trust_region", 0.05))
        self.max_cell_change = float(options.get("max_cell_change_per_outer", 0.05))
        self.max_surrogate_validation_loss = float(options.get("max_surrogate_validation_loss", 5.0))

    def _inner_optimize(self, surrogate, state, current, waste_target=None):
        state_tensor = torch.as_tensor(state.state_tensor[None], dtype=torch.float32)
        mask_tensor = torch.as_tensor(state.active_mask[None], dtype=torch.bool)
        policy_tensor = torch.tensor(current, dtype=torch.float32, requires_grad=True)
        policy_optimizer = torch.optim.Adam([policy_tensor], lr=self.policy_lr)
        predicted = None; gradient = np.zeros((38,4), np.float32)
        with surrogate.frozen():
            for _ in range(min(int(self.options["inner_gradient_steps"]), 50)):
                policy_optimizer.zero_grad(set_to_none=True)
                raw = surrogate.predict_raw_tensor(state_tensor, policy_tensor[None], mask_tensor)
                predicted = raw[0, 3]
                if waste_target is None:
                    loss = -predicted
                else:
                    predicted_waste_rate = raw[0, 4] / (raw[0, 1] + raw[0, 4]).clamp_min(1e-6)
                    profit_scale = float(surrogate.scaler.scale[3])
                    relative_excess = torch.relu(predicted_waste_rate - float(waste_target)) / max(float(waste_target), 1e-6)
                    loss = -predicted + float(self.options["surrogate_waste_penalty_weight"]) * profit_scale * relative_excess
                loss.backward()
                if policy_tensor.grad is None or policy_tensor.grad.shape != (38,4): raise RuntimeError("Policy gradient shape is not [38,4]")
                gradient = policy_tensor.grad.detach().cpu().numpy().copy()
                policy_optimizer.step()
                project_policy_tensor_(
                    policy_tensor,
                    state.active_mask,
                    self.caps,
                    current,
                    min(self.trust_region, self.max_cell_change),
                    lower_bounds=self.lower_bounds,
                )
        return policy_tensor.detach().cpu().numpy(), float(predicted.detach()), gradient, min(int(self.options["inner_gradient_steps"]), 50)
