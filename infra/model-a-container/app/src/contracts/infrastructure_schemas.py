"""Public infrastructure schemas for the physically separated A/B services.

This module contains validation and translation only.  It deliberately imports
neither Model A nor Model B, so both services can depend on the same contract
without depending on each other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import math
from typing import Any

from .schemas import ContractError, ErrorCode, validate_runtime_request


POLICY_ROWS = 38
POLICY_COLUMNS = 4
POLICY_SHAPE = (POLICY_ROWS, POLICY_COLUMNS)

A_INPUT_FIELDS = (
    "request_id",
    "store_id",
    "current_time",
    "current_state",
)
A_OUTPUT_FIELDS = (
    "request_id",
    "store_id",
    "policy_iteration",
    "policy_shape",
    "policy_matrix",
    "policy_source",
    "candidate_ready",
)
B_INPUT_FIELDS = (*A_INPUT_FIELDS, "policy")
B_METRIC_FIELDS = (
    "expected_demand",
    "expected_sales_qty",
    "expected_revenue",
    "expected_profit",
    "expected_waste_qty",
    "expected_waste_rate",
)
B_OUTPUT_FIELDS = (
    "request_id",
    "store_id",
    "policy_iteration",
    "metrics",
    "judgement",
    "discriminator_version",
    "threshold_version",
    "artifact_source",
)


def _schema_error(message: str, stage: str) -> ContractError:
    return ContractError(ErrorCode.INPUT_SCHEMA_ERROR, message, stage)


def _require_mapping(value: Any, name: str, stage: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _schema_error(f"{name} must be an object", stage)
    return deepcopy(dict(value))


def _require_fields(value: Mapping[str, Any], fields: Sequence[str], name: str, stage: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise _schema_error(f"Missing {name} fields: {missing}", stage)


def _parse_current_time(value: Any) -> datetime:
    try:
        normalized = str(value).replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
    except (TypeError, ValueError) as exc:
        raise _schema_error(
            "current_time must be an ISO-8601 timestamp",
            "INFRASTRUCTURE_INPUT_VALIDATION",
        ) from exc
    return timestamp


def build_runtime_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the infrastructure envelope to the existing schema-1.0 request."""
    value = _require_mapping(payload, "input", "INFRASTRUCTURE_INPUT_VALIDATION")
    _require_fields(value, A_INPUT_FIELDS, "input", "INFRASTRUCTURE_INPUT_VALIDATION")
    timestamp = _parse_current_time(value["current_time"])
    state = value["current_state"]
    if isinstance(state, Mapping):
        normalized_state = deepcopy(dict(state))
        normalized_state.setdefault("source", "OPERATING_SYSTEM_CURRENT_STATE")
        normalized_state.setdefault("cells", [])
    elif isinstance(state, Sequence) and not isinstance(state, (str, bytes)):
        normalized_state = {
            "source": "OPERATING_SYSTEM_CURRENT_STATE",
            "cells": deepcopy(list(state)),
        }
    else:
        raise _schema_error(
            "current_state must be an object with cells or an array of cell objects",
            "INFRASTRUCTURE_INPUT_VALIDATION",
        )
    if not isinstance(normalized_state.get("cells"), list):
        raise _schema_error(
            "current_state.cells must be an array",
            "INFRASTRUCTURE_INPUT_VALIDATION",
        )
    runtime = {
        "request_id": str(value["request_id"]),
        "schema_version": str(value.get("schema_version", "1.0")),
        "decision": {
            "store_id": str(value["store_id"]),
            "date": timestamp.date().isoformat(),
            "hour": int(timestamp.hour),
            "decision_timestamp": timestamp.isoformat(),
        },
        "state": normalized_state,
        "options": deepcopy(dict(value.get("options") or {})),
    }
    return validate_runtime_request(runtime)


