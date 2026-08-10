"""Train the initial-policy LightGBM from official Train-only bootstrap labels.

Validation labels are passed only to LightGBM early stopping and reporting.
This command rejects Test-period rows before fitting so an accidental data leak
cannot turn into a trained runtime artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts.b_modes import SCOPE_ALIGNED_EXPERIMENTAL
from src.contracts.mappings import load_policy_mappings
from src.model_a.initial_policy_lightgbm import InitialPolicyLightGBM
from src.model_a.state_builder import NUMERIC_FEATURES


TRAIN_START = pd.Timestamp("2025-01-01")
TRAIN_END = pd.Timestamp("2025-09-30 23:59:59")
VALID_START = pd.Timestamp("2025-10-01")
VALID_END = pd.Timestamp("2025-11-15 23:59:59")
TEST_START = pd.Timestamp("2025-11-16")


def runtime_feature_names() -> list[str]:
    return list(NUMERIC_FEATURES) + [f"product_{i}" for i in range(38)] + [f"dte_{i}" for i in range(4)]


def _read_labels(path: Path, split_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{split_name} bootstrap labels are missing: {path}")
    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError(f"{split_name} bootstrap labels are empty")
    required = {
        "policy_group_id", "store_id", "decision_timestamp", "product_id", "dte_index",
        "target_discount_rate", "active_inventory_flag",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{split_name} labels are missing required metadata: {sorted(missing)}")
    return frame


def _timestamp(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame.decision_timestamp, utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)


def _validate_split(frame: pd.DataFrame, name: str, start: pd.Timestamp, end: pd.Timestamp) -> None:
    timestamps = _timestamp(frame)
    if timestamps.isna().any() or not timestamps.between(start, end).all():
        raise ValueError(f"{name} labels contain timestamps outside {start.date()}..{end.date()}")
    if (timestamps >= TEST_START).any():
        raise ValueError(f"{name} labels include the official Test period")
    target = pd.to_numeric(frame.target_discount_rate, errors="coerce").to_numpy(float)
    if not np.isfinite(target).all() or (target < -1e-8).any() or (target > 0.40 + 1e-8).any():
        raise ValueError(f"{name} labels contain invalid discount rates")
    inactive = frame.active_inventory_flag.astype(int).to_numpy() == 0
    if not np.allclose(target[inactive], 0.0, atol=1e-8):
        raise ValueError(f"{name} labels violate inactive == 0")


def _features(frame: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    # Do not use an exclusion list here.  Raw identifiers and metadata must
    # never silently become model inputs.
    missing = [name for name in feature_names if name not in frame.columns]
    if missing:
        raise ValueError(f"Bootstrap labels do not implement the runtime feature schema: {missing}")
    forbidden = {"product_id", "store_id", "request_id", "policy_group_id", "decision_timestamp", "target_discount_rate"}
    if forbidden & set(feature_names):
        raise AssertionError("raw metadata appeared in the LightGBM feature schema")
    selected = frame.loc[:, feature_names].apply(pd.to_numeric, errors="raise")
    values = selected.to_numpy(np.float32)
    if not np.isfinite(values).all():
        raise ValueError("LightGBM feature matrix contains NaN or Inf")
    return values


def train(train_path: Path, validation_path: Path, artifact_dir: Path) -> dict:
    feature_names = runtime_feature_names()
    train_frame = _read_labels(train_path, "Train")
    validation_frame = _read_labels(validation_path, "Validation")
    _validate_split(train_frame, "Train", TRAIN_START, TRAIN_END)
    _validate_split(validation_frame, "Validation", VALID_START, VALID_END)
    train_groups = train_frame.policy_group_id.astype(str).to_numpy()
    validation_groups = validation_frame.policy_group_id.astype(str).to_numpy()
    if np.unique(train_groups).size < 6:
        raise ValueError("At least six distinct Train historical policy groups are required")
    if np.unique(validation_groups).size < 2:
        raise ValueError("At least two distinct Validation historical policy groups are required")
    model = InitialPolicyLightGBM(feature_names, random_seed=42).fit(
        _features(train_frame, feature_names), train_frame.target_discount_rate.to_numpy(np.float32),
        groups=train_groups,
        validation_data=(
            _features(validation_frame, feature_names),
            validation_frame.target_discount_rate.to_numpy(np.float32),
        ),
        validation_groups=validation_groups,
    )
    mappings = load_policy_mappings(ROOT / "artifacts" / "b_runtime")
    status = {
        "validated_policy_group_count": int(np.unique(train_groups).size),
        "validated_training_row_count": int(len(train_frame)),
        "validation_policy_group_count": int(np.unique(validation_groups).size),
        "validation_row_count": int(len(validation_frame)),
        "train_label_period": [TRAIN_START.date().isoformat(), TRAIN_END.date().isoformat()],
        "validation_label_period": [VALID_START.date().isoformat(), VALID_END.date().isoformat()],
        "test_rows_used_for_training": 0,
        "test_rows_used_for_tuning": 0,
        "discriminator_mode": SCOPE_ALIGNED_EXPERIMENTAL,
        "label_source": "offline_coordinate_ascent_real_b_threshold_passing_executable_policy",
    }
    model.save(artifact_dir, status)
    (artifact_dir / "initial_policy_mapping.json").write_text(json.dumps({
        "product_ids": list(mappings.product_ids), "dte_labels": list(mappings.dte_labels),
        "discriminator_mode": SCOPE_ALIGNED_EXPERIMENTAL,
        "mapping_source": mappings.source,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_path = artifact_dir / "initial_policy_training_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics.update(status)
    metrics["training_attempted"] = True
    metrics["initial_policy_source"] = "LIGHTGBM"
    metrics["feature_schema_is_explicit"] = True
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    bootstrap_reports = {}
    for name, path in (("train", train_path), ("validation", validation_path)):
        report_path = path.with_suffix(".report.json")
        if report_path.exists():
            bootstrap_reports[name] = json.loads(report_path.read_text(encoding="utf-8"))
    (artifact_dir / "initial_policy_bootstrap_report.json").write_text(json.dumps({
        "model_status": "TRAINED", "training_attempted": True,
        "initial_policy_source": "LIGHTGBM",
        "official_split": {
            "train": [TRAIN_START.date().isoformat(), TRAIN_END.date().isoformat()],
            "validation": [VALID_START.date().isoformat(), VALID_END.date().isoformat()],
            "test": ["2025-11-16", "2025-12-31"],
        },
        "test_rows_used_for_training": 0, "test_rows_used_for_tuning": 0,
        "validated_policy_group_count": int(np.unique(train_groups).size),
        "validated_training_row_count": int(len(train_frame)),
        "validation_policy_group_count": int(np.unique(validation_groups).size),
        "validation_row_count": int(len(validation_frame)),
        "label_contract": "REAL_B executable Rule discriminator: profit >= rule_profit + 0.03 * abs(rule_profit) AND waste_rate <= executable Rule waste target",
        "bootstrap_reports": bootstrap_reports,
    }, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-labels", type=Path, default=ROOT / "artifacts" / "model_a" / "bootstrap_labels" / "train_labels.csv")
    parser.add_argument("--validation-labels", type=Path, default=ROOT / "artifacts" / "model_a" / "bootstrap_labels" / "validation_labels.csv")
    parser.add_argument("--artifact-dir", type=Path, default=ROOT / "artifacts" / "model_a")
    args = parser.parse_args()
    print(json.dumps(train(args.train_labels, args.validation_labels, args.artifact_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
