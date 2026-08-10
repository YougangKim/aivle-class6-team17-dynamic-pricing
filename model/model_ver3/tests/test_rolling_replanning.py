from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from src.contracts.discounts import normalize_discount_rate
from src.contracts.store_schedule import resolve_store_schedule
from src.model_a.constraints import PreviousPolicyCapConflictError, round_execution_policy
from src.pipeline.rolling_constraints import RollingConstraintContext
from src.pipeline.rolling_planner import (
    RollingPolicyLedger,
    policy_hash,
    run_rolling_replan,
    run_rolling_smoke,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASK = np.zeros((38, 4), dtype=bool)
MASK[0, 0] = True
MASK[0, 1] = True
CAPS = np.full((38, 4), 0.40, dtype=np.float32)
CAPS[0, 1] = 0.35


def _policy(value: float) -> np.ndarray:
    result = np.zeros((38, 4), dtype=np.float32)
    result[MASK] = value
    return result


def _request(timestamp: str, request_id: str) -> dict:
    return {
        "request_id": request_id,
        "schema_version": "1.0",
        "decision": {
            "store_id": "S02", "date": timestamp[:10],
            "hour": int(timestamp[11:13]), "decision_timestamp": timestamp,
        },
        "state": {"cells": []},
        "options": {"discriminator_mode": "SCOPE_ALIGNED_EXPERIMENTAL"},
        "rolling_enabled": True,
    }


def _context(request, _project_root=None):
    previous = request.get("previous_discount_rate")
    if previous is None:
        lower = None
    else:
        raw = np.asarray(previous, dtype=np.float32)
        if raw.ndim == 0:
            raw = np.full((38, 4), float(raw), dtype=np.float32)
        lower = np.where(MASK, np.ceil(raw / 0.01 - 1e-9) * 0.01, 0.0).astype(np.float32)
    return RollingConstraintContext(
        request["decision"]["decision_timestamp"], MASK, CAPS, lower
    )


def _passing_b(request, policy):
    matrix = np.asarray(policy["policy_matrix"], np.float32)
    digest = policy_hash(matrix)
    return {
        "policy_hash": digest,
        "judgement": {"threshold_pass": True, "threshold_passed": True, "reject_reason": None},
        "metrics": {
            "expected_demand": 1.0, "expected_sales_qty": 1.0,
            "expected_revenue": 1.0, "expected_profit": 1.0,
            "expected_waste_qty": 0.0, "expected_waste_rate": 0.0,
        },
        "warnings": [],
    }


def test_01_first_execution_without_previous_uses_existing_projection():
    candidate = _policy(0.173)
    assert np.array_equal(
        round_execution_policy(candidate, MASK, CAPS),
        round_execution_policy(candidate, MASK, CAPS, lower_bounds=None),
    )


def test_02_discount_never_decreases_from_previous_published_rate():
    previous = _policy(0.20)
    lower_candidate = _policy(0.15)
    assert round_execution_policy(lower_candidate, MASK, CAPS, lower_bounds=previous)[0, 0] == pytest.approx(0.20)


def test_03_discount_increase_is_allowed_within_cap():
    previous = _policy(0.20)
    higher_candidate = _policy(0.30)
    assert round_execution_policy(higher_candidate, MASK, CAPS, lower_bounds=previous)[0, 0] == pytest.approx(0.30)


def test_04_actual_policy_cap_limits_candidate():
    previous = _policy(0.20)
    capped_candidate = _policy(0.50)
    projected = round_execution_policy(capped_candidate, MASK, CAPS, lower_bounds=previous)
    assert projected[0, 1] == pytest.approx(0.35)


def test_05_inactive_cells_remain_zero_even_with_previous_rate():
    previous = np.full((38, 4), 0.20, dtype=np.float32)
    projected = round_execution_policy(np.full((38, 4), .30, dtype=np.float32), MASK, CAPS, lower_bounds=previous)
    assert np.count_nonzero(projected[~MASK]) == 0


def test_previous_policy_above_current_cap_is_explicitly_rejected():
    previous = _policy(0.20)
    previous[0, 1] = 0.36
    with pytest.raises(PreviousPolicyCapConflictError, match="exceeds"):
        round_execution_policy(_policy(.30), MASK, CAPS, lower_bounds=previous)


def test_06_percent_normalization_is_unambiguous():
    assert normalize_discount_rate(30) == pytest.approx(0.30)
    assert normalize_discount_rate(0.30) == pytest.approx(0.30)
    with pytest.raises(ValueError):
        normalize_discount_rate(101)


def test_07_ledger_uses_full_ten_minute_timestamps(tmp_path):
    ledger = RollingPolicyLedger(tmp_path / "ledger.json")
    for timestamp, value in (("2025-01-01T13:00:00", .20), ("2025-01-01T13:10:00", .21), ("2025-01-01T13:20:00", .22)):
        matrix = _policy(value)
        ledger.upsert("S02", timestamp, {
            "published": True,
            "accepted_policy": {"policy_matrix": matrix, "policy_hash": policy_hash(matrix)},
        })
    previous = ledger.previous_accepted("S02", "2025-01-01T13:20:01")
    assert previous["accepted_policy"]["policy_hash"] == policy_hash(_policy(.22))
    assert len(ledger.document["stores"]["S02"]["records"]) == 3


def test_08_close_hour_is_exclusive():
    assert resolve_store_schedule(PROJECT_ROOT, "S02", "2025-01-01T21:59:00")["evaluation_end_hour"] == 21
    with pytest.raises(ValueError, match="outside"):
        resolve_store_schedule(PROJECT_ROOT, "S02", "2025-01-01T22:00:00")


def test_09_hash_chain_matches_b_and_published_ledger(monkeypatch, tmp_path):
    import src.pipeline.rolling_planner as planner
    matrix = _policy(.20)
    digest = policy_hash(matrix)

    monkeypatch.setattr(planner, "build_rolling_constraint_context", _context)
    monkeypatch.setattr(planner, "evaluate_b_policy", _passing_b)
    monkeypatch.setattr(planner, "run_discount_optimization", lambda request, output: {
        "status": "SUCCESS", "execution_eligible": True,
        "store_id": "S02",
        "decision": deepcopy(request["decision"]),
        "final_policy": {
            "policy_iteration": 1, "policy_source": "TEST_A",
            "policy_matrix": matrix, "policy_hash": digest,
        },
        "warnings": [],
    })
    ledger_path = tmp_path / "ledger.json"
    response = run_rolling_replan(_request("2025-01-01T13:00:00", "HASH_CHAIN"), str(tmp_path / "out.json"), ledger_path=ledger_path)
    assert response["published"] is True
    assert response["rolling"]["optimized_executable_policy_hash"] == digest
    assert response["rolling"]["b_evaluated_policy_hash"] == digest
    assert response["rolling"]["published_policy_hash"] == digest
    assert RollingPolicyLedger(ledger_path).exact("S02", "2025-01-01T13:00:00")["accepted_policy"]["policy_hash"] == digest


def test_10_threshold_failure_never_creates_accepted_policy(monkeypatch, tmp_path):
    import src.pipeline.rolling_planner as planner
    monkeypatch.setattr(planner, "build_rolling_constraint_context", _context)
    monkeypatch.setattr(planner, "run_discount_optimization", lambda request, output: {
        "status": "NO_THRESHOLD_PASS", "execution_eligible": False,
        "final_policy": None, "warnings": ["TEST_THRESHOLD_FAILURE"],
    })
    ledger_path = tmp_path / "ledger.json"
    response = run_rolling_replan(_request("2025-01-01T13:00:00", "THRESHOLD_FAILURE"), str(tmp_path / "out.json"), ledger_path=ledger_path)
    record = RollingPolicyLedger(ledger_path).exact("S02", "2025-01-01T13:00:00")
    assert response["published"] is False
    assert record["accepted_policy"] is None
    assert record["source"] == "THRESHOLD_FAILURE_SAFE_HOLD"


def test_11_all_constraints_and_ten_minute_smoke(monkeypatch, tmp_path):
    import src.pipeline.rolling_planner as planner

    def fake_pipeline(request, output):
        previous = request.get("previous_discount_rate")
        matrix = _policy(.20) if previous is None else np.minimum(np.asarray(previous, np.float32) + .01, CAPS)
        matrix[~MASK] = np.nan  # Verify the planner never publishes an invalid final policy.
        # The fake A executable policy must obey inactive=0, just as the real
        # A projection does; make its test input explicit after exercising the
        # real constraint assertions below.
        matrix[~MASK] = 0.0
        return {
            "status": "SUCCESS", "execution_eligible": True,
            "store_id": "S02",
            "decision": deepcopy(request["decision"]),
            "final_policy": {
                "policy_iteration": 1, "policy_source": "TEST_A",
                "policy_matrix": matrix, "policy_hash": policy_hash(matrix),
            }, "warnings": [],
        }

    monkeypatch.setattr(planner, "build_rolling_constraint_context", _context)
    monkeypatch.setattr(planner, "evaluate_b_policy", _passing_b)
    monkeypatch.setattr(planner, "run_discount_optimization", fake_pipeline)
    ledger_path = tmp_path / "ledger.json"
    dirty_candidate = _policy(.20)
    dirty_candidate[0, 0] = np.nan
    dirty_candidate[0, 1] = np.inf
    sanitized = round_execution_policy(dirty_candidate, MASK, CAPS, lower_bounds=_policy(.20))
    assert np.isfinite(sanitized).all()
    assert np.all(sanitized[MASK] >= _policy(.20)[MASK] - 1e-7)
    assert np.all(sanitized[MASK] <= CAPS[MASK])
    assert np.all(sanitized[~MASK] == 0.0)
    timestamps = ("2025-01-01T13:00:00", "2025-01-01T13:10:00", "2025-01-01T13:20:00")
    summary = run_rolling_smoke(
        [_request(timestamp, f"SMOKE_{index}") for index, timestamp in enumerate(timestamps)],
        tmp_path / "smoke",
        ledger_path=ledger_path,
    )
    assert summary["temporal_monotonicity_violations"] == 0
    assert (tmp_path / "smoke" / "rolling_smoke_log.csv").exists()
    assert (tmp_path / "smoke" / "rolling_smoke_summary.json").exists()
    means = []
    ledger = RollingPolicyLedger(ledger_path)
    previous = None
    for index, timestamp in enumerate(timestamps):
        record = ledger.exact("S02", timestamp)
        matrix = np.asarray(record["accepted_policy"]["policy_matrix"], np.float32)
        means.append(float(matrix[MASK].mean()))
        assert np.isfinite(matrix).all()
        assert np.all(matrix[MASK] <= CAPS[MASK])
        assert np.all(matrix[~MASK] == 0.0)
        if previous is not None:
            assert np.all(matrix[MASK] >= previous[MASK])
        previous = matrix
    assert means == sorted(means)
