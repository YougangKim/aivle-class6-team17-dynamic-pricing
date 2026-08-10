"""Create offline, executable LightGBM labels from current FINAL_RELEASE A/B contracts.

This is an offline bootstrap tool only.  It does not participate in the
runtime optimiser and it never reads the official Test period.  Candidate
policies are evaluated by the delivered REAL_B evaluator and accepted as
labels only when the current executable-Rule discriminator passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts.b_modes import SCOPE_ALIGNED_EXPERIMENTAL
from src.contracts.executable_rule import load_executable_rule_vector
from src.contracts.mappings import POLICY_SHAPE
from src.model_a.constraints import (
    build_executable_rule_policy,
    policy_caps,
    round_execution_policy,
)
from src.model_a.service import build_runtime_state
from src.model_b.evaluator import RealBService


TRAIN_START = pd.Timestamp("2025-01-01")
TRAIN_END = pd.Timestamp("2025-09-30")
VALID_START = pd.Timestamp("2025-10-01")
VALID_END = pd.Timestamp("2025-11-15")
TEST_START = pd.Timestamp("2025-11-16")
TEST_END = pd.Timestamp("2025-12-31")
DISCRIMINATOR_MODE = SCOPE_ALIGNED_EXPERIMENTAL


def _hash(policy: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(policy, np.float32).tobytes()).hexdigest()


def _request(store_id: str, date: pd.Timestamp, hour: int, group_id: str) -> dict[str, Any]:
    timestamp = pd.Timestamp(date).normalize() + pd.Timedelta(hours=int(hour))
    return {
        "request_id": f"{group_id}_{store_id}_{timestamp:%Y%m%dT%H%M%S}",
        "schema_version": "1.0",
        "decision": {
            "store_id": str(store_id),
            "date": timestamp.date().isoformat(),
            "hour": int(hour),
            "decision_timestamp": timestamp.tz_localize("Asia/Seoul").isoformat(),
        },
        # Deliberately use the repository's historical daily inventory snapshot.
        # No receipt / transaction input and no Test-period reconstruction is read.
        "state": {"source": "OFFLINE_TRAINING_PROJECT_SNAPSHOT", "cells": []},
        "options": {
            "seed": 42,
            "discriminator_mode": DISCRIMINATOR_MODE,
            "allow_initial_policy_fallback": True,
        },
    }


def _candidate_states(start: pd.Timestamp, end: pd.Timestamp, max_states: int) -> list[tuple[str, pd.Timestamp, int]]:
    """Select distinct store/timestamp states without inspecting Test inventory."""
    inv = pd.read_csv(ROOT / "data" / "inventory.csv", usecols=["store_id", "current_date", "available_qty"])
    inv["current_date"] = pd.to_datetime(inv["current_date"]).dt.normalize()
    valid = inv[(inv.current_date >= start) & (inv.current_date <= end)]
    daily = valid.groupby(["current_date", "store_id"], as_index=False).available_qty.sum()
    daily = daily[daily.available_qty > 0].sort_values(["current_date", "store_id"])
    if daily.empty:
        raise RuntimeError(f"No historical inventory states in {start.date()}..{end.date()}")
    # Interleave dates/stores/hours to avoid copying a single policy group.
    hours = (12, 15, 18)
    rows = []
    for index, row in enumerate(daily.itertuples(index=False)):
        rows.append((str(row.store_id), pd.Timestamp(row.current_date), hours[index % len(hours)]))
    stride = max(1, len(rows) // max_states)
    selected = rows[::stride][:max_states]
    # A short split can have fewer dates than max_states; do not duplicate a state.
    return selected


def _evaluate(
    b_service: RealBService,
    request: dict[str, Any],
    policy: np.ndarray,
    active_mask: np.ndarray,
    store_state: dict[str, Any],
) -> dict[str, Any]:
    result = b_service.evaluate_policy(request, policy, active_mask, {"store_state": store_state})
    result["policy_hash"] = _hash(policy)
    return result


def _score(result: dict[str, Any]) -> tuple[float, float, float, float]:
    """Exploration ordering; final approval still uses B's exact AND judgement."""
    metrics, judgement = result["metrics"], result["judgement"]
    profit = float(metrics["expected_profit"])
    waste = float(metrics["expected_waste_rate"])
    threshold = float(result["profit_threshold"])
    waste_target = float(result["waste_target"])
    profit_gap = (profit - threshold) / max(abs(threshold), 1.0)
    waste_gap = (waste_target - waste) / max(abs(waste_target), 1e-9)
    return (
        float(bool(judgement["threshold_pass"])),
        float(bool(waste <= waste_target + 1e-12)),
        float(min(profit_gap, waste_gap)),
        profit,
    )


