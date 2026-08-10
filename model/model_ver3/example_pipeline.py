"""Minimal infrastructure example: Model A -> Model B -> Model A.

The file is an orchestration example only.  Model logic remains in the two
independent packages and is not duplicated here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.model_a import run_model_a
from src.model_b import run_model_b


def _shared_b_input(a_input: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: a_input[key]
        for key in ("request_id", "store_id", "current_time", "current_state", "options")
        if key in a_input
    } | {"policy": policy}


def run_one_a_b_a_exchange(a_input: dict) -> dict:
    """Execute one candidate evaluation and, if allowed, request A's next candidate."""
    first_a_output = run_model_a(a_input)
    if not first_a_output["candidate_ready"]:
        return {"first_a_output": first_a_output, "b_output": None, "next_a_output": None}

    b_output = run_model_b(_shared_b_input(a_input, first_a_output))
    next_a_input = dict(a_input)
    next_a_input["previous_b_evaluation"] = b_output
    next_a_output = run_model_a(next_a_input)
    return {
        "first_a_output": first_a_output,
        "b_output": b_output,
        "next_a_output": next_a_output,
    }


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    example_input = json.loads(
        (project_root / "data" / "sample_infrastructure_input.json").read_text(encoding="utf-8")
    )
    result = run_one_a_b_a_exchange(example_input)
    compact = {
        "request_id": result["first_a_output"]["request_id"],
        "first_policy_source": result["first_a_output"]["policy_source"],
        "first_policy_shape": result["first_a_output"]["policy_shape"],
        "b_backend": result["b_output"]["b_backend"] if result["b_output"] else None,
        "b_expected_profit": (
            result["b_output"]["metrics"]["expected_profit"] if result["b_output"] else None
        ),
        "next_policy_source": (
            result["next_a_output"]["policy_source"] if result["next_a_output"] else None
        ),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
