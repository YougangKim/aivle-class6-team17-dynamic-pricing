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

    def fit(
        self,
        X,
        y,
        sample_weight=None,
        groups=None,
        validation_fraction=0.2,
        *,
        validation_data=None,
        validation_groups=None,
    ):
        """Fit from cell rows, optionally with a calendar-separated validation set.

        ``validation_data`` is deliberately explicit.  Offline bootstrap uses
        the project Train/Validation date split and must never create a random
        within-dataset split that could hide an accidental calendar leak.
        """
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("lightgbm is required to train InitialPolicyLightGBM") from exc
        features = np.asarray(X, dtype=np.float32)
        target = np.asarray(y, dtype=np.float32).reshape(-1)
        if features.ndim != 2 or features.shape[1] != len(self.feature_names) or len(features) != len(target):
            raise ValueError("X/y shape does not match the initial policy feature schema")
        if not np.isfinite(features).all() or not np.isfinite(target).all():
            raise ValueError("InitialPolicyLightGBM features and labels must be finite numeric values")
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
        if len(group_values) != len(features):
            raise ValueError("groups must have one value per training row")
        weights = None if sample_weight is None else np.asarray(sample_weight, dtype=np.float32)
        if weights is not None and len(weights) != len(features):
            raise ValueError("sample_weight must have one value per training row")
        feature_frame = pd.DataFrame(features, columns=self.feature_names)
        if validation_data is None:
            splitter = GroupShuffleSplit(n_splits=1, test_size=float(validation_fraction), random_state=self.random_seed)
            train_idx, val_idx = next(splitter.split(features, target, group_values))
            train_frame, train_target = feature_frame.iloc[train_idx], target[train_idx]
            validation_frame, validation_target = feature_frame.iloc[val_idx], target[val_idx]
            train_groups, held_out_groups = group_values[train_idx], group_values[val_idx]
            train_weights = None if weights is None else weights[train_idx]
        else:
            if not isinstance(validation_data, tuple) or len(validation_data) != 2:
                raise ValueError("validation_data must be an (X, y) pair")
            validation_features = np.asarray(validation_data[0], dtype=np.float32)
            validation_target = np.asarray(validation_data[1], dtype=np.float32).reshape(-1)
            if validation_features.ndim != 2 or validation_features.shape[1] != len(self.feature_names):
                raise ValueError("validation X does not match the initial policy feature schema")
            if len(validation_features) != len(validation_target) or len(validation_features) < 1:
                raise ValueError("validation X/y shape is invalid")
            if not np.isfinite(validation_features).all() or not np.isfinite(validation_target).all():
                raise ValueError("validation features and labels must be finite numeric values")
            if validation_groups is None:
                raise ValueError("validation_groups are required with explicit validation_data")
            held_out_groups = np.asarray(validation_groups)
            if len(held_out_groups) != len(validation_features):
                raise ValueError("validation_groups must have one value per validation row")
            train_frame, train_target = feature_frame, target
            validation_frame = pd.DataFrame(validation_features, columns=self.feature_names)
            train_groups, train_weights = group_values, weights
        started = time.perf_counter()
        self.model = lgb.LGBMRegressor(
            objective="regression_l1", n_estimators=300, learning_rate=0.03,
            num_leaves=31, min_child_samples=20, subsample=0.9, colsample_bytree=0.9,
            random_state=self.random_seed, n_jobs=-1, verbosity=-1,
        )
        self.model.fit(
            train_frame, train_target,
            sample_weight=train_weights,
            eval_set=[(validation_frame, validation_target)], callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        prediction = np.clip(self.model.predict(validation_frame), 0.0, 0.40)
        error = prediction - validation_target
        rounded_pred = np.floor(prediction * 100 + 0.5).astype(int)
        rounded_true = np.floor(validation_target * 100 + 0.5).astype(int)
        self.status = "TRAINED"
        self.metrics = {
            "model_status": "TRAINED",
            "mae": float(mean_absolute_error(validation_target, prediction)),
            "rmse": float(np.sqrt(mean_squared_error(validation_target, prediction))),
            "wape": float(np.abs(error).sum() / max(np.abs(validation_target).sum(), 1e-9)),
            "exact_match_1pct": float(np.mean(rounded_pred == rounded_true)),
            "within_1pct_accuracy": float(np.mean(np.abs(error) <= 0.01 + 1e-12)),
            "within_3pct_accuracy": float(np.mean(np.abs(error) <= 0.03 + 1e-12)),
            "train_sample_count": int(len(train_target)), "validation_sample_count": int(len(validation_target)),
            "train_policy_group_count": int(np.unique(train_groups).size),
            "validation_policy_group_count": int(np.unique(held_out_groups).size),
            "train_policy_groups": [str(value) for value in np.unique(train_groups).tolist()],
            "validation_policy_groups": [str(value) for value in np.unique(held_out_groups).tolist()],
            "training_seconds": float(time.perf_counter() - started), "feature_names": list(self.feature_names),
            "target_unique_1pct_count": int(rounded_unique.size),
            "target_min": float(target.min()), "target_max": float(target.max()),
            "target_discount_distribution": _distribution(validation_target),
            "prediction_discount_distribution": _distribution(prediction),
            "zero_label_ratio": float(np.mean(np.isclose(target, 0.0))),
            "unique_predicted_1pct_count": int(np.unique(rounded_pred).size),
            "validation_target_mean_by_dte": _mean_by_dte(validation_target),
            "validation_prediction_mean_by_dte": _mean_by_dte(prediction),
            "model_version": "initial-policy-lgbm-v2", "model_artifact_created": True,
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

    def save(self, artifact_dir: str | Path, artifact_status: dict[str, Any] | None = None) -> None:
        if not self.is_trained:
            raise LightGBMNotTrainedError("Refusing to create a fake LightGBM model artifact")
        out = Path(artifact_dir); out.mkdir(parents=True, exist_ok=True)
        (out / "initial_policy_lightgbm.txt").write_text(
            self.model.booster_.model_to_string(),
            encoding="utf-8",
        )
        (out / "initial_policy_feature_schema.json").write_text(json.dumps({
            "feature_names": list(self.feature_names), "input_shape": [152, len(self.feature_names)],
            "feature_contract": "numeric_state_features_plus_fixed_product_and_dte_one_hot",
            "metadata_columns_excluded": ["product_id", "store_id", "request_id", "policy_group_id", "decision_timestamp", "target_discount_rate"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "initial_policy_training_metrics.json").write_text(json.dumps(self.metrics, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
        status = {
            "status": "VALID", "model_status": "TRAINED", "training_attempted": True,
            "initial_policy_source": "LIGHTGBM", "fallback_enabled": True,
            **(artifact_status or {}),
        }
        (out / "initial_policy_artifact_status.json").write_text(
            json.dumps(status, ensure_ascii=False, allow_nan=False, indent=2),
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
                "LightGBM artifact is disabled because its status file is missing"
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
            booster = lgb.Booster(model_str=model_path.read_text(encoding="utf-8"))
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


def _distribution(values: np.ndarray) -> dict[str, float | int]:
    data = np.asarray(values, dtype=np.float64)
    return {
        "count": int(data.size), "min": float(data.min()), "max": float(data.max()),
        "mean": float(data.mean()), "median": float(np.median(data)),
        "zero_ratio": float(np.mean(np.isclose(data, 0.0))),
        "unique_1pct_count": int(np.unique(np.floor(data * 100 + 0.5).astype(int)).size),
    }


def _mean_by_dte(values: np.ndarray) -> dict[str, float]:
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    # Cell rows are always emitted product-major, with four DTE rows/product.
    return {str(dte): float(data[dte::4].mean()) for dte in range(4)}
