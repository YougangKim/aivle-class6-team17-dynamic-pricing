"""Versioned B-simulation replay with one sample per full policy decision."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from src.contracts.mappings import POLICY_SHAPE
from src.contracts.b_modes import (
    REAL_B_MODEL_VERSION,
    validate_backend_version,
)

TARGET_KEYS = ("expected_demand", "expected_sales_qty", "expected_revenue", "expected_profit", "expected_waste_qty")
CURRENT_B_MODEL_VERSION = REAL_B_MODEL_VERSION


@dataclass
class ReplaySample:
    sample_id: str
    request_id: str
    store_id: str
    decision_timestamp: str
    iteration: int
    state_tensor: np.ndarray
    policy_matrix: np.ndarray
    active_mask: np.ndarray
    targets: np.ndarray
    threshold_pass: bool
    reject_reason: str
    policy_source: str
    b_backend: str
    b_model_version: str
    discriminator_version: str
    threshold_version: str
    artifact_source: str


class RealPolicyReplayBuffer:
    def __init__(self, minimum_size=6, capacity=2000, seed=42) -> None:
        self.minimum_size = int(minimum_size); self.capacity = int(capacity)
        self.rng = np.random.default_rng(seed); self.samples: list[ReplaySample] = []

    def __len__(self): return len(self.samples)
    @property
    def can_train(self): return len(self.samples) >= self.minimum_size

    def add(self, request, state_tensor, policy_matrix, active_mask, b_result, iteration, policy_source, b_model_version=None):
        backend = str(b_result.get("b_backend"))
        result_version = str(b_result.get("b_model_version"))
        expected_version = result_version if b_model_version is None else str(b_model_version)
        if result_version != expected_version or not validate_backend_version(backend, result_version):
            raise ValueError("Replay sample B backend/model version pair is not supported")
        metrics = b_result.get("metrics") or {}
        missing = [key for key in TARGET_KEYS if metrics.get(key) is None]
        if missing:
            raise ValueError(f"REAL_B result is missing surrogate targets: {missing}")
        state = np.asarray(state_tensor, np.float32)
        policy = np.asarray(policy_matrix, np.float32)
        mask = np.asarray(active_mask, bool)
        if state.ndim != 3 or state.shape[:2] != POLICY_SHAPE or policy.shape != POLICY_SHAPE or mask.shape != POLICY_SHAPE:
            raise ValueError("Replay shapes must be state=[38,4,F], policy/mask=[38,4]")
        target = np.asarray([metrics[key] for key in TARGET_KEYS], np.float32)
        if not np.isfinite(state).all() or not np.isfinite(policy).all() or not np.isfinite(target).all():
            raise ValueError("Replay sample contains NaN or Infinity")
        judgement = b_result["judgement"]
        sample = ReplaySample(
            f"sample_{uuid4().hex[:16]}", str(request["request_id"]), str(request["decision"]["store_id"]),
            str(request["decision"]["decision_timestamp"]), int(iteration), state.copy(), policy.copy(), mask.copy(), target,
            bool(judgement["threshold_pass"]), str(judgement.get("reject_reason") or ""), str(policy_source),
            backend, result_version, str(b_result.get("discriminator_version") or ""),
            str(b_result.get("threshold_version") or ""), str(b_result.get("artifact_source") or ""),
        )
        self.samples.append(sample)
        if len(self.samples) > self.capacity: self.samples.pop(0)
        return sample.sample_id

    def arrays(self):
        if not self.samples: raise RuntimeError("Replay buffer is empty")
        return np.stack([s.state_tensor for s in self.samples]), np.stack([s.policy_matrix for s in self.samples]), np.stack([s.active_mask for s in self.samples]), np.stack([s.targets for s in self.samples])

    def save(self, artifact_dir: str | Path):
        out = Path(artifact_dir); out.mkdir(parents=True, exist_ok=True)
        states, policies, masks, targets = self.arrays()
        np.savez_compressed(out / "replay_tensors.npz", sample_ids=np.asarray([s.sample_id for s in self.samples]), state_tensors=states, policy_matrices=policies, active_masks=masks.astype(np.uint8), targets=targets)
        rows = [{
            "sample_id": s.sample_id, "request_id": s.request_id, "store_id": s.store_id,
            "decision_timestamp": s.decision_timestamp, "iteration": s.iteration, "b_backend": s.b_backend,
            "policy_schema": "38x4-v1", "product_mapping_version": "sim-arrays-pid-v1",
            "dte_mapping_version": "code2-dte-v1", "b_model_version": s.b_model_version,
            "discriminator_version": s.discriminator_version,
            "threshold_version": s.threshold_version, "artifact_source": s.artifact_source,
            "threshold_pass": s.threshold_pass, "reject_reason": s.reject_reason, "policy_source": s.policy_source,
            **{key: float(value) for key, value in zip(TARGET_KEYS, s.targets)},
        } for s in self.samples]
        pd.DataFrame(rows).to_parquet(out / "replay_metadata.parquet", index=False)
        return out

    @classmethod
    def load(cls, artifact_dir: str | Path, minimum_size=6, capacity=2000, seed=42):
        root = Path(artifact_dir)
        metadata = pd.read_parquet(root / "replay_metadata.parquet")
        required = {"sample_id", "request_id", "store_id", "decision_timestamp", "iteration", "b_backend", "policy_schema", "product_mapping_version", "dte_mapping_version", "b_model_version", "discriminator_version", "threshold_version", "artifact_source", "threshold_pass", "reject_reason", "policy_source", *TARGET_KEYS}
        missing = required - set(metadata.columns)
        if missing:
            raise ValueError(f"Replay metadata is missing columns: {sorted(missing)}")
        pairs = set(zip(metadata.b_backend.astype(str), metadata.b_model_version.astype(str)))
        if not pairs or any(not validate_backend_version(backend, version) for backend, version in pairs):
            raise ValueError("Replay metadata contains an unsupported B backend/model version pair")
        if len(pairs) != 1:
            raise ValueError("One replay buffer cannot mix discriminator backends or B model versions")
        if set(metadata.policy_schema.astype(str)) != {"38x4-v1"}:
            raise ValueError("Replay policy schema is incompatible")
        if set(metadata.product_mapping_version.astype(str)) != {"sim-arrays-pid-v1"} or set(metadata.dte_mapping_version.astype(str)) != {"code2-dte-v1"}:
            raise ValueError("Replay mapping version is incompatible")
        tensors = np.load(root / "replay_tensors.npz", allow_pickle=False)
        sample_ids = tensors["sample_ids"].astype(str)
        if metadata.sample_id.astype(str).tolist() != sample_ids.tolist():
            raise ValueError("Replay metadata and tensors are not joined in the same sample order")
        states, policies, masks, targets = (tensors["state_tensors"], tensors["policy_matrices"], tensors["active_masks"].astype(bool), tensors["targets"])
        if len(metadata) != len(states) or policies.shape[1:] != POLICY_SHAPE or masks.shape[1:] != POLICY_SHAPE or targets.shape[1:] != (len(TARGET_KEYS),):
            raise ValueError("Replay tensor shapes are incompatible")
        loaded = cls(minimum_size=minimum_size, capacity=capacity, seed=seed)
        for index, row in metadata.reset_index(drop=True).iterrows():
            loaded.samples.append(ReplaySample(
                str(row.sample_id), str(row.request_id), str(row.store_id), str(row.decision_timestamp), int(row.iteration),
                np.asarray(states[index], np.float32), np.asarray(policies[index], np.float32), np.asarray(masks[index], bool),
                np.asarray(targets[index], np.float32), bool(row.threshold_pass), "" if pd.isna(row.reject_reason) else str(row.reject_reason),
                str(row.policy_source), str(row.b_backend), str(row.b_model_version),
                str(row.discriminator_version), str(row.threshold_version), str(row.artifact_source),
            ))
        return loaded
