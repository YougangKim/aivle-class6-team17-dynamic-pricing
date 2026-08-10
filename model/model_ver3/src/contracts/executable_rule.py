"""Dependency-neutral access to the delivered Rule-policy contract."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def load_executable_rule_vector(project_root: str | Path) -> np.ndarray:
    """Return the delivered four-DTE Rule vector without importing B runtime.

    Both A and B consume the same delivered Code2 parameter artifact.  This
    contract keeps A coupled to the stable Rule definition only, rather than
    to B's artifact-loader implementation or evaluation internals.
    """
    root = Path(project_root)
    path = root / "external" / "b_original" / "nb1_results" / "params_customer_sim.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    vector = np.asarray(payload["shared"]["rule_vec"], dtype=np.float32)
    if vector.shape != (4,) or not np.isfinite(vector).all():
        raise ValueError("Delivered Rule vector must be four finite DTE rates")
    return vector
