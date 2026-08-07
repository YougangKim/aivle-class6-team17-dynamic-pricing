"""Public Model B entry points. No mock or reconstructed threshold fallback."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.contracts.mappings import load_policy_mappings
from src.contracts.schemas import validate_runtime_request
from src.contracts.store_schedule import resolve_store_schedule
from .evaluator import RealBService


_B_SESSIONS: dict[str, dict[str, Any]] = {}


def _policy_context(request: dict[str, Any], policy: dict[str, Any]):
    validated = validate_runtime_request(request)
    root = Path(__file__).resolve().parents[2]
    mappings = load_policy_mappings(root / "artifacts" / "b_runtime")
    matrix = np.asarray(policy["policy_matrix"], np.float32)
    if matrix.shape != (38, 4):
        raise ValueError(f"policy_matrix must have shape (38, 4); got {matrix.shape}")
    expected_hash = hashlib.sha256(matrix.tobytes()).hexdigest()
    supplied_hash = policy.get("policy_hash")
    if supplied_hash is not None and str(supplied_hash) != expected_hash:
        raise ValueError("policy_hash does not match policy_matrix")
    request_id = str(validated["request_id"])
    if policy.get("request_id") is not None and str(policy["request_id"]) != request_id:
        raise ValueError("request_id mismatch between request and policy")
    if policy.get("store_id") is not None and str(policy["store_id"]) != str(validated["decision"]["store_id"]):
        raise ValueError("store_id mismatch between request and policy")
    iteration = int(policy.get("policy_iteration", policy.get("policy_outer_iteration", 1)))
    session = _B_SESSIONS.get(request_id)
    if session is None:
        store_state, active_mask = _build_b_store_state(root, validated, mappings)
        discriminator_mode = str(validated["options"]["discriminator_mode"])
        session = {
            "service": RealBService(root, discriminator_mode=discriminator_mode),
            "store_state": store_state,
            "active_mask": active_mask,
            "discriminator_mode": discriminator_mode,
            "simulation_cache": {},
            "evaluation_cache": {},
        }
        _B_SESSIONS[request_id] = session
    elif session["discriminator_mode"] != str(validated["options"]["discriminator_mode"]):
        raise ValueError("discriminator_mode cannot change within one request_id session")
    return validated, matrix, expected_hash, iteration, session


def run_b_simulation(request: dict, policy: dict) -> dict:
    """Run B virtual-customer, inventory, and accounting simulation only."""
    validated, matrix, policy_hash, iteration, session = _policy_context(request, policy)
    cache_key = (policy_hash, iteration)
    cached = session["simulation_cache"].get(cache_key)
    if cached is not None:
        return deepcopy(cached)
    simulation = session["service"].run_b_simulation(
        validated,
        matrix,
        session["active_mask"],
        {"store_state": session["store_state"]},
    )
    result = {
        "request_id": str(validated["request_id"]),
        "policy_iteration": iteration,
        "policy_hash": policy_hash,
        **simulation,
        "b_evaluation_count": int(session["service"].evaluation_count),
    }
    session["simulation_cache"][cache_key] = deepcopy(result)
    return result


def run_policy_discriminator(
    request: dict,
    policy: dict,
    simulation_result: dict,
) -> dict:
    """Run the request-selected original or explicit experimental judge only."""
    validated, matrix, policy_hash, iteration, session = _policy_context(request, policy)
    if str(simulation_result.get("request_id")) != str(validated["request_id"]):
        raise ValueError("simulation_result request_id does not match request")
    if str(simulation_result.get("policy_hash")) != policy_hash:
        raise ValueError("simulation_result policy_hash does not match policy")
    discriminator = session["service"].run_policy_discriminator(
        validated,
        matrix,
        simulation_result,
        session["active_mask"],
        {"store_state": session["store_state"]},
    )
    return {
        "request_id": str(validated["request_id"]),
        "policy_iteration": iteration,
        "policy_hash": policy_hash,
        **discriminator,
        "b_evaluation_count": int(session["service"].evaluation_count),
    }


def evaluate_policy(request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one full policy: simulation first, then the selected B judge."""
    validated, _matrix, policy_hash, iteration, session = _policy_context(request, policy)
    cache_key = (policy_hash, iteration)
    cached = session["evaluation_cache"].get(cache_key)
    if cached is not None:
        return deepcopy(cached)

    simulation = run_b_simulation(validated, policy)
    discriminator = run_policy_discriminator(validated, policy, simulation)
    metrics = simulation["metrics"]
    judgement = discriminator["judgement"]
    warnings = list(dict.fromkeys(simulation.get("warnings", []) + discriminator.get("warnings", [])))
    result = {
        **simulation,
        **{
            key: value
            for key, value in discriminator.items()
            if key not in {"request_id", "policy_iteration", "policy_hash", "warnings"}
        },
        "warnings": warnings,
        "expected_demand": metrics["expected_demand"],
        "expected_sales_qty": metrics["expected_sales_qty"],
        "expected_revenue": metrics["expected_revenue"],
        "expected_profit": metrics["expected_profit"],
        "expected_waste_qty": metrics["expected_waste_qty"],
        "expected_waste_rate": metrics["expected_waste_rate"],
        "threshold_passed": judgement["threshold_passed"],
        "reject_reason": judgement["reject_reason"],
        "b_evaluation_count": int(session["service"].evaluation_count),
    }
    session["evaluation_cache"][cache_key] = deepcopy(result)
    return result