def _top_coordinates(state: Any, active_mask: np.ndarray, limit: int) -> list[tuple[int, int]]:
    table = state.cell_table.copy()
    margin = np.maximum(table.regular_price.to_numpy(float) - table.unit_cost.to_numpy(float), 0.0)
    urgency = 4.0 - table.dte_index.to_numpy(float)
    score = table.available_qty.to_numpy(float) * (margin + 1.0) * urgency
    score[~active_mask.reshape(-1)] = -np.inf
    order = np.argsort(-score, kind="stable")
    return [(int(index // 4), int(index % 4)) for index in order[:limit] if np.isfinite(score[index])]


def coordinate_ascent_label(request: dict[str, Any], *, max_coordinate_cells: int = 4) -> dict[str, Any]:
    """Return one validated executable policy, or a documented non-label result."""
    state = build_runtime_state(request, ROOT)
    active_mask = state.active_mask
    caps = policy_caps(
        state.store_state["regular_price_vector"],
        state.store_state["unit_cost_vector"],
        state.store_state["product_max_discount_vector"],
    )
    b_service = RealBService(ROOT, discriminator_mode=DISCRIMINATOR_MODE)
    current = round_execution_policy(state.current_policy, active_mask, caps)
    executable_rule = build_executable_rule_policy(load_executable_rule_vector(ROOT), active_mask, caps)
    anchors = []
    for source, policy in (("CURRENT_POLICY", current), ("EXECUTABLE_RULE", executable_rule)):
        anchors.append((source, policy, _evaluate(b_service, request, policy, active_mask, state.store_state)))
    source, accepted, accepted_result = max(anchors, key=lambda item: _score(item[2]))
    evaluations = len(anchors)
    # Coordinate ascent is intentionally limited and fully executable at every
    # move.  There is no hidden DTE-monotonic projection: FINAL_RELEASE has no
    # such official constraint, so labels use exactly its current constraints.
    for i, j in _top_coordinates(state, active_mask, max_coordinate_cells):
        best_policy, best_result = accepted, accepted_result
        for delta in (-0.03, -0.02, -0.01, 0.01, 0.02, 0.03):
            candidate = accepted.copy()
            candidate[i, j] += np.float32(delta)
            candidate = round_execution_policy(candidate, active_mask, caps)
            if np.array_equal(candidate, accepted):
                continue
            result = _evaluate(b_service, request, candidate, active_mask, state.store_state)
            evaluations += 1
            if _score(result) > _score(best_result):
                best_policy, best_result = candidate, result
        accepted, accepted_result = best_policy, best_result
    finite = bool(np.isfinite(accepted).all())
    constraints_valid = bool(
        finite
        and np.all(accepted <= caps + 1e-7)
        and np.all(accepted[~active_mask] == 0.0)
    )
    passed = bool(accepted_result["judgement"]["threshold_pass"])
    return {
        "accepted": bool(passed and constraints_valid),
        "policy": accepted,
        "result": accepted_result,
        "state": state,
        "caps": caps,
        "active_mask": active_mask,
        "source": source if np.array_equal(accepted, anchors[0][1]) else "COORDINATE_ASCENT",
        "b_evaluation_count": int(b_service.evaluation_count),
        "candidate_evaluations": evaluations,
        "constraints_valid": constraints_valid,
    }


def _label_rows(group_id: str, request: dict[str, Any], outcome: dict[str, Any]) -> pd.DataFrame:
    state = outcome["state"]
    policy = np.asarray(outcome["policy"], np.float32)
    metadata = state.cell_table[["product_id", "product_index", "dte_bucket", "dte_index"]].copy()
    features = pd.DataFrame(state.lgbm_rows, columns=state.feature_names)
    frame = pd.concat([features, metadata], axis=1)
    frame["policy_group_id"] = group_id
    frame["store_id"] = str(request["decision"]["store_id"])
    frame["decision_timestamp"] = str(request["decision"]["decision_timestamp"])
    frame["target_discount_rate"] = policy.reshape(-1)
    frame["active_inventory_flag"] = outcome["active_mask"].reshape(-1).astype(int)
    frame["policy_hash"] = _hash(policy)
    frame["label_source"] = outcome["source"]
    return frame


def bootstrap_split(
    split: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    output_path: Path,
    *,
    target_groups: int,
    max_states: int,
) -> dict[str, Any]:
    if end >= TEST_START:
        raise ValueError("Bootstrap split must end before the official Test period")
    rows: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for index, (store_id, date, hour) in enumerate(_candidate_states(start, end, max_states), start=1):
        group_id = f"LGBM_{split}_{index:03d}"
        request = _request(store_id, date, hour, group_id)
        try:
            outcome = coordinate_ascent_label(request)
        except Exception as exc:
            # Store closure and malformed historical snapshots are not labels;
            # record them transparently and continue to another in-split state.
            summaries.append({
                "policy_group_id": group_id, "store_id": store_id,
                "decision_timestamp": request["decision"]["decision_timestamp"],
                "accepted": False, "status": "SKIPPED_STATE", "reason": str(exc),
            })
            continue
        result = outcome["result"]
        summary = {
            "policy_group_id": group_id,
            "store_id": store_id,
            "decision_timestamp": request["decision"]["decision_timestamp"],
            "accepted": outcome["accepted"],
            "label_source": outcome["source"],
            "policy_hash": _hash(outcome["policy"]),
            "threshold_pass": bool(result["judgement"]["threshold_pass"]),
            "expected_profit": float(result["metrics"]["expected_profit"]),
            "waste_rate": float(result["metrics"]["expected_waste_rate"]),
            "profit_threshold": float(result["profit_threshold"]),
            "waste_target": float(result["waste_target"]),
            "constraints_valid": outcome["constraints_valid"],
            "b_evaluation_count": outcome["b_evaluation_count"],
            "candidate_evaluations": outcome["candidate_evaluations"],
        }
        summaries.append(summary)
        if outcome["accepted"]:
            rows.append(_label_rows(group_id, request, outcome))
            if len(rows) >= target_groups:
                break
    if not rows:
        raise RuntimeError(f"No REAL_B threshold-passing labels were generated for {split}")
    labels = pd.concat(rows, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(output_path, index=False)
    report = {
        "split": split,
        "start": start.date().isoformat(), "end": end.date().isoformat(),
        "test_period_read_or_used": False,
        "label_contract": "REAL_B executable Rule discriminator: profit >= rule_profit + 0.03 * abs(rule_profit) AND waste_rate <= executable Rule waste target",
        "discriminator_mode": DISCRIMINATOR_MODE,
        "policy_groups": int(labels.policy_group_id.nunique()),
        "rows": int(len(labels)),
        "zero_label_ratio": float(np.mean(np.isclose(labels.target_discount_rate, 0.0))),
        "unique_target_1pct_count": int(np.unique(np.floor(labels.target_discount_rate * 100 + 0.5).astype(int)).size),
        "decision_timestamp_min": str(labels.decision_timestamp.min()),
        "decision_timestamp_max": str(labels.decision_timestamp.max()),
        "all_labels_within_caps": True,
        "all_inactive_labels_zero": True,
        "all_labels_finite": True,
        "all_labels_threshold_passed": True,
        "group_summaries": summaries,
    }
    output_path.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("train", "validation", "both"), default="both")
    parser.add_argument("--train-target-groups", type=int, default=16)
    parser.add_argument("--validation-target-groups", type=int, default=4)
    parser.add_argument("--max-train-states", type=int, default=72)
    parser.add_argument("--max-validation-states", type=int, default=36)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "model_a" / "bootstrap_labels")
    args = parser.parse_args()
    reports = {}
    if args.split in {"train", "both"}:
        reports["train"] = bootstrap_split(
            "TRAIN", TRAIN_START, TRAIN_END, args.output_dir / "train_labels.csv",
            target_groups=args.train_target_groups, max_states=args.max_train_states,
        )
    if args.split in {"validation", "both"}:
        reports["validation"] = bootstrap_split(
            "VALIDATION", VALID_START, VALID_END, args.output_dir / "validation_labels.csv",
            target_groups=args.validation_target_groups, max_states=args.max_validation_states,
        )
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
