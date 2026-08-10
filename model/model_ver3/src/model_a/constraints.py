"""Vectorized continuous projection and final 1%p execution rounding."""

from __future__ import annotations

import numpy as np
import torch

from src.contracts.mappings import POLICY_SHAPE


class PreviousPolicyCapConflictError(ValueError):
    """Raised when an already-published ESL rate no longer fits a hard cap."""


def _policy_array(value, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape != POLICY_SHAPE:
        raise ValueError(f"{name} must have shape {POLICY_SHAPE}; got {array.shape}")
    return array


def execution_lower_bounds(previous_policy, active_mask, caps, step: float = 0.01) -> np.ndarray | None:
    """Return executable lower bounds for a previously published policy.

    A prior ESL policy must remain feasible after the existing 1%p execution
    rounding.  Rates are therefore rounded *up* to the next executable step;
    rounding a lower bound to the nearest step could otherwise lower a live
    price.  A conflict is explicit instead of silently clipping the published
    policy below a newly calculated product/cost/DTE cap.
    """
    if previous_policy is None:
        return None
    if not np.isfinite(float(step)) or float(step) <= 0:
        raise ValueError("step must be a positive finite number")
    previous = _policy_array(previous_policy, "previous_policy")
    mask = _policy_array(active_mask, "active_mask").astype(bool)
    raw_caps = _policy_array(caps, "caps")
    if not np.isfinite(previous).all():
        raise ValueError("previous_policy must contain only finite values")
    if not np.isfinite(raw_caps).all():
        raise ValueError("caps must contain only finite values")

    executable_cap = np.floor((raw_caps + 1e-12) / float(step)) * float(step)
    lower = np.ceil(np.maximum(previous, 0.0) / float(step) - 1e-9) * float(step)
    lower = np.where(mask, lower, 0.0).astype(np.float32)
    conflicts = np.argwhere(mask & (lower > executable_cap + 1e-7))
    if len(conflicts):
        preview = [tuple(map(int, pair)) for pair in conflicts[:8]]
        raise PreviousPolicyCapConflictError(
            "previous published discount exceeds the current executable policy cap "
            f"for {len(conflicts)} active cells; first cells={preview}"
        )
    return lower


def previous_policy_lower_bounds(request, active_mask, caps, step: float = 0.01) -> np.ndarray | None:
    """Read the optional, already normalized rolling lower bound from a request."""
    if "previous_discount_rate" not in request or request["previous_discount_rate"] is None:
        return None
    previous = np.asarray(request["previous_discount_rate"], dtype=np.float32)
    if previous.ndim == 0:
        previous = np.full(POLICY_SHAPE, float(previous), dtype=np.float32)
    return execution_lower_bounds(previous, active_mask, caps, step=step)


def policy_caps(regular_price, unit_cost, product_max, dte_max=(0.40, 0.40, 0.40, 0.40), max_discount=0.40):
    price = np.asarray(regular_price, dtype=np.float32).reshape(38)
    cost = np.asarray(unit_cost, dtype=np.float32).reshape(38)
    product = np.asarray(product_max, dtype=np.float32).reshape(38)
    dte = np.asarray(dte_max, dtype=np.float32).reshape(4)
    raw_cost_cap = np.clip(1.0 - cost.astype(np.float64) / np.maximum(price.astype(np.float64), 1e-9), 0.0, 1.0)
    # Leave a 1e-6 rate safety margin before converting to float32.  One ulp is
    # insufficient for high prices and can still put the execution price a few
    # thousandths of a won below cost.
    cost_cap = np.maximum(raw_cost_cap - np.where(raw_cost_cap > 0, 1e-6, 0.0), 0.0).astype(np.float32)
    return np.minimum.reduce([np.full(POLICY_SHAPE, max_discount, np.float32), product[:, None] * np.ones((1, 4), np.float32), cost_cap[:, None] * np.ones((1, 4), np.float32), np.ones((38, 1), np.float32) * dte[None, :]])


def project_policy_numpy(policy, active_mask, caps, center=None, trust_region=None, lower_bounds=None):
    value = np.nan_to_num(np.asarray(policy, np.float32), nan=0.0, posinf=0.40, neginf=0.0)
    if value.shape != POLICY_SHAPE:
        raise ValueError(f"policy must have shape {POLICY_SHAPE}")
    mask = _policy_array(active_mask, "active_mask").astype(bool)
    cap = _policy_array(caps, "caps")
    if center is not None and trust_region is not None:
        center_array = np.asarray(center, np.float32)
        value = np.clip(value, center_array - float(trust_region), center_array + float(trust_region))
    value = np.minimum(np.maximum(value, 0.0), cap)
    lower = execution_lower_bounds(lower_bounds, mask, cap) if lower_bounds is not None else None
    if lower is not None:
        # This is part of the optimizer projection, never a post-optimization
        # patch to a policy that A/B have already processed.
        value = np.maximum(value, lower)
    return np.where(mask, value, 0.0).astype(np.float32)


def project_policy_tensor_(policy_tensor, active_mask, caps, center=None, trust_region=None, lower_bounds=None):
    mask = torch.as_tensor(active_mask, dtype=torch.bool, device=policy_tensor.device)
    cap = torch.as_tensor(caps, dtype=policy_tensor.dtype, device=policy_tensor.device)
    lower = None
    if lower_bounds is not None:
        lower_array = execution_lower_bounds(lower_bounds, active_mask, caps)
        lower = torch.as_tensor(lower_array, dtype=policy_tensor.dtype, device=policy_tensor.device)
    with torch.no_grad():
        policy_tensor.nan_to_num_(nan=0.0, posinf=0.40, neginf=0.0)
        if center is not None and trust_region is not None:
            c = torch.as_tensor(center, dtype=policy_tensor.dtype, device=policy_tensor.device)
            policy_tensor.copy_(torch.maximum(torch.minimum(policy_tensor, c + float(trust_region)), c - float(trust_region)))
        policy_tensor.clamp_(min=0.0)
        policy_tensor.copy_(torch.minimum(policy_tensor, cap))
        if lower is not None:
            policy_tensor.copy_(torch.maximum(policy_tensor, lower))
        policy_tensor.mul_(mask)


def round_execution_policy(policy, active_mask, caps, step=0.01, lower_bounds=None):
    cap = np.floor((np.asarray(caps) + 1e-12) / step) * step
    rounded = np.floor(np.asarray(policy) / step + 0.5) * step
    return project_policy_numpy(
        np.minimum(rounded, cap), active_mask, cap, lower_bounds=lower_bounds
    )


def build_executable_rule_policy(rule_vector, active_mask, caps):
    """Convert the delivered DTE Rule vector into A's executable policy space."""
    rule = np.asarray(rule_vector, dtype=np.float32)
    if rule.shape != (4,):
        raise ValueError(f"rule_vector must have shape (4,); got {rule.shape}")
    return round_execution_policy(np.tile(rule, (38, 1)), active_mask, caps)
