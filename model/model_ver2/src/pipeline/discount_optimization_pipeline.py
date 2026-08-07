"""Infrastructure orchestrator that alternates the independent A and B APIs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import traceback
from typing import Any

import numpy as np

from src.contracts.schemas import ContractError, ErrorCode, failure_response, validate_runtime_request
from src.contracts.serialization import save_json, to_jsonable
from src.model_a.candidate_generator import generate_discount_candidate, get_candidate_session, reset_candidate_session
from src.model_a.convergence import policy_change_metrics
from src.model_b.service import evaluate_policy, get_b_session, reset_b_session


def _make_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"runtime.{path.parent.name}")
    logger.handlers.clear(); logger.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8", mode="w")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def run_discount_optimization(request: dict[str, Any], output_path: str | None = None) -> dict[str, Any]:
    """Orchestrate A candidate -> B evaluation until A reports a stop condition."""
    root = Path(__file__).resolve().parents[2]
    runtime_root = root / "outputs" / "runtime"
    result_path = Path(output_path) if output_path else runtime_root / "discount_result.json"
    run_artifact_root = result_path.parent
    log_path = run_artifact_root / "run.log"
    logger = _make_logger(log_path)
    request_id = str(request.get("request_id")) if isinstance(request, dict) and request.get("request_id") is not None else None
    stage = "INPUT_VALIDATION"
    try:
        validated = validate_runtime_request(request)
        request_id = str(validated["request_id"])
        reset_candidate_session(request_id); reset_b_session(request_id)
        logger.info("request_id=%s discriminator_mode=%s", request_id, validated["options"]["discriminator_mode"])

        stage = "B_BASELINE_EVALUATION"
        store_id = str(validated["decision"]["store_id"])
        no_discount_policy = {
            "request_id": request_id,
            "store_id": store_id,
            "policy_iteration": 0,
            "policy_outer_iteration": 0,
            "policy_shape": [38, 4],
            "policy_matrix": np.zeros((38, 4), np.float32),
            "policy_source": "NO_DISCOUNT_BASELINE",
        }
        baseline_b = evaluate_policy(validated, no_discount_policy)
        if str(baseline_b.get("store_id")) != store_id:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR,
                "B no-discount baseline store_id does not match the request",
                "B_BASELINE_EVALUATION",
            )
        logger.info(
            "B baseline store_id=%s scope=%s start=%s end=%s expected_profit=%s",
            store_id,
            baseline_b["evaluation_scope"],
            baseline_b["evaluation_start"],
            baseline_b["evaluation_end"],
            baseline_b["metrics"]["expected_profit"],
        )

        stage = "A_CANDIDATE_GENERATION"
        previous_b = None
        first_a = first_b = None
        while True:
            a_output = generate_discount_candidate(validated, previous_b)
            if not a_output["candidate_ready"]:
                break
            logger.info(
                "A policy_outer_iteration=%s source=%s shape=%s",
                a_output["policy_outer_iteration"], a_output["policy_source"], a_output["policy_shape"],
            )
            if first_a is None:
                first_a = a_output
                get_candidate_session(request_id).record_no_discount_baseline(baseline_b)
            stage = "B_EVALUATION"
            b_output = evaluate_policy(validated, a_output)
            if str(b_output.get("store_id")) != store_id:
                raise ContractError(
                    ErrorCode.B_EVALUATION_ERROR,
                    "B candidate evaluation store_id does not match the request",
                    "B_EVALUATION",
                )
            logger.info(
                "B policy_outer_iteration=%s expected_profit=%s threshold_pass=%s policy_hash=%s",
                b_output["policy_iteration"], b_output["metrics"]["expected_profit"],
                b_output["judgement"]["threshold_pass"], b_output["policy_hash"],
            )
            if first_b is None:
                first_b = b_output
            previous_b = b_output
            stage = "A_CANDIDATE_GENERATION"

        session = get_candidate_session(request_id)
        final_entry = session.best_available()
        if first_a is None or first_b is None or final_entry is None:
            raise ContractError(ErrorCode.POLICY_OPTIMIZATION_ERROR, "No actual-B policy evaluation completed", "POLICY_OPTIMIZATION")
        final_matrix = np.asarray(final_entry["policy"], np.float32)
        final_evaluation = final_entry["result"]
        final_metrics = final_evaluation["metrics"]
        judgement = final_evaluation["judgement"]
        history, cell_history, surrogate_history = session.frames()

        stage = "ARTIFACT_SAVE"
        run_artifact_root.mkdir(parents=True, exist_ok=True)
        history_path = run_artifact_root / "optimization_history.csv"
        cell_history_path = run_artifact_root / "policy_cell_history.parquet"
        surrogate_history_path = run_artifact_root / "surrogate_training_history.csv"
        history.to_csv(history_path, index=False, encoding="utf-8-sig")
        cell_history.to_parquet(cell_history_path, index=False)
        surrogate_history.to_csv(surrogate_history_path, index=False, encoding="utf-8-sig")
        replay_dir = root / "artifacts" / "replay_buffer" / request_id
        session.replay.save(replay_dir)
        model_dir = root / "artifacts" / "model_a"
        if session.surrogate.is_trained:
            session.surrogate.save(model_dir, session.state.feature_names)

        initial_matrix = np.asarray(first_a["policy_matrix"], np.float32)
        changes = policy_change_metrics(initial_matrix, final_matrix, session.state.active_mask)
        status = session.status()
        best_passed = session.best_passed()
        fallback_used = not session.converged
        fallback_reason = None if session.converged else (
            "Best actual-B-passed policy selected" if best_passed is not None else "No threshold-passing policy; best feasible policy selected"
        )
        long = []
        for row in session.state.cell_table.itertuples(index=False):
            i, j = int(row.product_index), int(row.dte_index)
            long.append({
                "store_id": store_id,
                "date": str(validated["decision"]["date"]),
                "hour": int(validated["decision"]["hour"]),
                "product_id": row.product_id, "product_index": i,
                "dte": j, "dte_bucket": row.dte_bucket, "dte_index": j,
                "available_qty": float(row.available_qty), "active_inventory_flag": bool(row.active_inventory_flag),
                "initial_discount_rate": float(initial_matrix[i, j]), "final_discount_rate": float(final_matrix[i, j]),
                "discount_rate": float(final_matrix[i, j]),
                "discounted_price": float(row.regular_price * (1.0 - final_matrix[i, j])),
            })
        b_session = get_b_session(request_id)
        b_evaluation_count = int(b_session["service"].evaluation_count)
        training_metrics = dict(session.initial["metrics"])
        model_metadata = {
            "a_initial_policy_model": "LightGBM", "initial_policy_status": session.initial["model_status"],
            "initial_policy_source": first_a["policy_source"], "a_surrogate_model": "FullPolicyAttentionNeuralNetwork",
            "surrogate_status": "TRAINED" if session.surrogate.is_trained else "NOT_TRAINED",
            "a_optimizer": "Adam", "a_model_version": "full-policy-a-v2",
            "b_model_version": final_evaluation["b_model_version"], "b_backend": final_evaluation["b_backend"],
            "discriminator_mode": validated["options"]["discriminator_mode"],
        }
        discriminator_metadata_keys = (
            "discriminator_version", "threshold_version", "artifact_source",
            "artifact_paths", "threshold_scope", "profit_threshold",
            "threshold_margin_alpha", "experimental_discriminator",
            "threshold_formula", "no_discount_baseline_profit",
            "rule_policy_baseline_profit", "baseline_profit", "baseline_profit_sign",
        )
        evaluation_metadata = {
            key: final_evaluation[key]
            for key in discriminator_metadata_keys
            if key in final_evaluation
        }
        baseline_evaluation_metadata = {
            key: baseline_b[key]
            for key in discriminator_metadata_keys
            if key in baseline_b
        }
        baseline_metrics = baseline_b["metrics"]
        baseline_judgement = baseline_b["judgement"]
        save_json(model_metadata, model_dir / "model_metadata.json")
        response = {
            "request_id": request_id, "store_id": store_id,
            "schema_version": "1.0", "status": "SUCCESS", "b_backend": final_evaluation["b_backend"],
            "decision": {key: validated["decision"][key] for key in ("store_id", "date", "hour")},
            "baseline": {
                "policy_source": "NO_DISCOUNT_BASELINE",
                "policy_iteration": 0,
                "policy_shape": [38, 4],
                "policy_hash": baseline_b["policy_hash"],
                "store_id": store_id,
                "evaluation_scope": baseline_b["evaluation_scope"],
                "evaluation_start": baseline_b["evaluation_start"],
                "evaluation_end": baseline_b["evaluation_end"],
                "metrics": baseline_metrics,
                "judgement": baseline_judgement,
                **baseline_evaluation_metadata,
            },
            "initial_policy": {
                "source": first_a["policy_source"], "model_status": session.initial["model_status"],
                "policy_shape": [38, 4], "policy_matrix": initial_matrix,
                "policy_hash": first_a["policy_hash"], "active_cell_count": int(session.state.active_mask.sum()),
                "first_b_policy_hash": first_b["policy_hash"],
                "first_b_policy_match": bool(first_a["policy_hash"] == first_b["policy_hash"]),
                "fallback_used": bool(session.initial["fallback_used"]),
                "fallback_reason": session.initial["fallback_reason"],
                "lightgbm_error_code": session.initial["lightgbm_error_code"],
            },
            "final_policy": {"policy_shape": [38, 4], "policy_matrix": final_matrix, "policy_long": long},
            "evaluation": {**final_metrics, **judgement, **evaluation_metadata},
            "optimization": {
                "objective_name": "expected_profit",
                "initial_objective": float(first_b["metrics"]["expected_profit"]),
                "final_objective": float(final_metrics["expected_profit"]),
                "objective_improvement": float(final_metrics["expected_profit"] - first_b["metrics"]["expected_profit"]),
                "baseline_objective": float(baseline_metrics["expected_profit"]),
                "final_vs_baseline_objective_improvement": float(
                    final_metrics["expected_profit"] - baseline_metrics["expected_profit"]
                ),
                "outer_iteration_count": int(len(session.all_evaluated)),
                "policy_outer_iteration": int(len(session.all_evaluated)),
                "inner_gradient_step_count": int(session.inner_gradient_step_count),
                "adam_inner_step": int(session.inner_gradient_step_count),
                "b_evaluation_count": b_evaluation_count,
                "converged": bool(session.converged), "stop_reason": session.stop_reason,
                **changes, "rollback_count": int(session.rollback_count),
                "fallback_used": fallback_used, "fallback_reason": fallback_reason,
                "runtime_seconds": float(time_elapsed(session.started)),
                **status,
            },
            "training": {
                "initial_policy_lightgbm_status": session.initial["model_status"],
                "initial_policy_metrics": training_metrics,
                "surrogate_training_status": "TRAINED" if session.surrogate.is_trained else "NOT_TRAINED",
                "surrogate_train_loss": session.surrogate.training_metrics.get("total_train_loss"),
                "surrogate_validation_loss": session.surrogate.training_metrics.get("total_validation_loss"),
                "surrogate_sample_count": len(session.replay), "real_b_sample_count": len(session.replay),
                "test_double_sample_count": 0,
                "baseline_replay_sample_count": 1,
                "optimization_candidate_sample_count": len(session.all_evaluated),
                "surrogate_training_epoch_count": int(len(session.surrogate_history)),
            },
            "comparison_to_no_discount": {
                "expected_demand_delta": float(final_metrics["expected_demand"] - baseline_metrics["expected_demand"]),
                "expected_sales_qty_delta": float(final_metrics["expected_sales_qty"] - baseline_metrics["expected_sales_qty"]),
                "expected_revenue_delta": float(final_metrics["expected_revenue"] - baseline_metrics["expected_revenue"]),
                "expected_profit_delta": float(final_metrics["expected_profit"] - baseline_metrics["expected_profit"]),
                "expected_waste_qty_delta": float(final_metrics["expected_waste_qty"] - baseline_metrics["expected_waste_qty"]),
                "profit_improved": bool(final_metrics["expected_profit"] > baseline_metrics["expected_profit"]),
            },
            "artifacts": {
                "result_json_path": str(result_path.resolve()), "optimization_history_path": str(history_path.resolve()),
                "policy_cell_history_path": str(cell_history_path.resolve()),
                "surrogate_training_history_path": str(surrogate_history_path.resolve()),
                "replay_buffer_path": str(replay_dir.resolve()), "run_log_path": str(log_path.resolve()),
                "initial_policy_lightgbm_path": str((model_dir / "initial_policy_lightgbm.txt").resolve()),
            },
            "model_metadata": model_metadata,
            "warnings": list(dict.fromkeys(session.initial["warnings"] + final_evaluation.get("warnings", []))),
        }
        response = to_jsonable(response)
        save_json(response, result_path)
        logger.info("status=SUCCESS stop_reason=%s converged=%s final_objective=%s", session.stop_reason, session.converged, final_metrics["expected_profit"])
        return response
    except ContractError as exc:
        logger.error("stage=%s code=%s message=%s\n%s", stage, exc.code.value, exc, traceback.format_exc())
        response = failure_response(request_id, exc)
    except Exception as exc:
        code_map = {
            "A_CANDIDATE_GENERATION": ErrorCode.POLICY_OPTIMIZATION_ERROR,
            "B_BASELINE_EVALUATION": ErrorCode.B_EVALUATION_ERROR,
            "B_EVALUATION": ErrorCode.B_EVALUATION_ERROR,
            "ARTIFACT_SAVE": ErrorCode.OUTPUT_SERIALIZATION_ERROR,
        }
        wrapped = ContractError(code_map.get(stage, ErrorCode.INPUT_SCHEMA_ERROR), str(exc), stage)
        logger.error("stage=%s code=%s message=%s\n%s", stage, wrapped.code.value, exc, traceback.format_exc())
        response = failure_response(request_id, wrapped)
    try:
        save_json(response, result_path)
    except Exception:
        logger.error("Failed to save failure JSON\n%s", traceback.format_exc())
    return response


def time_elapsed(started: float) -> float:
    import time
    return time.perf_counter() - float(started)


def run_from_json_file(input_json_path: str, output_json_path: str) -> dict[str, Any]:
    try:
        request = json.loads(Path(input_json_path).read_text(encoding="utf-8"))
    except Exception as exc:
        error = ContractError(ErrorCode.INPUT_SCHEMA_ERROR, f"Cannot read input JSON: {exc}", "INPUT_VALIDATION")
        response = failure_response(None, error); save_json(response, output_json_path); return response
    return run_discount_optimization(request, output_json_path)