def _validate_policy(policy: Mapping[str, Any], stage: str, *, allow_none: bool = False) -> None:
    _require_fields(policy, A_OUTPUT_FIELDS, "policy", stage)
    if list(policy["policy_shape"]) != list(POLICY_SHAPE):
        raise _schema_error(f"policy_shape must be {list(POLICY_SHAPE)}", stage)
    matrix = policy["policy_matrix"]
    if matrix is None and allow_none:
        return
    if not isinstance(matrix, Sequence) or isinstance(matrix, (str, bytes)) or len(matrix) != POLICY_ROWS:
        raise _schema_error(f"policy_matrix must contain {POLICY_ROWS} product rows", stage)
    for row_index, row in enumerate(matrix):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != POLICY_COLUMNS:
            raise _schema_error(
                f"policy_matrix[{row_index}] must contain {POLICY_COLUMNS} DTE values",
                stage,
            )
        for value in row:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise _schema_error("policy_matrix values must be numeric", stage) from exc
            if not math.isfinite(number) or not 0.0 <= number <= 0.40:
                raise _schema_error("policy_matrix values must be finite rates in 0.00..0.40", stage)


def validate_model_a_input(a_input: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Validate A input and return (existing runtime request, optional B feedback)."""
    value = _require_mapping(a_input, "a_input", "MODEL_A_INPUT_VALIDATION")
    request = build_runtime_request(value)
    previous = value.get("previous_b_evaluation")
    if previous is not None:
        previous = _require_mapping(previous, "previous_b_evaluation", "MODEL_A_INPUT_VALIDATION")
        validate_model_b_output(previous)
        if str(previous["request_id"]) != str(request["request_id"]):
            raise _schema_error("previous_b_evaluation.request_id does not match A input", "MODEL_A_INPUT_VALIDATION")
        if str(previous["store_id"]) != str(request["decision"]["store_id"]):
            raise _schema_error("previous_b_evaluation.store_id does not match A input", "MODEL_A_INPUT_VALIDATION")
    return request, previous


def validate_model_a_output(a_output: Mapping[str, Any]) -> None:
    value = _require_mapping(a_output, "a_output", "MODEL_A_OUTPUT_VALIDATION")
    _require_fields(value, A_OUTPUT_FIELDS, "a_output", "MODEL_A_OUTPUT_VALIDATION")
    ready = bool(value["candidate_ready"])
    _validate_policy(value, "MODEL_A_OUTPUT_VALIDATION", allow_none=not ready)
    if ready and len(value.get("policy_long") or []) != POLICY_ROWS * POLICY_COLUMNS:
        raise _schema_error("A candidate policy_long must contain exactly 152 cells", "MODEL_A_OUTPUT_VALIDATION")


def validate_model_b_input(b_input: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _require_mapping(b_input, "b_input", "MODEL_B_INPUT_VALIDATION")
    _require_fields(value, B_INPUT_FIELDS, "b_input", "MODEL_B_INPUT_VALIDATION")
    request = build_runtime_request(value)
    policy = _require_mapping(value["policy"], "policy", "MODEL_B_INPUT_VALIDATION")
    _validate_policy(policy, "MODEL_B_INPUT_VALIDATION")
    if str(policy["request_id"]) != str(request["request_id"]):
        raise _schema_error("policy.request_id does not match B input", "MODEL_B_INPUT_VALIDATION")
    if str(policy["store_id"]) != str(request["decision"]["store_id"]):
        raise _schema_error("policy.store_id does not match B input", "MODEL_B_INPUT_VALIDATION")
    return request, policy


def validate_model_b_output(b_output: Mapping[str, Any]) -> None:
    value = _require_mapping(b_output, "b_output", "MODEL_B_OUTPUT_VALIDATION")
    _require_fields(value, B_OUTPUT_FIELDS, "b_output", "MODEL_B_OUTPUT_VALIDATION")
    metrics = _require_mapping(value["metrics"], "metrics", "MODEL_B_OUTPUT_VALIDATION")
    _require_fields(metrics, B_METRIC_FIELDS, "metrics", "MODEL_B_OUTPUT_VALIDATION")
    for field in B_METRIC_FIELDS:
        try:
            number = float(metrics[field])
        except (TypeError, ValueError) as exc:
            raise _schema_error(f"metrics.{field} must be numeric", "MODEL_B_OUTPUT_VALIDATION") from exc
        if not math.isfinite(number):
            raise _schema_error(f"metrics.{field} must be finite", "MODEL_B_OUTPUT_VALIDATION")
    judgement = _require_mapping(value["judgement"], "judgement", "MODEL_B_OUTPUT_VALIDATION")
    _require_fields(judgement, ("threshold_pass", "threshold_passed", "reject_reason"), "judgement", "MODEL_B_OUTPUT_VALIDATION")
