"""Single infrastructure entry point for Model A.

Model A does not import or execute Model B.  B feedback is accepted only as a
validated value from the previous infrastructure call.
"""

from __future__ import annotations

from typing import Any

from src.contracts.infrastructure_schemas import (
    validate_model_a_input,
    validate_model_a_output,
)
from src.contracts.serialization import to_jsonable

from .candidate_generator import generate_discount_candidate, get_candidate_session


def _policy_long(output: dict[str, Any]) -> list[dict[str, Any]]:
    if not output.get("candidate_ready"):
        return []
    session = get_candidate_session(str(output["request_id"]))
    matrix = output["policy_matrix"]
    rows: list[dict[str, Any]] = []
    for cell in session.state.cell_table.itertuples(index=False):
        product_index = int(cell.product_index)
        dte_index = int(cell.dte_index)
        rows.append(
            {
                "store_id": str(output["store_id"]),
                "product_id": str(cell.product_id),
                "product_index": product_index,
                "dte": dte_index,
                "dte_bucket": str(cell.dte_bucket),
                "dte_index": dte_index,
                "available_qty": float(cell.available_qty),
                "active_inventory_flag": bool(cell.active_inventory_flag),
                "discount_rate": float(matrix[product_index, dte_index]),
            }
        )
    return rows


def run_model_a(a_input: dict) -> dict:
    """Generate exactly one complete 38x4 policy candidate.

    First call: omit ``previous_b_evaluation``.  Later calls: pass the prior
    unmodified ``run_model_b`` output in that field.
    """
    request, previous_b = validate_model_a_input(a_input)
    output = generate_discount_candidate(request, previous_b)
    if "policy_iteration" not in output:
        session = get_candidate_session(str(output["request_id"]))
        output["policy_iteration"] = max(int(session.next_iteration) - 1, 0)
        output["policy_outer_iteration"] = output["policy_iteration"]
    output["policy_long"] = _policy_long(output)
    output = to_jsonable(output)
    validate_model_a_output(output)
    return output