def reset_b_session(request_id: str) -> None:
    _B_SESSIONS.pop(str(request_id), None)


def get_b_session(request_id: str) -> dict[str, Any]:
    return _B_SESSIONS[str(request_id)]


def _build_b_store_state(root, request, mappings):
    product = (
        pd.read_csv(root / "data" / "product.csv")
        .set_index("product_id")
        .loc[list(mappings.product_ids)]
    )
    store_id = str(request["decision"]["store_id"])
    timestamp = pd.Timestamp(request["decision"]["decision_timestamp"])
    local_timestamp = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
    availability = np.zeros((38, 4), np.float32)
    freshness_weight = np.zeros((38, 4), np.float32)
    cells = list((request.get("state") or {}).get("cells") or [])
    if cells:
        for cell in cells:
            if cell.get("store_id") is not None and str(cell["store_id"]) != store_id:
                raise ValueError(
                    f"State cell store_id={cell['store_id']} does not match decision.store_id={store_id}"
                )
            i = mappings.product_to_index[str(cell["product_id"])]
            j = int(cell["dte_index"])
            qty = max(float(cell.get("available_qty", 0)), 0)
            availability[i, j] = qty
            freshness_weight[i, j] = qty * float(
                cell.get("freshness_score", (cell.get("features") or {}).get("freshness_score", 0.6))
            )
    else:
        inventory = pd.read_csv(root / "data" / "inventory.csv", parse_dates=["current_date"])
        current = inventory[
            (inventory.store_id.astype(str) == store_id)
            & (inventory.current_date == local_timestamp.normalize())
        ]
        for row in current.itertuples():
            i = mappings.product_to_index[str(row.product_id)]
            days = int(row.days_to_expiry)
            j = 0 if days <= 0 else (3 if days >= 3 else days)
            qty = max(float(row.available_qty), 0)
            availability[i, j] += qty
            freshness_weight[i, j] += qty * float(row.freshness_score)
    freshness = np.divide(
        freshness_weight,
        availability,
        out=np.full((38, 4), 0.6, np.float32),
        where=availability > 0,
    )
    schedule = resolve_store_schedule(root, store_id, local_timestamp)
    state = {
        "store_id": store_id,
        "date": local_timestamp.normalize(),
        "hour": int(local_timestamp.hour),
        "decision_timestamp": local_timestamp,
        "open_hour": int(schedule["open_hour"]),
        "close_hour": int(schedule["evaluation_end_hour"]),
        "close_hour_exclusive": int(schedule["close_hour_exclusive"]),
        "store_schedule_source": str(schedule["schedule_source"]),
        "availability_matrix": availability,
        "freshness_matrix": freshness,
        "regular_price_vector": product.base_price.to_numpy(float),
        "unit_cost_vector": product.base_cost.to_numpy(float),
        "weight_vector": product.standard_weight_kg.to_numpy(float),
        "product_max_discount_vector": product.max_discount_rate.to_numpy(float),
        "baseline_policy_source": "REQUEST_CELLS" if cells else "PROJECT_DATA_SNAPSHOT",
    }
    return state, availability > 0
