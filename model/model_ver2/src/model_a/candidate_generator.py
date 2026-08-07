"""Stateful public Model-A boundary: emit exactly one complete policy per call."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import numpy as np
import pandas as pd

from src.contracts.schemas import ContractError, ErrorCode, validate_runtime_request
from src.model_a.constraints import policy_caps, project_policy_numpy, round_execution_policy
from src.model_a.convergence import PassedPolicyConvergenceTracker, policy_change_metrics
from src.model_a.full_policy_surrogate import FullPolicySurrogate
from src.model_a.policy_optimizer import OuterInnerPolicyOptimizer
from src.contracts.b_modes import backend_for_mode, model_version_for_mode
from src.model_a.replay_buffer import RealPolicyReplayBuffer
from src.model_a.service import build_runtime_state, propose_initial_policy


def _policy_hash(policy: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(policy, np.float32).tobytes()).hexdigest()


class CandidateGenerationSession:
    def __init__(self, request: dict[str, Any]) -> None:
        self.request = validate_runtime_request(request)
        self.options = self.request["options"]
        self.state = build_runtime_state(self.request)
        self.caps = policy_caps(
            self.state.store_state["regular_price_vector"], self.state.store_state["unit_cost_vector"],
            self.state.store_state["product_max_discount_vector"],
        )
        try:
            self.initial = propose_initial_policy(self.request, state=self.state)
        except Exception as exc:
            if not bool(self.options.get("allow_initial_policy_fallback", False)):
                raise ContractError(ErrorCode.LIGHTGBM_ARTIFACT_LOAD_ERROR, str(exc), "INITIAL_POLICY") from exc
            fallback = round_execution_policy(self.state.current_policy, self.state.active_mask, self.caps)
            self.initial = {
                "source": "CURRENT_POLICY", "model_status": "LOAD_FAILED", "policy_shape": [38, 4],
                "policy_matrix": fallback, "active_cell_count": int(self.state.active_mask.sum()),
                "warnings": [f"EXPLICIT_LIGHTGBM_FALLBACK: {exc}"], "metrics": {}, "caps": self.caps,
                "fallback_used": True, "fallback_reason": str(exc), "lightgbm_error_code": "LIGHTGBM_ARTIFACT_LOAD_ERROR",
            }
        if self.initial["source"] != "LIGHTGBM" and not bool(self.options.get("allow_initial_policy_fallback", False)):
            raise ContractError(
                ErrorCode.LIGHTGBM_NOT_TRAINED,
                "A trained, schema-compatible InitialPolicyLightGBM artifact is required for normal operation",
                "INITIAL_POLICY",
                {"initial_policy_source": self.initial["source"], "warnings": self.initial["warnings"]},
            )
        self.replay = RealPolicyReplayBuffer(int(self.options["minimum_replay_size"]), seed=int(self.options["seed"]))
        self.surrogate = FullPolicySurrogate(self.state.state_tensor.shape[-1], seed=int(self.options["seed"]))
        self.optimizer = OuterInnerPolicyOptimizer(self.options, self.caps)
        self.tracker = PassedPolicyConvergenceTracker(
            int(self.options["convergence_patience"]), float(self.options["policy_tolerance"]),
            float(self.options["objective_relative_tolerance"]), float(self.options["objective_epsilon"]),
        )
        self.started = time.perf_counter()
        self.next_iteration = 1
        self.last_candidate: np.ndarray | None = None
        self.last_candidate_output: dict[str, Any] | None = None
        self.previous_evaluated_policy: np.ndarray | None = None
        self.previous_evaluation: dict[str, Any] | None = None
        self.accepted_policy: np.ndarray | None = None
        self.accepted_objective: float | None = None
        self.passed_pool: list[dict[str, Any]] = []
        self.all_evaluated: list[dict[str, Any]] = []
        self.optimization_history: list[dict[str, Any]] = []
        self.policy_cell_history: list[dict[str, Any]] = []
        self.surrogate_history: list[dict[str, Any]] = []
        self.inner_gradient_step_count = 0
        self.rollback_count = 0
        self.confirmation_mode = False
        self.stop_reason: str | None = None
        self.converged = False
        self.warmup_cursor = 0
        self.baseline_evaluation: dict[str, Any] | None = None
        self.rng = np.random.default_rng(int(self.options["seed"]))
        self._warmup = self._build_warmup()

    def generate(self, previous_b_evaluation: dict[str, Any] | None = None) -> dict[str, Any]:
        if previous_b_evaluation is not None:
            self._ingest(previous_b_evaluation)
        elif self.last_candidate is not None:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "previous_b_evaluation is required after the first A call", "A_CANDIDATE_GENERATION")

        if self.stop_reason is not None:
            return self._stop_output()

        if self.last_candidate is None:
            candidate = np.asarray(self.initial["policy_matrix"], np.float32)
            source = "LIGHTGBM" if self.initial["source"] == "LIGHTGBM" else self.initial["source"]
            adam_steps = 0
        else:
            candidate, source, adam_steps = self._next_policy()

        candidate = round_execution_policy(candidate, self.state.active_mask, self.caps)
        iteration = self.next_iteration
        self.next_iteration += 1
        self.last_candidate = candidate.copy()
        output = {
            "request_id": str(self.request["request_id"]),
            "store_id": str(self.request["decision"]["store_id"]),
            "policy_iteration": iteration,
            "policy_outer_iteration": iteration,
            "policy_shape": [38, 4],
            "policy_matrix": candidate,
            "policy_hash": _policy_hash(candidate),
            "policy_source": source,
            "candidate_ready": True,
            "model_status": {
                "initial_policy_lightgbm": self.initial["model_status"],
                "full_policy_surrogate": "TRAINED" if self.surrogate.is_trained else "WARMUP",
                "adam_inner_steps": adam_steps,
            },
            "optimization_status": self.status(),
            "warnings": list(self.initial["warnings"]),
        }
        self.last_candidate_output = output
        return output

    def record_no_discount_baseline(self, result: dict[str, Any]) -> None:
        """Store an actual-B zero-policy sample without making it an A candidate."""
        if self.baseline_evaluation is not None:
            raise ContractError(
                ErrorCode.INPUT_SCHEMA_ERROR,
                "No-discount baseline was already recorded for this request",
                "A_BASELINE_INGEST",
            )
        request_id = str(self.request["request_id"])
        store_id = str(self.request["decision"]["store_id"])
        zero_policy = np.zeros((38, 4), np.float32)
        if str(result.get("request_id")) != request_id:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "Baseline request_id mismatch", "A_BASELINE_INGEST")
        if str(result.get("store_id")) != store_id:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "Baseline store_id mismatch", "A_BASELINE_INGEST")
        if int(result.get("policy_iteration", -1)) != 0:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "Baseline policy_iteration must be 0", "A_BASELINE_INGEST")
        if str(result.get("policy_hash")) != _policy_hash(zero_policy):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "Baseline must be the complete zero policy", "A_BASELINE_INGEST")
        expected_backend = backend_for_mode(self.options["discriminator_mode"])
        expected_version = model_version_for_mode(self.options["discriminator_mode"])
        if result.get("b_backend") != expected_backend or result.get("b_model_version") != expected_version:
            raise ContractError(ErrorCode.B_EVALUATION_ERROR, "Baseline B backend/version mismatch", "A_BASELINE_INGEST")
        self.replay.add(
            self.request,
            self.state.state_tensor,
            zero_policy,
            self.state.active_mask,
            result,
            0,
            "NO_DISCOUNT_BASELINE",
            str(result["b_model_version"]),
        )
        self.baseline_evaluation = result

    def _ingest(self, result: dict[str, Any]) -> None:
        if self.last_candidate is None or self.last_candidate_output is None:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "A has no outstanding policy candidate", "A_FEEDBACK_INGEST")
        if str(result.get("request_id")) != str(self.request["request_id"]):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "B feedback request_id mismatch", "A_FEEDBACK_INGEST")
        if str(result.get("store_id")) != str(self.request["decision"]["store_id"]):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "B feedback store_id mismatch", "A_FEEDBACK_INGEST")
        if int(result.get("policy_iteration", -1)) != int(self.last_candidate_output["policy_iteration"]):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "B feedback policy_iteration mismatch", "A_FEEDBACK_INGEST")
        if str(result.get("policy_hash")) != str(self.last_candidate_output["policy_hash"]):
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "B feedback policy hash mismatch", "A_FEEDBACK_INGEST")
        expected_backend = backend_for_mode(self.options["discriminator_mode"])
        expected_version = model_version_for_mode(self.options["discriminator_mode"])
        if result.get("b_backend") != expected_backend or result.get("b_model_version") != expected_version:
            raise ContractError(
                ErrorCode.B_EVALUATION_ERROR,
                "B feedback discriminator backend/model version does not match the request",
                "A_FEEDBACK_INGEST",
            )

        iteration = int(self.last_candidate_output["policy_iteration"])
        self.replay.add(
            self.request, self.state.state_tensor, self.last_candidate, self.state.active_mask,
            result, iteration, str(self.last_candidate_output["policy_source"]), str(result["b_model_version"]),
        )
        metrics = result["metrics"]
        judgement = result["judgement"]
        objective = float(metrics["expected_profit"])
        passed = bool(judgement["threshold_pass"])
        changes = policy_change_metrics(
            self.previous_evaluated_policy if self.previous_evaluated_policy is not None else self.last_candidate,
            self.last_candidate, self.state.active_mask,
        )
        previous_profit = None if self.previous_evaluation is None else float(self.previous_evaluation["metrics"]["expected_profit"])
        previous_pass = False if self.previous_evaluation is None else bool(self.previous_evaluation["judgement"]["threshold_pass"])
        self.converged = self.tracker.update(previous_pass, passed, changes, previous_profit, objective)

        accepted = self.accepted_objective is None or objective >= self.accepted_objective - float(self.options["objective_tolerance"])
        rollback = not accepted
        if accepted:
            self.accepted_policy = self.last_candidate.copy()
            self.accepted_objective = objective
        else:
            self.rollback_count += 1
            # Warm-up policies intentionally explore diverse regions.  Enter
            # stability confirmation only after the neural/Adam phase has run.
            if (self.passed_pool or passed) and (
                self.surrogate.is_trained or self.last_candidate_output["policy_source"] in {"SURROGATE_ADAM", "CONVERGENCE_HOLD"}
            ):
                self.confirmation_mode = True

        record = {
            "store_id": str(self.request["decision"]["store_id"]),
            "policy_outer_iteration": iteration, "policy_epoch": iteration,
            "b_evaluation_count": int(result.get("b_evaluation_count", len(self.replay))),
            **{key: metrics.get(key) for key in metrics},
            "objective_value": objective,
            "objective_improvement": None if previous_profit is None else float(objective - previous_profit),
            "objective_relative_improvement": self.tracker.objective_relative_improvement,
            **changes, "threshold_pass": passed, "reject_reason": judgement.get("reject_reason"),
            "convergence_patience_count": self.tracker.count,
            "convergence_patience_required": self.tracker.patience,
            "consecutive_pass_count": self.tracker.consecutive_pass_count,
            "profit_threshold": result.get("profit_threshold"),
            "baseline_profit": result.get("baseline_profit"),
            "baseline_profit_sign": result.get("baseline_profit_sign"),
            "threshold_version": result.get("threshold_version"),
            "artifact_source": result.get("artifact_source"),
            "adam_inner_step": int(self.last_candidate_output["model_status"].get("adam_inner_steps", 0)),
            "rollback": rollback, "policy_source": self.last_candidate_output["policy_source"],
            "surrogate_trained": self.surrogate.is_trained, "b_backend": result["b_backend"],
        }
        self.optimization_history.append(record)
        evaluated = {"iteration": iteration, "policy": self.last_candidate.copy(), "result": result, "objective": objective}
        self.all_evaluated.append(evaluated)
        if passed:
            self.passed_pool.append(evaluated)
        for row in self.state.cell_table.itertuples(index=False):
            i, j = int(row.product_index), int(row.dte_index)
            self.policy_cell_history.append({
                "store_id": str(self.request["decision"]["store_id"]),
                "policy_outer_iteration": iteration, "product_id": row.product_id, "product_index": i,
                "dte_bucket": row.dte_bucket, "dte_index": j, "active_inventory_flag": bool(row.active_inventory_flag),
                "discount_rate": float(self.last_candidate[i, j]), "policy_source": self.last_candidate_output["policy_source"],
            })

        self.previous_evaluated_policy = self.last_candidate.copy()
        self.previous_evaluation = result
        if self.converged:
            self.stop_reason = "THRESHOLD_PASSED_AND_CONVERGED"
        elif iteration >= int(self.options["max_outer_iterations"]):
            self.stop_reason = "MAX_OUTER_ITERATIONS"
        elif int(result.get("b_evaluation_count", 0)) >= int(self.options["max_b_evaluations"]):
            self.stop_reason = "MAX_B_EVALUATIONS"
        elif time.perf_counter() - self.started >= float(self.options["max_runtime_seconds"]):
            self.stop_reason = "MAX_RUNTIME_SECONDS"

    def _next_policy(self):
        if self.confirmation_mode and self.passed_pool:
            return self.best_passed()["policy"].copy(), "CONVERGENCE_HOLD", 0
        if not self.replay.can_train:
            return self._next_warmup(), "REAL_B_SURROGATE_WARMUP", 0

        epochs = int(self.options["surrogate_epochs"] if not self.surrogate.is_trained else self.options["surrogate_update_epochs"])
        history = self.surrogate.train_from_replay(self.replay, epochs=epochs, seed=int(self.options["seed"]) + len(self.surrogate_history))
        epoch_offset = len(self.surrogate_history)
        for row in history:
            row = dict(row)
            row["surrogate_training_epoch"] = epoch_offset + int(row.pop("epoch"))
            self.surrogate_history.append(row)
        validation_loss = float(self.surrogate.training_metrics.get("total_validation_loss", float("inf")))
        if validation_loss > float(self.options["max_surrogate_validation_loss"]):
            if self.passed_pool:
                self.confirmation_mode = True
                return self.best_passed()["policy"].copy(), "CONVERGENCE_HOLD", 0
            return self._next_warmup(), "REAL_B_SURROGATE_WARMUP", 0
        base = self.accepted_policy if self.accepted_policy is not None else self.last_candidate
        proposal, _, _, steps = self.optimizer._inner_optimize(self.surrogate, self.state, base)
        candidate = round_execution_policy(proposal, self.state.active_mask, self.caps)
        self.inner_gradient_step_count += steps
        if _policy_hash(candidate) == _policy_hash(base) and self.passed_pool:
            self.confirmation_mode = True
            return self.best_passed()["policy"].copy(), "CONVERGENCE_HOLD", steps
        return candidate, "SURROGATE_ADAM", steps

    def _build_warmup(self):
        mask = self.state.active_mask
        current = round_execution_policy(self.state.current_policy, mask, self.caps)
        rule = round_execution_policy(np.tile(np.array([.40, .30, .20, 0], np.float32), (38, 1)), mask, self.caps)
        # The zero policy is evaluated once by the infrastructure orchestrator
        # as a baseline and stored in replay with iteration=0. It must not be
        # reused as the operational initial or warm-up candidate.
        policies = [current, rule]
        for anchor in (current, rule, np.asarray(self.initial["policy_matrix"], np.float32)):
            noise = np.zeros((38, 4), np.float32)
            noise[mask] = self.rng.normal(0, .015, int(mask.sum()))
            policies.append(project_policy_numpy(anchor + noise, mask, self.caps))
        return policies

    def _next_warmup(self):
        seen = {
            _policy_hash(np.zeros((38, 4), np.float32)),
            *(_policy_hash(item["policy"]) for item in self.all_evaluated),
        }
        while self.warmup_cursor < len(self._warmup):
            candidate = round_execution_policy(self._warmup[self.warmup_cursor], self.state.active_mask, self.caps)
            self.warmup_cursor += 1
            if _policy_hash(candidate) not in seen:
                return candidate
        base = self.accepted_policy if self.accepted_policy is not None else self.last_candidate
        noise = np.zeros((38, 4), np.float32)
        noise[self.state.active_mask] = self.rng.normal(0, .01, int(self.state.active_mask.sum()))
        return project_policy_numpy(base + noise, self.state.active_mask, self.caps)

    def best_passed(self):
        if not self.passed_pool:
            return None
        previous = self.state.current_policy
        def key(item):
            metrics = item["result"]["metrics"]
            change = policy_change_metrics(previous, item["policy"], self.state.active_mask)["policy_l1_change"]
            return (
                float(metrics["expected_profit"]), -float(metrics["expected_waste_qty"]),
                -float(metrics.get("expected_waste_cost") or 0.0), -float(change), -int(item["iteration"]),
            )
        return max(self.passed_pool, key=key)

    def best_available(self):
        return self.best_passed() or (max(self.all_evaluated, key=lambda item: item["objective"]) if self.all_evaluated else None)

    def status(self):
        best = self.best_passed()
        return {
            "converged": self.converged, "stop_reason": self.stop_reason,
            "convergence_patience_required": self.tracker.patience,
            "convergence_patience_count": self.tracker.count,
            "consecutive_pass_count": self.tracker.consecutive_pass_count,
            "passed_policy_count": len(self.passed_pool),
            "best_passed_policy_iteration": None if best is None else int(best["iteration"]),
            "best_passed_objective": None if best is None else float(best["objective"]),
            "objective_relative_improvement": self.tracker.objective_relative_improvement,
            "rollback_count": self.rollback_count,
        }

    def _stop_output(self):
        return {
            "request_id": str(self.request["request_id"]),
            "store_id": str(self.request["decision"]["store_id"]),
            "candidate_ready": False,
            "policy_shape": [38, 4], "policy_matrix": None, "policy_source": None,
            "model_status": {"initial_policy_lightgbm": self.initial["model_status"], "full_policy_surrogate": "TRAINED" if self.surrogate.is_trained else "WARMUP"},
            "optimization_status": self.status(), "warnings": list(self.initial["warnings"]),
        }

    def frames(self):
        return pd.DataFrame(self.optimization_history), pd.DataFrame(self.policy_cell_history), pd.DataFrame(self.surrogate_history)


_SESSIONS: dict[str, CandidateGenerationSession] = {}


def reset_candidate_session(request_id: str) -> None:
    _SESSIONS.pop(str(request_id), None)


def get_candidate_session(request_id: str) -> CandidateGenerationSession:
    try:
        return _SESSIONS[str(request_id)]
    except KeyError as exc:
        raise KeyError(f"No A candidate session for request_id={request_id}") from exc


def generate_discount_candidate(request: dict, previous_b_evaluation: dict | None = None) -> dict:
    """Return one A policy candidate, or a stop status after ingesting the last B result."""
    validated = validate_runtime_request(request)
    request_id = str(validated["request_id"])
    session = _SESSIONS.get(request_id)
    if session is None:
        if previous_b_evaluation is not None:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "First A call cannot include B feedback", "A_CANDIDATE_GENERATION")
        session = CandidateGenerationSession(validated)
        _SESSIONS[request_id] = session
    return session.generate(previous_b_evaluation)
