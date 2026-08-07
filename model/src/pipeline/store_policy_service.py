"""Store-scoped operational wrappers around the existing A/B orchestrator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from src.contracts.b_modes import SCOPE_ALIGNED_EXPERIMENTAL
from src.contracts.serialization import save_json, to_jsonable
from src.pipeline.discount_optimization_pipeline import run_discount_optimization


SERVICE_STORE_IDS = ("S01", "S02", "S03")


def _normalize_current_state(current_state: Mapping[str, Any] | Sequence[dict] | None) -> dict[str, Any]:
    if current_state is None:
        return {"source": "PROJECT_DATA_SNAPSHOT", "cells": []}
    if isinstance(current_state, Mapping):
        if "cells" not in current_state:
            raise ValueError("current_state object must contain a cells array")
        state = deepcopy(dict(current_state))
        state.setdefault("source", "OPERATING_SYSTEM_CURRENT_STATE")
        state["cells"] = list(state.get("cells") or [])
        return state
    if isinstance(current_state, Sequence) and not isinstance(current_state, (str, bytes)):
        return {"source": "OPERATING_SYSTEM_CURRENT_STATE", "cells": list(current_state)}
    raise TypeError("current_state must be None, a state object, or a sequence of cell objects")


def _timestamp_parts(current_time: Any) -> tuple[pd.Timestamp, str]:
    timestamp = pd.Timestamp(current_time)
    if pd.isna(timestamp):
        raise ValueError("current_time must be a valid timestamp")
    return timestamp, timestamp.isoformat()


def optimize_discount_policy(
    store_id: str,
    current_time: Any,
    current_state: Mapping[str, Any] | Sequence[dict] | None,
    *,
    options: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Optimize one independent product-38 by DTE-4 policy for one store.

    This function does not combine stores into a 456-cell optimization. It
    constructs one existing schema-1.0 request and delegates to the unchanged
    A-candidate/B-evaluation outer loop.
    """
    normalized_store = str(store_id)
    if normalized_store not in SERVICE_STORE_IDS:
        raise ValueError(f"store_id must be one of {list(SERVICE_STORE_IDS)}")
    timestamp, timestamp_iso = _timestamp_parts(current_time)
    runtime_options = deepcopy(dict(options or {}))
    requested_mode = str(
        runtime_options.get("discriminator_mode", SCOPE_ALIGNED_EXPERIMENTAL)
    ).upper()
    if requested_mode != SCOPE_ALIGNED_EXPERIMENTAL:
        raise ValueError(
            "optimize_discount_policy requires SCOPE_ALIGNED_EXPERIMENTAL so B evaluates "
            "the current store/current-time-to-close threshold; use run_discount_optimization "
            "directly only for explicit offline ORIGINAL_CODE2 reproduction"
        )
    runtime_options["discriminator_mode"] = SCOPE_ALIGNED_EXPERIMENTAL
    generated_request_id = request_id or (
        f"STORE_POLICY_{normalized_store}_{timestamp.strftime('%Y%m%dT%H%M%S')}"
    )
    request = {
        "request_id": str(generated_request_id),
        "schema_version": "1.0",
        "decision": {
            "store_id": normalized_store,
            "date": timestamp.date().isoformat(),
            "hour": int(timestamp.hour),
            "decision_timestamp": timestamp_iso,
        },
        "state": _normalize_current_state(current_state),
        "options": runtime_options,
    }
    if output_path is None:
        root = Path(__file__).resolve().parents[2]
        output_path = str(
            root / "outputs" / "runtime" / "stores" / normalized_store / "discount_result.json"
        )
    return run_discount_optimization(request, output_path)


def optimize_all_store_policies(
    current_time: Any,
    current_states: Mapping[str, Mapping[str, Any] | Sequence[dict] | None],
    *,
    options: Mapping[str, Any] | None = None,
    store_ids: Sequence[str] = SERVICE_STORE_IDS,
    request_id_prefix: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Run three independent 152-cell optimizations and aggregate long output."""
    requested_stores = tuple(str(value) for value in store_ids)
    if requested_stores != SERVICE_STORE_IDS:
        raise ValueError(f"store_ids must be exactly {list(SERVICE_STORE_IDS)} in service order")
    missing = [store for store in requested_stores if store not in current_states]
    if missing:
        raise ValueError(f"current_states is missing stores: {missing}")
    timestamp, _ = _timestamp_parts(current_time)
    root = Path(__file__).resolve().parents[2]
    destination = Path(output_dir) if output_dir else (
        root / "outputs" / "runtime" / "all_stores" / timestamp.strftime("%Y%m%dT%H%M%S")
    )
    destination.mkdir(parents=True, exist_ok=True)
    prefix = request_id_prefix or f"ALL_STORES_{timestamp.strftime('%Y%m%dT%H%M%S')}"

    store_results: dict[str, dict[str, Any]] = {}
    combined_long: list[dict[str, Any]] = []
    base_options = deepcopy(dict(options or {}))
    base_seed = int(base_options.get("seed", 42))
    for index, store_id in enumerate(requested_stores):
        store_options = deepcopy(base_options)
        store_options["seed"] = base_seed + index
        result = optimize_discount_policy(
            store_id,
            timestamp,
            current_states[store_id],
            options=store_options,
            request_id=f"{prefix}_{store_id}",
            output_path=str(destination / store_id / "discount_result.json"),
        )
        store_results[store_id] = result
        if result.get("status") == "SUCCESS":
            combined_long.extend(result["final_policy"]["policy_long"])

    long_path = destination / "store_discount_policy_long.csv"
    pd.DataFrame(combined_long).to_csv(long_path, index=False, encoding="utf-8-sig")
    successful = [store for store, result in store_results.items() if result.get("status") == "SUCCESS"]
    response = {
        "schema_version": "1.0",
        "status": "SUCCESS" if len(successful) == len(requested_stores) else "PARTIAL_FAILURE",
        "optimization_unit": "ONE_STORE_X_ONE_DECISION_TIME_X_PRODUCT_38_X_DTE_4",
        "store_ids": list(requested_stores),
        "successful_store_ids": successful,
        "policy_shape_per_store": [38, 4],
        "total_policy_cell_count": 152 * len(successful),
        "store_results": store_results,
        "policy_long": combined_long,
        "artifacts": {
            "output_directory": str(destination.resolve()),
            "combined_policy_long_path": str(long_path.resolve()),
        },
    }
    response = to_jsonable(response)
    save_json(response, destination / "all_store_result.json")
    return response
