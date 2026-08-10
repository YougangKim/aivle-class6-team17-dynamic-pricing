"""Cell-level Initial Policy LightGBM owned by Model A."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupShuffleSplit

from src.contracts.mappings import POLICY_SHAPE
from src.model_a.constraints import project_policy_numpy


class LightGBMNotTrainedError(RuntimeError):
    pass


class InitialPolicyLightGBM:
    """Predict 152 cell discounts; targets must be completed final policies."""

    def __init__(self, feature_names: list[str] | tuple[str, ...], random_seed: int = 42) -> None:
        self.feature_names = tuple(feature_names)
        self.random_seed = int(random_seed)
        self.model = None
        self.status = "NOT_TRAINED"
        self.metrics: dict[str, Any] = {
            "model_status": "NOT_TRAINED",
            "reason": "No completed A-B final_discount_rate training dataset is available.",
            "mae": None, "rmse": None, "wape": None, "exact_match_1pct": None,
            "within_1pct_accuracy": None, "within_3pct_accuracy": None,
            "train_sample_count": None, "validation_sample_count": None,
            "train_policy_group_count": None, "validation_policy_group_count": None,
            "model_artifact_created": False,
        }

    @property
    def is_trained(self) -> bool:
        return self.status == "TRAINED" and self.model is not None

    def fit(self, X, y, sample_weight=None, groups=None, validation_fraction=0.2):
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("lightgbm is required to train InitialPolicyLightGBM") from exc
        features = np.asarray(X, dtype=np.float32)
        target = np.asarray(y, dtype=np.float32).reshape(-1)
        if features.ndim != 2 or features.shape[1] != len(self.feature_names) or len(features) != len(target):
            raise ValueError("X/y shape does not match the initial policy feature schema")
        if len(features) < 10:
            raise ValueError("At least 10 labeled cell rows are required")
        rounded_unique = np.unique(np.floor(target * 100 + 0.5).astype(int))
        if rounded_unique.size < 2 or float(np.std(target)) < 1e-8:
            raise ValueError(
                "InitialPolicyLightGBM labels are constant after 1%p rounding; "
                "a zero-error constant predictor is not a valid trained policy model"
            )
        if groups is None:
            raise ValueError("groups are required so one store-time policy cannot leak across train/validation")
        group_values = np.asarray(groups)
        splitter = GroupShuffleSplit(n_splits=1, test_size=float(validation_fraction), random_state=self.random_seed)
        train_idx, val_idx = next(splitter.split(features, target, group_values))
        weights = None if sample_weight is None else np.asarray(sample_weight, dtype=np.float32)
        feature_frame = pd.DataFrame(features, columns=self.feature_names)
        started = time.perf_counter()
        self.model = lgb.LGBMRegressor(
            objective="regression_l1", n_estimators=300, learning_rate=0.03,
            num_leaves=31, min_child_samples=20, subsample=0.9, colsample_bytree=0.9,
            random_state=self.random_seed, n_jobs=-1, verbosity=-1,
        )
        self.model.fit(
            feature_frame.iloc[train_idx], target[train_idx],
            sample_weight=None if weights is None else weights[train_idx],
            eval_set=[(feature_frame.iloc[val_idx], target[val_idx])], callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        prediction = np.clip(self.model.predict(feature_frame.iloc[val_idx]), 0.0, 0.40)
        error = prediction - target[val_idx]
        rounded_pred = np.floor(prediction * 100 + 0.5).astype(int)
        rounded_true = np.floor(target[val_idx] * 100 + 0.5).astype(int)
        self.status = "TRAINED"
        self.metrics = {
            "model_status": "TRAINED",
            "mae": float(mean_absolute_error(target[val_idx], prediction)),
            "rmse": float(np.sqrt(mean_squared_error(target[val_idx], prediction))),
            "wape": float(np.abs(error).sum() / max(np.abs(target[val_idx]).sum(), 1e-9)),
            "exact_match_1pct": float(np.mean(rounded_pred == rounded_true)),
            "within_1pct_accuracy": float(np.mean(np.abs(error) <= 0.01 + 1e-12)),
            "within_3pct_accuracy": float(np.mean(np.abs(error) <= 0.03 + 1e-12)),
            "train_sample_count": int(len(train_idx)), "validation_sample_count": int(len(val_idx)),
            "train_policy_group_count": int(np.unique(group_values[train_idx]).size),
            "validation_policy_group_count": int(np.unique(group_values[val_idx]).size),
            "train_policy_groups": [str(value) for value in np.unique(group_values[train_idx]).tolist()],
            "validation_policy_groups": [str(value) for value in np.unique(group_values[val_idx]).tolist()],
            "training_seconds": float(time.perf_counter() - started), "feature_names": list(self.feature_names),
            "target_unique_1pct_count": int(rounded_unique.size),
            "target_min": float(target.min()), "target_max": float(target.max()),
            "model_version": "initial-policy-lgbm-v1", "model_artifact_created": True,
        }
        return self

    def predict_policy(self, state_rows, active_mask, caps):
        if not self.is_trained:
            raise LightGBMNotTrainedError(self.metrics["reason"])
        features = np.asarray(state_rows, dtype=np.float32)
        if features.shape != (152, len(self.feature_names)):
            raise ValueError(f"LightGBM rows must have shape (152, {len(self.feature_names)})")
        prediction = np.asarray(self.model.predict(pd.DataFrame(features, columns=self.feature_names)), dtype=np.float32).reshape(POLICY_SHAPE)
        return project_policy_numpy(prediction, active_mask, caps)

    def save(self, artifact_dir: str | Path) -> None:
        if not self.is_trained:
            raise LightGBMNotTrainedError("Refusing to create a fake LightGBM model artifact")
        out = Path(artifact_dir); out.mkdir(parents=True, exist_ok=True)
        self.model.booster_.save_model(str(out / "initial_policy_lightgbm.txt"))
        (out / "initial_policy_feature_schema.json").write_text(json.dumps({"feature_names": list(self.feature_names), "input_shape": [152, len(self.feature_names)]}, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "initial_policy_training_metrics.json").write_text(json.dumps(self.metrics, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
        (out / "initial_policy_artifact_status.json").write_text(
            json.dumps({"status": "VALID", "model_status": "TRAINED"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load_or_not_trained(cls, artifact_dir: str | Path, feature_names, random_seed=42):
        instance = cls(feature_names, random_seed)
        artifact_root = Path(artifact_dir)
        model_path = artifact_root / "initial_policy_lightgbm.txt"
        status_path = artifact_root / "initial_policy_artifact_status.json"
        if status_path.exists():
            artifact_status = json.loads(status_path.read_text(encoding="utf-8"))
            if artifact_status.get("status") != "VALID" or artifact_status.get("model_status") != "TRAINED":
                instance.metrics.update(artifact_status)
                instance.metrics["model_status"] = "NOT_TRAINED"
                return instance
        if not model_path.exists():
            return instance
        if not status_path.exists():
            instance.metrics["reason"] = (
                "Legacy/pre-reconstruction LightGBM artifact is disabled because its status file is missing"
            )
            return instance
        try:
            import lightgbm as lgb
            schema_path = artifact_root / "initial_policy_feature_schema.json"
            if not schema_path.exists():
                raise RuntimeError("initial policy feature schema is missing")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            if tuple(schema.get("feature_names", ())) != tuple(feature_names):
                raise RuntimeError("initial policy feature schema does not match the runtime state tensor")
            booster = lgb.Booster(model_file=str(model_path))
            if booster.num_feature() != len(feature_names):
                raise RuntimeError("LightGBM feature count does not match the runtime state tensor")
            instance.model = _BoosterPredictor(booster)
            instance.status = "TRAINED"
            metrics_path = artifact_root / "initial_policy_training_metrics.json"
            if metrics_path.exists():
                instance.metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            return instance
        except Exception as exc:
            raise RuntimeError(f"LightGBM artifact load failed: {exc}") from exc


class _BoosterPredictor:
    def __init__(self, booster): self.booster_ = booster
    def predict(self, X): return self.booster_.predict(X)
