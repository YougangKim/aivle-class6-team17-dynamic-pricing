"""Stateful public Model-A boundary: emit exactly one complete policy per call."""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from src.contracts.schemas import ContractError, ErrorCode, validate_runtime_request
from src.contracts.executable_rule import load_executable_rule_vector
from src.model_a.constraints import (
    build_executable_rule_policy,
    policy_caps,
    previous_policy_lower_bounds,
    round_execution_policy,
)
from src.model_a.convergence import PassedPolicyConvergenceTracker, policy_change_metrics
from src.model_a.full_policy_surrogate import FullPolicySurrogate
from src.model_a.policy_optimizer import OuterInnerPolicyOptimizer
from src.contracts.b_modes import backend_for_mode, model_version_for_mode
from src.model_a.replay_buffer import RealPolicyReplayBuffer
from src.model_a.service import build_runtime_state, propose_initial_policy


def _policy_hash(policy: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(policy, np.float32).tobytes()).hexdigest()


class CandidateGenerationSession:
    # This is deliberately a small, fixed operating budget.  It is not a
    # replacement for the diagnostic direct search, which may evaluate every
    # active cell offline.  Two cells x four discrete moves produces at most
    # eight sparse B samples after the current and executable-Rule anchors.
    RULE_CENTERED_WARMUP_TOP_K = 2
    RULE_CENTERED_PERTURBATION_PPT = (1, 2, 3, 5)

    def __init__(self, request: dict[str, Any]) -> None:
        self.request = validate_runtime_request(request)
        self.options = self.request["options"]
        self.state = build_runtime_state(self.request)
        self.caps = policy_caps(
            self.state.store_state["regular_price_vector"], self.state.store_state["unit_cost_vector"],
            self.state.store_state["product_max_discount_vector"],
        )
        # The lower bound is derived once from the normalized request and is
        # passed into every A projection, including Adam's inner gradient
        # steps.  It is never applied after an A/B candidate has been chosen.
        self.previous_published_lower_bound = previous_policy_lower_bounds(
            self.request, self.state.active_mask, self.caps
        )
        try:
            self.initial = propose_initial_policy(self.request, state=self.state)
        except Exception as exc:
            if not bool(self.options.get("allow_initial_policy_fallback", False)):
                raise ContractError(ErrorCode.LIGHTGBM_ARTIFACT_LOAD_ERROR, str(exc), "INITIAL_POLICY") from exc
            fallback = self._execution_policy(self.state.current_policy)
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
        self.optimizer = OuterInnerPolicyOptimizer(
            self.options, self.caps, lower_bounds=self.previous_published_lower_bound
        )
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
        self.accepted_priority: tuple[int, float] | None = None
        self.passed_pool: list[dict[str, Any]] = []
        self.all_evaluated: list[dict[str, Any]] = []
        self.optimization_history: list[dict[str, Any]] = []
        self.policy_cell_history: list[dict[str, Any]] = []
        self.surrogate_history: list[dict[str, Any]] = []
        self.inner_gradient_step_count = 0
        self.adam_call_count = 0
        self.surrogate_train_count = 0
        self.rollback_count = 0
        self.confirmation_mode = False
        self.stop_reason: str | None = None
        self.converged = False
        self.warmup_cursor = 0
        self.required_warmup_count = 0
        self.emitted_warmup_candidate_count = 0
        self.evaluated_warmup_candidate_count = 0
        self.planned_sparse_warmup_candidate_count = 0
        self.emitted_sparse_warmup_candidate_count = 0
        self.evaluated_sparse_warmup_candidate_count = 0
        self.baseline_evaluation: dict[str, Any] | None = None
        self.rule_policy: np.ndarray | None = None
        self.warmup_selected_cells: list[dict[str, Any]] = []
        self.warmup_candidate_sources: list[str] = []
        self._warmup = self._build_warmup()

    def generate(self, previous_b_evaluation: dict[str, Any] | None = None) -> dict[str, Any]:
        if previous_b_evaluation is not None:
            self._ingest(previous_b_evaluation)
        elif self.last_candidate is not None:
            raise ContractError(ErrorCode.INPUT_SCHEMA_ERROR, "previous_b_evaluation is required after the first A call", "A_CANDIDATE_GENERATION")

        if self.stop_reason is not None:
            return self._stop_output()

        next_policy = self._next_policy()
        if next_policy is None:
            # A validation guard can stop the session before a further policy
            # is emitted.  The just-ingested real-B samples remain available
            # for diagnostics, but no fabricated fallback candidate is sent.
            return self._stop_output()
        candidate, source, adam_steps = next_policy

        candidate = self._execution_policy(candidate)
        iteration = self.next_iteration
        self.next_iteration += 1
        self.last_candidate = candidate.copy()
        if source == "SURROGATE_ADAM":
            self.adam_call_count += 1
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
        if self.last_candidate_output["policy_source"] in self.warmup_candidate_sources:
            self.evaluated_warmup_candidate_count += 1
            if self.last_candidate_output["policy_source"] == "REAL_B_SURROGATE_WARMUP":
                self.evaluated_sparse_warmup_candidate_count += 1
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

        waste_feasible = bool(float(metrics["expected_waste_rate"]) <= float(result["waste_target"]))
        # Accepted anchors are intentionally ordered as follows:
        # threshold pass > waste-feasible non-pass > waste violation.  A
        # waste-violating sample remains useful replay/diagnostic evidence,
        # but it must never become the operational Adam anchor.
        priority = (int(passed), objective)
        accepted = waste_feasible and (
            self.accepted_priority is None or priority >= self.accepted_priority
        )
        rollback = not accepted
        if accepted:
            self.accepted_policy = self.last_candidate.copy()
            self.accepted_objective = objective
            self.accepted_priority = priority
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
        evaluated = {
            "iteration": iteration,
            "policy": self.last_candidate.copy(),
            "policy_source": self.last_candidate_output["policy_source"],
            "result": result,
            "objective": objective,
        }
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
        elif (
            self.last_candidate_output["policy_source"] == "SURROGATE_ADAM"
            and self.adam_call_count >= int(self.options["max_outer_iterations"])
        ):
            # Warm-up is a bounded replay-acquisition phase, not an outer
            # Adam iteration.  Keeping the counters separate guarantees that
            # max_outer_iterations remains available to Surrogate+Adam.
            self.stop_reason = "MAX_OUTER_ITERATIONS"
        elif self.warmup_cursor >= len(self._warmup) and not self.replay.can_train:
            self.stop_reason = "INSUFFICIENT_REAL_B_REPLAY"
        elif int(result.get("b_evaluation_count", 0)) >= int(self.options["max_b_evaluations"]):
            self.stop_reason = "MAX_B_EVALUATIONS"
        elif time.perf_counter() - self.started >= float(self.options["max_runtime_seconds"]):
            self.stop_reason = "MAX_RUNTIME_SECONDS"

    def _next_policy(self):
        if self.confirmation_mode and self.passed_pool:
            return self.best_passed()["policy"].copy(), "CONVERGENCE_HOLD", 0
        if self.warmup_cursor < len(self._warmup):
            warmup_candidate = self._next_warmup()
            if warmup_candidate is not None:
                return warmup_candidate
        if not self.replay.can_train:
            # All bounded candidates were either sent to B or collapsed to
            # duplicates during 1%p projection.  Do not emit a synthetic or
            # repeated policy merely to reach replay size.
            self.stop_reason = "INSUFFICIENT_REAL_B_REPLAY"
            return None

        epochs = int(self.options["surrogate_epochs"] if not self.surrogate.is_trained else self.options["surrogate_update_epochs"])
        history = self.surrogate.train_from_replay(self.replay, epochs=epochs, seed=int(self.options["seed"]) + len(self.surrogate_history))
        self.surrogate_train_count += 1
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
            self.stop_reason = "SURROGATE_VALIDATION_GUARD"
            return None
        base = self.accepted_policy if self.accepted_policy is not None else self.rule_policy
        waste_target = None
        if self.previous_evaluation is not None:
            waste_target = float(self.previous_evaluation["waste_target"])
        proposal, _, _, steps = self.optimizer._inner_optimize(
            self.surrogate, self.state, base, waste_target=waste_target
        )
        candidate = self._execution_policy(proposal)
        self.inner_gradient_step_count += steps
        if _policy_hash(candidate) == _policy_hash(base) and self.passed_pool:
            self.confirmation_mode = True
            return self.best_passed()["policy"].copy(), "CONVERGENCE_HOLD", steps
        return candidate, "SURROGATE_ADAM", steps

    def _build_warmup(self):
        """Build independent, sparse actual-B replay candidates from state.

        The score intentionally uses only the current runtime state and the
        executable Rule policy.  It prioritizes inventory value at risk:
        on-hand quantity times unit gross margin, amplified by short DTE,
        low freshness, product waste risk, and the Rule discount.  The latter
        terms determine which active cells receive the small discount
        reductions; no diagnostic file, direct-search result, or mock label
        participates in this calculation.
        """
        mask = self.state.active_mask
        current = self._execution_policy(self.state.current_policy)
        root = Path(__file__).resolve().parents[2]
        rule = build_executable_rule_policy(load_executable_rule_vector(root), mask, self.caps)
        self.rule_policy = rule.copy()
        # The zero policy is evaluated once by the infrastructure orchestrator
        # as a baseline and stored in replay with iteration=0. It must not be
        # reused as the operational initial or warm-up candidate.
        initial_policy = self._execution_policy(np.asarray(self.initial["policy_matrix"], np.float32))
        initial_source = "LIGHTGBM" if self.initial["source"] == "LIGHTGBM" else "CURRENT_POLICY"
        policies: list[tuple[np.ndarray, str]] = [(initial_policy, initial_source)]
        # A trained LightGBM policy must remain the first actual-B candidate.
        # Preserve CURRENT_POLICY as a separate replay anchor only when it is
        # distinct; in the current NOT_TRAINED fallback it is already first.
        if _policy_hash(current) != _policy_hash(initial_policy):
            policies.append((current, "CURRENT_POLICY"))
        policies.append((rule, "EXECUTABLE_RULE_POLICY"))
        active = self.state.cell_table.loc[self.state.cell_table["active_inventory_flag"].astype(bool)].copy()
        if not active.empty:
            active["rule_discount_rate"] = [
                float(rule[int(row.product_index), int(row.dte_index)])
                for row in active.itertuples(index=False)
            ]
            active = active.loc[active["rule_discount_rate"] >= 0.01].copy()
            active["warmup_priority_score"] = (
                active["available_qty"].clip(lower=0.0)
                * (active["regular_price"] - active["unit_cost"]).clip(lower=0.0)
                * (
                    1.0
                    + active["product_baseline_waste_rate"].clip(lower=0.0)
                    + (3 - active["dte_index"].astype(float)).clip(lower=0.0) / 3.0
                    + (1.0 - active["freshness_score"].clip(0.0, 1.0))
                    + active["rule_discount_rate"]
                )
            )
            active = active.sort_values(
                ["warmup_priority_score", "available_qty", "product_index", "dte_index"],
                ascending=[False, False, True, True],
                kind="mergesort",
            )
        selected_sparse_cells = active.head(self.RULE_CENTERED_WARMUP_TOP_K)
        self.warmup_selected_cells = [
            {
                "rank": rank,
                "product_id": str(row.product_id),
                "product_index": int(row.product_index),
                "dte_index": int(row.dte_index),
                "priority_score": float(row.warmup_priority_score),
            }
            for rank, row in enumerate(selected_sparse_cells.itertuples(index=False), start=1)
        ]
        for cell in self.warmup_selected_cells:
            product_index = int(cell["product_index"])
            dte_index = int(cell["dte_index"])
            for decrease_ppt in self.RULE_CENTERED_PERTURBATION_PPT:
                sparse = rule.copy()
                sparse[product_index, dte_index] = max(0.0, sparse[product_index, dte_index] - decrease_ppt / 100.0)
                policies.append((
                    self._execution_policy(sparse),
                    "REAL_B_SURROGATE_WARMUP",
                ))
        self.required_warmup_count = len(policies)
        self.planned_sparse_warmup_candidate_count = sum(
            source == "REAL_B_SURROGATE_WARMUP" for _, source in policies
        )
        self.warmup_candidate_sources = list(dict.fromkeys(source for _, source in policies))
        return policies

    def _next_warmup(self):
        seen = {
            _policy_hash(np.zeros((38, 4), np.float32)),
            *(_policy_hash(item["policy"]) for item in self.all_evaluated),
        }
        while self.warmup_cursor < len(self._warmup):
            raw_candidate, source = self._warmup[self.warmup_cursor]
            candidate = self._execution_policy(raw_candidate)
            self.warmup_cursor += 1
            if _policy_hash(candidate) not in seen:
                self.emitted_warmup_candidate_count += 1
                if source == "REAL_B_SURROGATE_WARMUP":
                    self.emitted_sparse_warmup_candidate_count += 1
                return candidate, source, 0
        # A later perturbation may project to an already evaluated policy
        # (e.g. Rule -3%p and -5%p both become zero).  Let _next_policy move
        # directly to train/stop rather than evaluating a duplicate fallback.
        return None

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

    def best_diagnostic_candidate(self):
        """Return the best B-evaluated *unpassed* policy for diagnostics only."""
        unpassed = [
            item
            for item in self.all_evaluated
            if not bool(item["result"]["judgement"]["threshold_pass"])
        ]
        return max(unpassed, key=lambda item: item["objective"]) if unpassed else None

    def best_available(self):
        """Return only an approved operating policy.

        Kept as a compatibility alias for callers that previously used this
        method.  An unpassed policy is never an available operating policy;
        callers that need debugging information must explicitly use
        ``best_diagnostic_candidate``.
        """
        return self.best_passed()

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
            "replay_sample_count": len(self.replay),
            # Keep the older generic count while making the planned/emitted
            # distinction explicit: projection can collapse a planned sparse
            # move into a duplicate policy that is intentionally not sent to B.
            "warmup_candidate_count": self.required_warmup_count,
            "planned_warmup_candidate_count": self.required_warmup_count,
            "emitted_warmup_candidate_count": self.emitted_warmup_candidate_count,
            "evaluated_warmup_candidate_count": self.evaluated_warmup_candidate_count,
            "planned_sparse_warmup_candidate_count": self.planned_sparse_warmup_candidate_count,
            "emitted_sparse_warmup_candidate_count": self.emitted_sparse_warmup_candidate_count,
            "evaluated_sparse_warmup_candidate_count": self.evaluated_sparse_warmup_candidate_count,
            "warmup_candidate_sources": list(self.warmup_candidate_sources),
            "warmup_selected_cells": list(self.warmup_selected_cells),
            "surrogate_train_count": self.surrogate_train_count,
            "adam_call_count": self.adam_call_count,
            "adam_step_count": self.inner_gradient_step_count,
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

    def _execution_policy(self, policy: np.ndarray) -> np.ndarray:
        """Apply FINAL_RELEASE executable constraints plus rolling lower bounds."""
        return round_execution_policy(
            policy,
            self.state.active_mask,
            self.caps,
            lower_bounds=self.previous_published_lower_bound,
        )

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
