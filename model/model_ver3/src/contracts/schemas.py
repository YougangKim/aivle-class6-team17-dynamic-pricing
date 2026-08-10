"""Runtime request validation and stable error codes."""

from __future__ import annotations

from enum import Enum
import math
from typing import Any, Mapping

from .discounts import normalize_discount_value

from src.contracts.b_modes import SCOPE_ALIGNED_EXPERIMENTAL, SUPPORTED_DISCRIMINATOR_MODES


class ErrorCode(str, Enum):
    INPUT_SCHEMA_ERROR = "INPUT_SCHEMA_ERROR"
    STATE_TENSOR_BUILD_ERROR = "STATE_TENSOR_BUILD_ERROR"
    LIGHTGBM_ARTIFACT_LOAD_ERROR = "LIGHTGBM_ARTIFACT_LOAD_ERROR"
    LIGHTGBM_NOT_TRAINED = "LIGHTGBM_NOT_TRAINED"
    PRODUCT_MAPPING_ERROR = "PRODUCT_MAPPING_ERROR"
    DTE_MAPPING_ERROR = "DTE_MAPPING_ERROR"
    POLICY_SHAPE_ERROR = "POLICY_SHAPE_ERROR"
    B_ARTIFACT_LOAD_ERROR = "B_ARTIFACT_LOAD_ERROR"
    B_MAPPING_ERROR = "B_MAPPING_ERROR"
    B_EVALUATION_ERROR = "B_EVALUATION_ERROR"
    SURROGATE_ARTIFACT_LOAD_ERROR = "SURROGATE_ARTIFACT_LOAD_ERROR"
    SURROGATE_TRAINING_ERROR = "SURROGATE_TRAINING_ERROR"
    POLICY_OPTIMIZATION_ERROR = "POLICY_OPTIMIZATION_ERROR"
    CONVERGENCE_ERROR = "CONVERGENCE_ERROR"
    OUTPUT_SERIALIZATION_ERROR = "OUTPUT_SERIALIZATION_ERROR"


class ContractError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, stage: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.details = details


