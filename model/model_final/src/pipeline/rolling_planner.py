"""Receding-horizon, store-scoped rolling policy replanning.

Each invocation optimizes one current 38x4 policy against the remaining
store-to-close horizon.  It does not create an all-day discount time series.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.contracts.schemas import ContractError, ErrorCode, failure_response, validate_runtime_request
from src.contracts.serialization import save_json, to_jsonable
from src.model_a.constraints import PreviousPolicyCapConflictError
from src.model_b.service import evaluate_policy as evaluate_b_policy
from src.pipeline.rolling_constraints import (
    as_policy_matrix,
    build_rolling_constraint_context,
    canonical_decision_timestamp,
    verify_publishable_policy,
)


def policy_hash(policy: Any) -> str:
    return hashlib.sha256(np.asarray(policy, np.float32).tobytes()).hexdigest()


def run_discount_optimization(request: dict[str, Any], output_path: str | None = None) -> dict[str, Any]:
    """Lazy bridge so the ledger/B path does not eagerly load PyTorch A."""
    from src.pipeline.discount_optimization_pipeline import run_discount_optimization as run_base
    return run_base(request, output_path)


class RollingPolicyLedger:
    """Small persistent ledger keyed by store and full ISO-8601 timestamp."""

    VERSION = "rolling-policy-ledger-v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.document = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": self.VERSION, "stores": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Cannot read rolling ledger {self.path}: {exc}") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("stores"), Mapping):
            raise RuntimeError(f"Rolling ledger {self.path} has an invalid structure")
        return dict(payload)

    def _records(self, store_id: str) -> dict[str, Any]:
        stores = self.document.setdefault("stores", {})
        store = stores.setdefault(str(store_id), {"records": {}})
        return store.setdefault("records", {})

    def exact(self, store_id: str, decision_timestamp: str) -> dict[str, Any] | None:
        record = self._records(store_id).get(str(decision_timestamp))
        return deepcopy(record) if record is not None else None

    def previous_accepted(self, store_id: str, decision_timestamp: str) -> dict[str, Any] | None:
        target = pd.Timestamp(decision_timestamp)
        candidates: list[tuple[pd.Timestamp, dict[str, Any]]] = []
        for timestamp, record in self._records(store_id).items():
            if not bool(record.get("published")) or not isinstance(record.get("accepted_policy"), Mapping):
                continue
            parsed = pd.Timestamp(timestamp)
            if parsed < target:
                candidates.append((parsed, record))
        if not candidates:
            return None
        return deepcopy(max(candidates, key=lambda item: item[0])[1])

    def upsert(self, store_id: str, decision_timestamp: str, record: Mapping[str, Any]) -> None:
        self._records(store_id)[str(decision_timestamp)] = to_jsonable(dict(record))
        save_json(self.document, self.path)


def _default_ledger_path(project_root: Path) -> Path:
    return project_root / "outputs" / "runtime" / "rolling_policy_ledger.json"


def _result_path(project_root: Path, output_path: str | None) -> Path:
    return Path(output_path) if output_path else project_root / "outputs" / "runtime" / "rolling_result.json"


def _metrics_snapshot(b_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if b_result is None:
        return None
    metrics = dict(b_result.get("metrics") or {})
    return {
        key: metrics.get(key)
        for key in (
            "expected_demand", "expected_sales_qty", "expected_revenue",
            "expected_profit", "expected_waste_qty", "expected_waste_rate",
        )
    }


def _previous_from_request_or_ledger(
    request: dict[str, Any], previous_record: Mapping[str, Any] | None
) -> tuple[np.ndarray | None, str | None, str | None]:
    supplied = request.get("previous_discount_rate")
    ledger_policy = None
    if previous_record is not None:
        ledger_policy = np.asarray(previous_record["accepted_policy"]["policy_matrix"], np.float32)
    if supplied is None:
        if ledger_policy is None:
            return None, None, None
        return ledger_policy, "LEDGER_PREVIOUS_PUBLISHED", str(previous_record["accepted_policy"]["policy_hash"])

    supplied_matrix = as_policy_matrix(supplied)
    if ledger_policy is not None:
        if not np.allclose(supplied_matrix, ledger_policy, rtol=0.0, atol=1e-7):
            raise ContractError(
                ErrorCode.INPUT_SCHEMA_ERROR,
                "previous_discount_rate conflicts with the latest published policy in the rolling ledger",
                "ROLLING_INPUT_VALIDATION",
            )
        return ledger_policy, "LEDGER_AND_REQUEST_PREVIOUS_PUBLISHED", str(previous_record["accepted_policy"]["policy_hash"])
    return supplied_matrix, "REQUEST_PREVIOUS_DISCOUNT_RATE", policy_hash(supplied_matrix)


def _rejected_response(
    request: dict[str, Any],
    timestamp: str,
    reason: str,
    *,
    previous_policy_hash: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": str(request["request_id"]),
        "store_id": str(request["decision"]["store_id"]),
        "schema_version": "1.0",
        "status": "NO_THRESHOLD_PASS" if reason == "THRESHOLD_NOT_PASSED" else "ROLLING_REPLAN_REJECTED",
        "execution_eligible": False,
        "final_policy": None,
        "fallback_type": "KEEP_PREVIOUS_ESL_NO_NEW_PUBLICATION",
        "published": False,
        "publish": {
            "published": False,
            "source": "KEEP_PREVIOUS_ESL_NO_NEW_PUBLICATION",
            "reject_reason": reason,
        },
        "rolling": {
            "decision_timestamp": timestamp,
            "previous_policy_hash": previous_policy_hash,
            "threshold_pass": False,
            "temporal_monotonicity_violations": 0,
        },
        "warnings": list(warnings or []),
    }


def _record(
    response: Mapping[str, Any],
    timestamp: str,
    *,
    previous_policy_hash: str | None,
    accepted_policy: Mapping[str, Any] | None,
    b_result: Mapping[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    return {
        "store_id": str(response["store_id"]),
        "decision_timestamp": timestamp,
        "published": bool(accepted_policy is not None),
        "threshold_pass": bool(accepted_policy is not None),
        "previous_policy_hash": previous_policy_hash,
        "accepted_policy": None if accepted_policy is None else {
            "policy_matrix": accepted_policy["policy_matrix"],
            "policy_hash": accepted_policy["policy_hash"],
            "policy_source": accepted_policy.get("policy_source"),
        },
        "policy_hash": None if accepted_policy is None else accepted_policy["policy_hash"],
        "b_metrics": _metrics_snapshot(b_result),
        "source": source,
        "response": response,
    }


def run_rolling_replan(
    request: dict[str, Any],
    output_path: str | None = None,
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Optimize and publish one current policy using a persistent ESL ledger.

    The underlying FINAL_RELEASE pipeline remains responsible for actual B
    evaluations and executable-Rule discrimination.  This wrapper supplies
    the prior published ESL matrix as the optimizer's hard lower bound and
    records only a B-approved, hash-matched policy as published.
    """
    root = Path(__file__).resolve().parents[2]
    destination = _result_path(root, output_path)
    request_id = request.get("request_id") if isinstance(request, Mapping) else None
    try:
        validated = validate_runtime_request(request)
        timestamp = canonical_decision_timestamp(validated)
        store_id = str(validated["decision"]["store_id"])
        ledger = RollingPolicyLedger(ledger_path or _default_ledger_path(root))
        existing = ledger.exact(store_id, timestamp)
        if existing is not None:
            response = deepcopy(existing["response"])
            response["rolling"] = {
                **dict(response.get("rolling") or {}),
                "idempotent_replay": True,
            }
            save_json(response, destination)
            return response

        prior_record = ledger.previous_accepted(store_id, timestamp)
        previous_matrix, previous_source, previous_hash = _previous_from_request_or_ledger(
            validated, prior_record
        )
        inner_request = deepcopy(validated)
        inner_request["rolling_enabled"] = False
        if previous_matrix is not None:
            inner_request["previous_discount_rate"] = previous_matrix.tolist()

        try:
            context = build_rolling_constraint_context(inner_request, root)
        except PreviousPolicyCapConflictError as exc:
            response = _rejected_response(
                validated, timestamp, "PREVIOUS_POLICY_EXCEEDS_CURRENT_CAP",
                previous_policy_hash=previous_hash, warnings=[str(exc)],
            )
            ledger.upsert(store_id, timestamp, _record(
                response, timestamp, previous_policy_hash=previous_hash,
                accepted_policy=None, b_result=None, source="CAP_CONFLICT_SAFE_HOLD",
            ))
            save_json(response, destination)
            return response

        # Candidate generation and its final 1%p executable projection happen
        # inside the existing A/B pipeline.  The lower bound above is present
        # in every A projection rather than patched onto its final output.
        pipeline_result = run_discount_optimization(
            inner_request,
            str(destination.parent / "a_b_optimization" / "discount_result.json"),
        )
        final_policy = pipeline_result.get("final_policy")
        if not bool(pipeline_result.get("execution_eligible")) or not isinstance(final_policy, Mapping):
            response = _rejected_response(
                validated, timestamp, "THRESHOLD_NOT_PASSED",
                previous_policy_hash=previous_hash,
                warnings=list(pipeline_result.get("warnings") or []),
            )
            response["optimization_result"] = pipeline_result
            ledger.upsert(store_id, timestamp, _record(
                response, timestamp, previous_policy_hash=previous_hash,
                accepted_policy=None, b_result=None, source="THRESHOLD_FAILURE_SAFE_HOLD",
            ))
            save_json(response, destination)
            return response

        matrix = verify_publishable_policy(final_policy["policy_matrix"], context)
        executable_hash = policy_hash(matrix)
        if executable_hash != str(final_policy.get("policy_hash")):
            raise ContractError(
                ErrorCode.POLICY_OPTIMIZATION_ERROR,
                "A final policy_hash does not match its executable policy matrix",
                "ROLLING_B_REEVALUATION",
            )

        # This is an explicit B final gate.  The pipeline's existing B result
        # may be returned from its request-local evaluation cache, but it is
        # still the same actual B evaluation of the exact publish matrix.
        b_final = evaluate_b_policy(inner_request, {
            "request_id": str(inner_request["request_id"]),
            "store_id": store_id,
            "policy_iteration": int(final_policy["policy_iteration"]),
            "policy_matrix": matrix,
            "policy_hash": executable_hash,
        })
        if str(b_final.get("policy_hash")) != executable_hash:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR,
                "B final evaluation policy_hash differs from the publish policy_hash",
                "ROLLING_B_REEVALUATION",
            )
        if not bool(b_final["judgement"]["threshold_pass"]):
            response = _rejected_response(
                validated, timestamp, "B_FINAL_REEVALUATION_THRESHOLD_NOT_PASSED",
                previous_policy_hash=previous_hash,
                warnings=list(b_final.get("warnings") or []),
            )
            response["b_final_evaluation"] = b_final
            ledger.upsert(store_id, timestamp, _record(
                response, timestamp, previous_policy_hash=previous_hash,
                accepted_policy=None, b_result=b_final, source="B_FINAL_RECHECK_SAFE_HOLD",
            ))
            save_json(response, destination)
            return response

        response = deepcopy(pipeline_result)
        response["decision"]["decision_timestamp"] = timestamp
        response["published"] = True
        response["publish"] = {
            "published": True,
            "policy_source": str(final_policy.get("policy_source")),
            "policy_hash": executable_hash,
            "threshold_pass": True,
        }
        response["rolling"] = {
            "decision_timestamp": timestamp,
            "previous_policy_source": previous_source,
            "previous_policy_hash": previous_hash,
            "previous_policy_mean": None if previous_matrix is None else float(np.mean(previous_matrix)),
            "new_policy_mean": float(np.mean(matrix)),
            "policy_delta": None if previous_matrix is None else float(np.mean(matrix - previous_matrix)),
            "threshold_pass": True,
            "optimized_executable_policy_hash": executable_hash,
            "b_evaluated_policy_hash": str(b_final["policy_hash"]),
            "published_policy_hash": executable_hash,
            "temporal_monotonicity_violations": 0,
        }
        ledger.upsert(store_id, timestamp, _record(
            response, timestamp, previous_policy_hash=previous_hash,
            accepted_policy=final_policy, b_result=b_final, source="B_VALIDATED_ESL_PUBLICATION",
        ))
        response = to_jsonable(response)
        save_json(response, destination)
        return response
    except ContractError as exc:
        response = failure_response(None if request_id is None else str(request_id), exc)
    except Exception as exc:
        error = ContractError(ErrorCode.POLICY_OPTIMIZATION_ERROR, str(exc), "ROLLING_REPLAN")
        response = failure_response(None if request_id is None else str(request_id), error)
    save_json(response, destination)
    return response


