"""REAL_B outer loop plus bounded Adam inner loop over the 38x4 policy tensor."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any

import numpy as np
import pandas as pd
import torch

from src.model_a.constraints import project_policy_numpy, project_policy_tensor_, round_execution_policy
from src.model_a.convergence import ConvergenceTracker, policy_change_metrics
from src.model_a.full_policy_surrogate import FullPolicySurrogate
from src.model_a.replay_buffer import RealPolicyReplayBuffer


@dataclass
class PolicyOptimizationResult:
    initial_policy: np.ndarray
    final_policy: np.ndarray
    final_evaluation: dict[str, Any]
    optimization_history: pd.DataFrame
    policy_cell_history: pd.DataFrame
    surrogate_history: pd.DataFrame
    replay: RealPolicyReplayBuffer
    surrogate: FullPolicySurrogate
    converged: bool
    stop_reason: str
    rollback_count: int
    fallback_used: bool
    fallback_reason: str | None
    inner_gradient_step_count: int
    runtime_seconds: float


class OuterInnerPolicyOptimizer:
    def __init__(self, options: dict[str, Any], caps: np.ndarray) -> None:
        self.options = options; self.caps = np.asarray(caps, np.float32)
        self.seed = int(options["seed"]); self.rng = np.random.default_rng(self.seed); torch.manual_seed(self.seed)
        self.policy_lr = float(options.get("policy_learning_rate", 0.02))
        self.trust_region = float(options.get("trust_region", 0.05))
        self.max_cell_change = float(options.get("max_cell_change_per_outer", 0.05))
        self.max_surrogate_validation_loss = float(options.get("max_surrogate_validation_loss", 5.0))

    def run(self, request, state, initial_policy, b_service):
        started = time.perf_counter(); mask = state.active_mask
        replay = RealPolicyReplayBuffer(minimum_size=int(self.options.get("minimum_replay_size", 6)), seed=self.seed)
        surrogate = FullPolicySurrogate(state.state_tensor.shape[-1], seed=self.seed)
        histories, cell_histories, training_history = [], [], []
        candidates: list[tuple[np.ndarray, dict, float]] = []; seen = set(); rollback_count = 0; inner_count = 0

        def evaluate(policy, iteration, source):
            result = b_service.evaluate_policy(request, policy, mask, {"store_state": state.store_state})
            replay.add(request, state.state_tensor, policy, mask, result, iteration, source)
            objective = float(result["metrics"]["expected_profit"])
            candidates.append((policy.copy(), result, objective)); seen.add(self._hash(policy))
            return result, objective

        initial = round_execution_policy(initial_policy, mask, self.caps)
        result, objective = evaluate(initial, 0, "INITIAL_POLICY")
        initial_objective = objective; current = initial.copy(); current_result = result; current_objective = objective
        best = (current.copy(), current_result, current_objective)
        previous_validated = current.copy(); previous_objective = current_objective
        self._record(histories, 0, b_service.evaluation_count, result, objective, None, policy_change_metrics(current, current, mask), 0, 0, False, "INITIAL_REAL_B", outer_iteration=0)
        self._record_cells(cell_histories, 0, state, current, "INITIAL_REAL_B", outer_iteration=0)

        warmup = self._warmup_policies(state.current_policy, initial, mask)
        warm_iteration = 1
        for policy in warmup:
            if replay.can_train or b_service.evaluation_count >= self.options["max_b_evaluations"]: break
            policy = round_execution_policy(policy, mask, self.caps)
            if self._hash(policy) in seen: continue
            warm_result, warm_objective = evaluate(policy, warm_iteration, "REAL_B_SURROGATE_WARMUP")
            changes = policy_change_metrics(previous_validated, policy, mask)
            self._record(histories, warm_iteration, b_service.evaluation_count, warm_result, warm_objective, warm_objective - previous_objective, changes, 0, 0, False, "REAL_B_WARMUP", outer_iteration=0)
            self._record_cells(cell_histories, warm_iteration, state, policy, "REAL_B_WARMUP", outer_iteration=0)
            if warm_result["judgement"]["threshold_pass"] and warm_objective > best[2]: best = (policy.copy(), warm_result, warm_objective)
            previous_validated, previous_objective = policy.copy(), warm_objective; warm_iteration += 1
        if not replay.can_train:
            return self._finish(initial, best, histories, cell_histories, training_history, replay, surrogate, False, "INSUFFICIENT_REAL_B_REPLAY", rollback_count, True, "Surrogate minimum REAL_B replay size not reached", inner_count, started)

        new_history = surrogate.train_from_replay(replay, epochs=int(self.options.get("surrogate_epochs", 40)), seed=self.seed)
        training_history.extend(new_history)
        tracker = ConvergenceTracker(int(self.options["patience"]), float(self.options["policy_tolerance"]), float(self.options["objective_tolerance"]))
        converged = False; stop_reason = "MAX_OUTER_ITERATIONS"; current = best[0].copy(); current_result = best[1]; current_objective = best[2]
        outer_start = warm_iteration
        for outer in range(1, int(self.options["max_outer_iterations"]) + 1):
            iteration = outer_start + outer - 1
            if time.perf_counter() - started >= self.options["max_runtime_seconds"]:
                stop_reason = "MAX_RUNTIME_SECONDS"; break
            if b_service.evaluation_count >= self.options["max_b_evaluations"]:
                stop_reason = "MAX_B_EVALUATIONS"; break
            val_loss = float(surrogate.training_metrics.get("total_validation_loss", float("inf")))
            if val_loss > self.max_surrogate_validation_loss:
                stop_reason = "SURROGATE_VALIDATION_GUARD"; break
            proposal, predicted_objective, gradient, steps = self._inner_optimize(surrogate, state, current)
            inner_count += steps
            candidate = round_execution_policy(proposal, mask, self.caps)
            if self._hash(candidate) in seen:
                stop_reason = "DUPLICATE_POLICY_GUARD"; break
            candidate_result, candidate_objective = evaluate(candidate, iteration, "ADAM_INNER_LOOP")
            changes = policy_change_metrics(current, candidate, mask)
            actual_improvement = candidate_objective - current_objective
            accepted = self.accept_real_b_update(current_objective, candidate_objective, float(self.options["objective_tolerance"]))
            if accepted:
                current, current_result, current_objective = candidate.copy(), candidate_result, candidate_objective
                if candidate_result["judgement"]["threshold_pass"] and candidate_objective > best[2]: best = (candidate.copy(), candidate_result, candidate_objective)
            else:
                rollback_count += 1
            converged = tracker.update(candidate_result["judgement"]["threshold_pass"] and accepted, changes if accepted else policy_change_metrics(current, current, mask), actual_improvement if accepted else 0.0)
            reason = "CONVERGED" if converged else ("REAL_B_ACCEPTED" if accepted else "REAL_B_ROLLBACK")
            self._record(histories, iteration, b_service.evaluation_count, candidate_result, candidate_objective, actual_improvement, changes, tracker.count, steps, converged, reason, predicted_objective, not accepted, outer_iteration=outer)
            self._record_cells(cell_histories, iteration, state, candidate, reason, outer_iteration=outer)
            if converged: stop_reason = "THRESHOLD_POLICY_OBJECTIVE_CONVERGED"; break
            update_history = surrogate.train_from_replay(replay, epochs=int(self.options.get("surrogate_update_epochs", 8)), seed=self.seed + outer)
            offset = len(training_history)
            for row in update_history: row["epoch"] += offset
            training_history.extend(update_history)

        passing = [item for item in candidates if item[1]["judgement"]["threshold_pass"]]
        final = max(passing or candidates, key=lambda item: item[2])
        fallback = not converged
        fallback_reason = None if converged else ("Best REAL_B-validated threshold policy selected" if passing else "No threshold-passing policy; best REAL_B feasible policy selected")
        return self._finish(initial, final, histories, cell_histories, training_history, replay, surrogate, converged, stop_reason, rollback_count, fallback, fallback_reason, inner_count, started)

    def _inner_optimize(self, surrogate, state, current):
        state_tensor = torch.as_tensor(state.state_tensor[None], dtype=torch.float32)
        mask_tensor = torch.as_tensor(state.active_mask[None], dtype=torch.bool)
        policy_tensor = torch.tensor(current, dtype=torch.float32, requires_grad=True)
        policy_optimizer = torch.optim.Adam([policy_tensor], lr=self.policy_lr)
        predicted = None; gradient = np.zeros((38,4), np.float32)
        with surrogate.frozen():
            for _ in range(min(int(self.options["inner_gradient_steps"]), 50)):
                policy_optimizer.zero_grad(set_to_none=True)
                raw = surrogate.predict_raw_tensor(state_tensor, policy_tensor[None], mask_tensor)
                predicted = raw[0, 3]
                loss = -predicted; loss.backward()
                if policy_tensor.grad is None or policy_tensor.grad.shape != (38,4): raise RuntimeError("Policy gradient shape is not [38,4]")
                gradient = policy_tensor.grad.detach().cpu().numpy().copy()
                policy_optimizer.step()
                project_policy_tensor_(policy_tensor, state.active_mask, self.caps, current, min(self.trust_region, self.max_cell_change))
        return policy_tensor.detach().cpu().numpy(), float(predicted.detach()), gradient, min(int(self.options["inner_gradient_steps"]), 50)

    def _warmup_policies(self, current, initial, mask):
        policies = [np.zeros((38,4), np.float32), current.copy(), np.tile(np.array([.40,.30,.20,0],np.float32),(38,1)), initial.copy()]
        while len(policies) < int(self.options.get("minimum_replay_size", 6)) + 3:
            anchor = policies[len(policies) % 4]
            noise = np.zeros((38,4), np.float32); noise[mask] = self.rng.normal(0, .015, int(mask.sum()))
            policies.append(project_policy_numpy(anchor + noise, mask, self.caps))
        return policies

    @staticmethod
    def _hash(policy): return hashlib.sha256(np.asarray(policy,np.float32).tobytes()).hexdigest()
    @staticmethod
    def accept_real_b_update(current_objective, candidate_objective, tolerance):
        """The surrogate proposes; only the actual B objective can accept the update."""
        return bool(float(candidate_objective) >= float(current_objective) - float(tolerance))
    @staticmethod
    def _record(rows, iteration, b_count, result, objective, improvement, changes, patience, inner_steps, converged, reason, predicted=None, rollback=False, outer_iteration=0):
        metrics=result["metrics"]; judgement=result["judgement"]
        phase = "ADAM_OUTER" if outer_iteration else ("INITIAL" if iteration == 0 else "REAL_B_WARMUP")
        rows.append({"iteration":iteration,"outer_iteration":outer_iteration,"phase":phase,"b_evaluation_count":b_count,**{k:metrics.get(k) for k in metrics},"objective_value":objective,"predicted_objective":predicted,"objective_improvement":improvement,**changes,"threshold_pass":judgement["threshold_pass"],"reject_reason":judgement["reject_reason"],"profit_threshold":result.get("profit_threshold"),"baseline_profit":result.get("baseline_profit"),"baseline_profit_sign":result.get("baseline_profit_sign"),"threshold_version":result.get("threshold_version"),"artifact_source":result.get("artifact_source"),"patience_count":patience,"inner_gradient_steps":inner_steps,"rollback":rollback,"converged":converged,"stop_reason":reason,"b_backend":result["b_backend"]})
    @staticmethod
    def _record_cells(rows, iteration, state, policy, source, outer_iteration=0):
        for row in state.cell_table.itertuples(index=False):
            i,j=int(row.product_index),int(row.dte_index)
            rows.append({"iteration":iteration,"outer_iteration":outer_iteration,"product_id":row.product_id,"product_index":i,"dte_bucket":row.dte_bucket,"dte_index":j,"available_qty":float(row.available_qty),"active_inventory_flag":bool(row.active_inventory_flag),"discount_rate":float(policy[i,j]),"policy_source":source})
    @staticmethod
    def _finish(initial, final, histories, cell_histories, training_history, replay, surrogate, converged, stop_reason, rollback_count, fallback, fallback_reason, inner_count, started):
        return PolicyOptimizationResult(initial,final[0],final[1],pd.DataFrame(histories),pd.DataFrame(cell_histories),pd.DataFrame(training_history),replay,surrogate,converged,stop_reason,rollback_count,fallback,fallback_reason,inner_count,time.perf_counter()-started)
