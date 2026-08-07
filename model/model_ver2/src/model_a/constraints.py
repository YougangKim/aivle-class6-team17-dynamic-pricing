"""Vectorized continuous projection and final 1%p execution rounding."""

from __future__ import annotations

import numpy as np
import torch

from src.contracts.mappings import POLICY_SHAPE


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


def project_policy_numpy(policy, active_mask, caps, center=None, trust_region=None):
    value = np.nan_to_num(np.asarray(policy, np.float32), nan=0.0, posinf=0.40, neginf=0.0)
    if value.shape != POLICY_SHAPE:
        raise ValueError(f"policy must have shape {POLICY_SHAPE}")
    if center is not None and trust_region is not None:
        center_array = np.asarray(center, np.float32)
        value = np.clip(value, center_array - float(trust_region), center_array + float(trust_region))
    value = np.minimum(np.maximum(value, 0.0), np.asarray(caps, np.float32))
    return np.where(np.asarray(active_mask, bool), value, 0.0).astype(np.float32)


def project_policy_tensor_(policy_tensor, active_mask, caps, center=None, trust_region=None):
    mask = torch.as_tensor(active_mask, dtype=torch.bool, device=policy_tensor.device)
    cap = torch.as_tensor(caps, dtype=policy_tensor.dtype, device=policy_tensor.device)
    with torch.no_grad():
        policy_tensor.nan_to_num_(nan=0.0, posinf=0.40, neginf=0.0)
        if center is not None and trust_region is not None:
            c = torch.as_tensor(center, dtype=policy_tensor.dtype, device=policy_tensor.device)
            policy_tensor.copy_(torch.maximum(torch.minimum(policy_tensor, c + float(trust_region)), c - float(trust_region)))
        policy_tensor.clamp_(min=0.0)
        policy_tensor.copy_(torch.minimum(policy_tensor, cap))
        policy_tensor.mul_(mask)


def round_execution_policy(policy, active_mask, caps, step=0.01):
    cap = np.floor((np.asarray(caps) + 1e-12) / step) * step
    rounded = np.floor(np.asarray(policy) / step + 0.5) * step
    return project_policy_numpy(np.minimum(rounded, cap), active_mask, cap)
