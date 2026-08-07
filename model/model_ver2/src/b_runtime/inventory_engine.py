"""Current-snapshot inventory engine using Code2 accounting equations."""

from __future__ import annotations

import numpy as np

from .schemas import POLICY_SHAPE, validate_policy_matrix


class InventorySnapshotEngine:
    """Evaluate from a current 38x4 inventory snapshot to day close."""

    def __init__(
        self,
        availability: np.ndarray,
        regular_price: np.ndarray,
        unit_cost: np.ndarray,
        product_weight_kg: np.ndarray,
        shrinkage_rate: float = 0.0255,
        disposal_fee_per_kg: float = 147.0,
    ) -> None:
        self.availability = np.asarray(availability, dtype=np.float64).copy()
        if self.availability.shape != POLICY_SHAPE:
            raise ValueError(f"availability must have shape {POLICY_SHAPE}")
        self.regular_price = np.asarray(regular_price, dtype=np.float64).reshape(-1)
        self.unit_cost = np.asarray(unit_cost, dtype=np.float64).reshape(-1)
        self.product_weight_kg = np.asarray(product_weight_kg, dtype=np.float64).reshape(-1)
        if any(v.shape != (POLICY_SHAPE[0],) for v in (self.regular_price, self.unit_cost, self.product_weight_kg)):
            raise ValueError("price, cost, and weight vectors must have length 38")
        self.shrinkage_rate = float(shrinkage_rate)
        self.disposal_fee_per_kg = float(disposal_fee_per_kg)
        self.log = {key: 0.0 for key in ("demand", "sold", "revenue", "cogs", "waste_qty", "waste_cost", "disposal_fee")}

    def sell(self, demand: np.ndarray, policy_matrix: np.ndarray) -> np.ndarray:
        disc = validate_policy_matrix(policy_matrix)
        requested = np.asarray(demand, dtype=np.float64)
        if requested.shape != POLICY_SHAPE:
            raise ValueError(f"demand must have shape {POLICY_SHAPE}")
        self.log["demand"] += float(np.maximum(requested, 0).sum())
        sold = np.minimum(np.maximum(requested, 0.0), self.availability)
        self.availability -= sold
        self.log["sold"] += float(sold.sum())
        self.log["revenue"] += float((sold * self.regular_price[:, None] * (1.0 - disc)).sum())
        self.log["cogs"] += float((sold * self.unit_cost[:, None]).sum())
        return sold

    def end_of_day(self) -> None:
        shrink = self.availability * self.shrinkage_rate
        self.availability -= shrink
        expired = np.zeros_like(self.availability)
        expired[:, 0] = self.availability[:, 0]
        self.availability[:, 0] = 0.0
        waste = shrink + expired
        self.log["waste_qty"] += float(waste.sum())
        self.log["waste_cost"] += float((waste * self.unit_cost[:, None]).sum())
        self.log["disposal_fee"] += float((waste * self.product_weight_kg[:, None] * self.disposal_fee_per_kg).sum())

    def results(self) -> dict[str, float]:
        profit = self.log["revenue"] - self.log["cogs"] - self.log["waste_cost"] - self.log["disposal_fee"]
        return {**self.log, "profit": float(profit)}
