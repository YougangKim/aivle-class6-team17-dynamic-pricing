"""Authoritative product/DTE mappings derived only from B code artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

PRODUCT_COUNT = 38
DTE_LABELS = ("당일만료", "D-1", "D-2", "D-3 이상")
POLICY_SHAPE = (38, 4)


@dataclass(frozen=True)
class PolicyMappings:
    product_ids: tuple[str, ...]
    dte_labels: tuple[str, ...]
    source: str

    @property
    def product_to_index(self) -> dict[str, int]:
        return {value: i for i, value in enumerate(self.product_ids)}

    @property
    def dte_to_index(self) -> dict[str, int]:
        return {value: i for i, value in enumerate(self.dte_labels)}


def load_policy_mappings(runtime_artifact_dir: str | Path) -> PolicyMappings:
    root = Path(runtime_artifact_dir)
    product_path = root / "product_index_mapping.json"
    dte_path = root / "dte_index_mapping.json"
    if not product_path.exists() or not dte_path.exists():
        raise FileNotFoundError(f"B mapping artifacts are missing under {root}")
    product = json.loads(product_path.read_text(encoding="utf-8"))
    dte = json.loads(dte_path.read_text(encoding="utf-8"))
    product_ids = tuple(product["index_to_product"][str(i)] for i in range(PRODUCT_COUNT))
    dte_labels = tuple(dte["index_to_dte"][str(i)] for i in range(4))
    if product_ids != tuple(f"P{i:03d}" for i in range(1, 39)):
        raise ValueError("Product mapping differs from delivered sim_arrays.npz/PID order")
    if dte_labels != DTE_LABELS:
        raise ValueError(f"DTE mapping differs from B code order: {dte_labels}")
    return PolicyMappings(product_ids, dte_labels, "sim_arrays.npz/PID + dte_index_mapping.json")
