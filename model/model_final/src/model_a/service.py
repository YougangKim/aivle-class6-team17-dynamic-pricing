"""Public Model A functions; infrastructure uses the pipeline function instead."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from src.contracts.mappings import load_policy_mappings
from src.contracts.schemas import validate_runtime_request
from src.model_a.constraints import (
    policy_caps,
    previous_policy_lower_bounds,
    project_policy_numpy,
    round_execution_policy,
)
from src.model_a.initial_policy_lightgbm import InitialPolicyLightGBM, LightGBMNotTrainedError
from src.model_a.state_builder import RuntimeStateBuilder, RuntimePolicyState


def build_runtime_state(
    request: dict[str, Any],
    project_root: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> RuntimePolicyState:
    root = Path(project_root or Path(__file__).resolve().parents[2])
    mappings = load_policy_mappings(root / "artifacts" / "b_runtime")
    return RuntimeStateBuilder(root, mappings, data_dir=data_dir).build(request)


def propose_initial_policy(request: dict[str, Any], *, state: RuntimePolicyState | None = None, project_root: str | Path | None = None) -> dict[str, Any]:
    request = validate_runtime_request(request)
    root = Path(project_root or Path(__file__).resolve().parents[2]); state = state or build_runtime_state(request, root)
    caps = policy_caps(state.store_state["regular_price_vector"], state.store_state["unit_cost_vector"], state.store_state["product_max_discount_vector"])
    lower_bounds = previous_policy_lower_bounds(request, state.active_mask, caps)
    model = InitialPolicyLightGBM.load_or_not_trained(root / "artifacts" / "model_a", state.feature_names, int(request["options"]["seed"]))
    warnings = []
    fallback_used = False
    fallback_reason = None
    lightgbm_error_code = None
    try:
        if model.is_trained:
            mapping_path = root / "artifacts" / "model_a" / "initial_policy_mapping.json"
            if not mapping_path.exists():
                raise RuntimeError("InitialPolicyLightGBM mapping artifact is missing")
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            runtime_mapping = load_policy_mappings(root / "artifacts" / "b_runtime")
            if tuple(mapping.get("product_ids", ())) != runtime_mapping.product_ids or tuple(mapping.get("dte_labels", ())) != runtime_mapping.dte_labels:
                raise RuntimeError("InitialPolicyLightGBM mapping differs from the current B mapping")
            if str(mapping.get("discriminator_mode")) != str(request["options"]["discriminator_mode"]):
                raise RuntimeError(
                    "InitialPolicyLightGBM was trained for a different discriminator_mode"
                )
        policy = model.predict_policy(state.lgbm_rows, state.active_mask, caps); source = "LIGHTGBM"
    except LightGBMNotTrainedError as exc:
        policy = project_policy_numpy(state.current_policy, state.active_mask, caps); source = "CURRENT_POLICY"
        warnings.append(f"LIGHTGBM_NOT_TRAINED: {exc}")
        fallback_used = True; fallback_reason = str(exc); lightgbm_error_code = "LIGHTGBM_NOT_TRAINED"
    policy = round_execution_policy(policy, state.active_mask, caps, lower_bounds=lower_bounds)
    return {"source": source, "model_status": model.status, "policy_shape": [38,4], "policy_matrix": policy, "active_cell_count": int(state.active_mask.sum()), "warnings": warnings, "metrics": model.metrics, "caps": caps, "fallback_used":fallback_used, "fallback_reason":fallback_reason, "lightgbm_error_code":lightgbm_error_code}
