"""One normalization boundary for externally supplied discount rates."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def normalize_discount_rate(value: Any, *, field_name: str = "discount_rate") -> float:
    """Normalize a rate (``0.30``) or percentage (``30``) to a rate.

    Values in ``[0, 1]`` are interpreted as ratios and values in ``(1, 100]``
    as percentages.  The deliberately strict finite/non-negative validation
    prevents an accidental ``30.0`` from reaching policy optimization.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if number < 0.0 or number > 100.0:
        raise ValueError(f"{field_name} must be in 0..1 as a rate or 0..100 as a percent")
    return number / 100.0 if number > 1.0 else number


def normalize_discount_value(value: Any, *, field_name: str = "previous_discount_rate") -> Any:
    """Normalize either one rate or a nested JSON policy-rate matrix."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            normalize_discount_value(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    return normalize_discount_rate(value, field_name=field_name)
