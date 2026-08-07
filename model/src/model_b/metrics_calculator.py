"""Standardize B accounting metrics without changing their equations."""

from __future__ import annotations


def standardize_metrics(raw: dict) -> dict:
    accounting = raw.get("accounting") or {}
    sold = float(raw["expected_sales_qty"])
    waste = float(raw["expected_waste_qty"])
    waste_rate = float(raw.get("expected_waste_rate", waste / max(sold + waste, 1e-9)))
    return {
        "expected_demand": float(raw["expected_demand"]),
        "expected_sales_qty": sold,
        "expected_revenue": float(raw["expected_revenue"]),
        "expected_cogs": float(accounting["cogs"]) if accounting.get("cogs") is not None else None,
        "expected_profit": float(raw["expected_profit"]),
        "expected_waste_qty": waste,
        "expected_waste_cost": float(accounting["waste_cost"]) if accounting.get("waste_cost") is not None else None,
        "expected_disposal_fee": float(accounting["disposal_fee"]) if accounting.get("disposal_fee") is not None else None,
        "expected_waste_rate": waste_rate,
        "waste_rate": waste_rate,
    }
