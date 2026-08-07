"""Single infrastructure entry point for Model B.

Model B imports no Model-A, surrogate, LightGBM, or optimizer implementation.
"""

from __future__ import annotations

from src.contracts.infrastructure_schemas import (
    validate_model_b_input,
    validate_model_b_output,
)
from src.contracts.serialization import to_jsonable

from .service import evaluate_policy


def run_model_b(b_input: dict) -> dict:
    """Evaluate one A-produced full policy with B simulation and discriminator."""
    request, policy = validate_model_b_input(b_input)
    output = to_jsonable(evaluate_policy(request, policy))
    validate_model_b_output(output)
    return output