def validate_runtime_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "request must be an object", "INPUT_VALIDATION")
    result = dict(request)
    required = ("request_id", "schema_version", "decision")
    missing = [key for key in required if key not in result]
    if missing:
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"Missing request fields: {missing}", "INPUT_VALIDATION")
    if str(result["schema_version"]) != "1.0":
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "Only schema_version 1.0 is supported", "INPUT_VALIDATION")
    decision = result["decision"]
    if not isinstance(decision, Mapping):
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "decision must be an object", "INPUT_VALIDATION")
    missing_decision = [key for key in ("store_id", "date", "hour", "decision_timestamp") if key not in decision]
    if missing_decision:
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"Missing decision fields: {missing_decision}", "INPUT_VALIDATION")
    try:
        hour = int(decision["hour"])
    except (TypeError, ValueError) as exc:
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "decision.hour must be an integer", "INPUT_VALIDATION") from exc
    if not 0 <= hour <= 23:
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "decision.hour must be in 0..23", "INPUT_VALIDATION")
    decision = dict(decision)
    decision["hour"] = hour
    result["decision"] = decision
    options = dict(result.get("options") or {})
    if "b_backend" in options:
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "options.b_backend is removed; runtime always uses REAL_B", "INPUT_VALIDATION")
    diagnostic_hint_options = (
        "rule_centered_warmup_cells",
        "direct_search_top_cells",
        "diagnostic_best_cells",
        "diagnostic_csv_path",
        "diagnostic_json_path",
    )
    supplied_diagnostic_hints = [key for key in diagnostic_hint_options if key in options]
    if supplied_diagnostic_hints:
        raise ContractError(
            ErrorCode.INPUT_SCHEMA_ERROR,
            "Operating optimization does not accept direct-search or diagnostic warm-up hints: "
            f"{supplied_diagnostic_hints}",
            "INPUT_VALIDATION",
        )
    defaults = {
        "max_outer_iterations": 30,
        "inner_gradient_steps": 10,
        "patience": 3,
        "convergence_patience": 3,
        "policy_tolerance": 0.01,
        "objective_tolerance": 0.001,
        "objective_relative_tolerance": 0.001,
        "objective_epsilon": 1.0,
        "max_b_evaluations": 24,
        "max_runtime_seconds": 120.0,
        "seed": 42,
        "minimum_replay_size": 6,
        "surrogate_epochs": 40,
        "surrogate_update_epochs": 8,
        "policy_learning_rate": 0.02,
        "trust_region": 0.05,
        "max_cell_change_per_outer": 0.05,
        "max_surrogate_validation_loss": 5.0,
        "surrogate_waste_penalty_weight": 1.0,
        "save_artifacts": True,
        "return_iteration_history": True,
        # While no qualifying real-B labels exist, CURRENT_POLICY is the safe
        # operating initial policy.  A caller can still opt out explicitly to
        # enforce a trained LightGBM artifact.
        "allow_initial_policy_fallback": True,
        "minimum_lightgbm_policy_groups": 6,
        "minimum_lightgbm_train_rows": 120,
        "minimum_lightgbm_validation_groups": 2,
        "discriminator_mode": SCOPE_ALIGNED_EXPERIMENTAL,
    }
    for key, value in defaults.items():
        options.setdefault(key, value)
    integer_positive = ("max_outer_iterations", "inner_gradient_steps", "patience", "convergence_patience", "max_b_evaluations", "minimum_replay_size", "surrogate_epochs", "surrogate_update_epochs", "minimum_lightgbm_policy_groups", "minimum_lightgbm_train_rows", "minimum_lightgbm_validation_groups")
    for key in integer_positive:
        if int(options[key]) <= 0:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"options.{key} must be positive", "INPUT_VALIDATION")
        options[key] = int(options[key])
    for key in ("policy_tolerance", "objective_tolerance", "objective_relative_tolerance", "objective_epsilon", "max_runtime_seconds", "surrogate_waste_penalty_weight"):
        value = float(options[key])
        if not math.isfinite(value) or value <= 0:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"options.{key} must be a positive finite number", "INPUT_VALIDATION")
        options[key] = value
    options["discriminator_mode"] = str(options["discriminator_mode"]).upper()
    if options["discriminator_mode"] not in SUPPORTED_DISCRIMINATOR_MODES:
        raise ContractError(
            ErrorCode.INPUT_SCHEMA_ERROR,
            f"options.discriminator_mode must be one of {list(SUPPORTED_DISCRIMINATOR_MODES)}",
            "INPUT_VALIDATION",
        )
    result["options"] = options
    state = result.setdefault("state", {"cells": []})
    if not isinstance(state, Mapping):
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "state must be an object", "INPUT_VALIDATION")
    state = dict(state)
    cells = state.setdefault("cells", [])
    if not isinstance(cells, list):
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "state.cells must be an array", "INPUT_VALIDATION")
    normalized_cells = []
    for index, cell in enumerate(cells):
        if not isinstance(cell, Mapping):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"state.cells[{index}] must be an object", "INPUT_VALIDATION")
        normalized_cell = dict(cell)
        if "previous_discount_rate" in normalized_cell:
            try:
                normalized_cell["previous_discount_rate"] = normalize_discount_value(
                    normalized_cell["previous_discount_rate"],
                    field_name=f"state.cells[{index}].previous_discount_rate",
                )
            except ValueError as exc:
                raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, str(exc), "INPUT_VALIDATION") from exc
        normalized_cells.append(normalized_cell)
    state["cells"] = normalized_cells
    result["state"] = state

    if "previous_discount_rate" in result and result["previous_discount_rate"] is not None:
        try:
            result["previous_discount_rate"] = normalize_discount_value(
                result["previous_discount_rate"], field_name="previous_discount_rate"
            )
        except ValueError as exc:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, str(exc), "INPUT_VALIDATION") from exc
    if "rolling_enabled" in result and not isinstance(result["rolling_enabled"], bool):
        raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "rolling_enabled must be boolean", "INPUT_VALIDATION")
    result.setdefault("rolling_enabled", False)
    return result


def failure_response(request_id: str | None, error: ContractError, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "schema_version": "1.0",
        "status": "FAILED",
        "error": {
            "error_code": error.code.value,
            "error_message": str(error),
            "failed_stage": error.stage,
            "details": error.details,
        },
        "warnings": warnings or [],
    }