def run_rolling_smoke(
    requests: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run timestamped rolling decisions and save an operational smoke log.

    ``requests`` are ordinary one-store rolling requests in chronological
    order.  This helper is deliberately a test/operational diagnostic; each
    item still goes through the same ``run_rolling_replan`` publication gate.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shared_ledger = Path(ledger_path) if ledger_path else destination / "rolling_policy_ledger.json"
    rows: list[dict[str, Any]] = []
    prior_matrix: np.ndarray | None = None
    violations = 0
    for index, request in enumerate(requests):
        result = run_rolling_replan(
            request,
            str(destination / f"decision_{index:03d}.json"),
            ledger_path=shared_ledger,
        )
        rolling = dict(result.get("rolling") or {})
        final_policy = result.get("final_policy") or {}
        matrix = (
            np.asarray(final_policy["policy_matrix"], np.float32)
            if result.get("published") and final_policy.get("policy_matrix") is not None
            else None
        )
        active_mask = np.zeros((38, 4), dtype=bool)
        for cell in final_policy.get("policy_long") or []:
            active_mask[int(cell["product_index"]), int(cell["dte_index"])] = bool(
                cell.get("active_inventory_flag")
            )
        if prior_matrix is not None and matrix is not None:
            violations += int(np.count_nonzero(active_mask & (matrix < prior_matrix - 1e-7)))
        if matrix is not None:
            prior_matrix = matrix
        metrics = dict(result.get("evaluation") or result.get("b_final_evaluation", {}).get("metrics") or {})
        rows.append({
            "decision_timestamp": rolling.get("decision_timestamp") or request["decision"]["decision_timestamp"],
            "previous_policy_mean": rolling.get("previous_policy_mean"),
            "new_policy_mean": rolling.get("new_policy_mean"),
            "policy_delta": rolling.get("policy_delta"),
            "threshold_pass": rolling.get("threshold_pass", False),
            "expected_profit": metrics.get("expected_profit"),
            "waste_rate": metrics.get("expected_waste_rate"),
            "policy_hash": rolling.get("published_policy_hash"),
            "published": bool(result.get("published")),
        })
    log_path = destination / "rolling_smoke_log.csv"
    pd.DataFrame(rows).to_csv(log_path, index=False, encoding="utf-8-sig")
    summary = {
        "decision_count": len(rows),
        "temporal_monotonicity_violations": int(violations),
        "ledger_path": str(shared_ledger.resolve()),
        "log_csv_path": str(log_path.resolve()),
        "rows": rows,
    }
    summary_path = destination / "rolling_smoke_summary.json"
    save_json(summary, summary_path)
    summary["summary_json_path"] = str(summary_path.resolve())
    return to_jsonable(summary)
