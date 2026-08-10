"""Stable cross-boundary contracts shared by Model A, Model B, and pipeline."""

from .mappings import DTE_LABELS, POLICY_SHAPE, PRODUCT_COUNT, PolicyMappings, load_policy_mappings
from .schemas import ContractError, ErrorCode, validate_runtime_request
from .serialization import save_json, to_jsonable
from .infrastructure_schemas import (
    A_INPUT_FIELDS,
    A_OUTPUT_FIELDS,
    B_INPUT_FIELDS,
    B_METRIC_FIELDS,
    B_OUTPUT_FIELDS,
    build_runtime_request,
    validate_model_a_input,
    validate_model_a_output,
    validate_model_b_input,
    validate_model_b_output,
)

__all__ = ["A_INPUT_FIELDS", "A_OUTPUT_FIELDS", "B_INPUT_FIELDS", "B_METRIC_FIELDS", "B_OUTPUT_FIELDS", "ContractError", "DTE_LABELS", "ErrorCode", "POLICY_SHAPE", "PRODUCT_COUNT", "PolicyMappings", "build_runtime_request", "load_policy_mappings", "save_json", "to_jsonable", "validate_model_a_input", "validate_model_a_output", "validate_model_b_input", "validate_model_b_output", "validate_runtime_request"]
