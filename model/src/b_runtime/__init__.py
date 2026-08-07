"""Reusable runtime extracted from the delivered B packages."""

from .artifact_loader import BArtifactBundle, BArtifactError, load_b_artifacts
from .customer_simulator import CustomerSimulator, MatrixCustomerSimulator
from .discriminator import RealBPolicyEvaluator
from .inventory_engine import InventorySnapshotEngine
from .schemas import DTE_LABELS, POLICY_SHAPE, PRODUCT_COUNT

__all__ = [
    "BArtifactBundle",
    "BArtifactError",
    "CustomerSimulator",
    "DTE_LABELS",
    "InventorySnapshotEngine",
    "MatrixCustomerSimulator",
    "POLICY_SHAPE",
    "PRODUCT_COUNT",
    "RealBPolicyEvaluator",
    "load_b_artifacts",
]
