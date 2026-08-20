"""Build [38,4,F] state tensors from request cells or the project data snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.contracts.data_paths import resolve_data_dir
from src.contracts.mappings import POLICY_SHAPE, PolicyMappings
from src.contracts.schemas import ContractError, ErrorCode
from src.contracts.store_schedule import resolve_store_schedule

NUMERIC_FEATURES = (
    "available_qty", "freshness_score", "regular_price", "unit_cost",
    "current_stock_qty", "reserved_qty", "visitor_count", "previous_discount_rate",
    "product_max_discount_rate", "max_discount_rate_by_cost", "active_inventory_flag",
    "hour", "day_of_week_index", "weekend_flag", "holiday_flag", "season_index",
    "event_index", "store_floating_idx", "store_resident_pop", "store_order_error_sigma",
    "product_shelf_life_days", "product_baseline_waste_rate", "product_margin_rate",
    "sold_out_flag", "dte_index_numeric",
)


@dataclass
class RuntimePolicyState:
    cell_table: pd.DataFrame
    state_tensor: np.ndarray
    lgbm_rows: np.ndarray
    feature_names: tuple[str, ...]
    active_mask: np.ndarray
    current_policy: np.ndarray
    store_state: dict[str, Any]


class RuntimeStateBuilder:
    def __init__(
        self,
        project_root: str | Path,
        mappings: PolicyMappings,
        data_dir: str | Path | None = None,
    ) -> None:
        self.root = Path(project_root)
        self.data_dir = resolve_data_dir(self.root, data_dir)
        self.mappings = mappings
        self.product = pd.read_csv(self.data_dir / "product.csv").set_index("product_id").loc[list(mappings.product_ids)].reset_index()
        self.store = pd.read_csv(self.data_dir / "store.csv").set_index("store_id")
        self.calendar = pd.read_csv(self.data_dir / "calendar.csv", parse_dates=["date"]).set_index("date")
        self.store_calendar = pd.read_csv(self.data_dir / "store_calendar.csv", parse_dates=["date"])
        self.visitor_profile = pd.read_csv(self.data_dir / "store_visitor_profile.csv")

    def build(self, request: dict[str, Any]) -> RuntimePolicyState:
        decision = request["decision"]
        timestamp = pd.Timestamp(decision["decision_timestamp"])
        cells = list((request.get("state") or {}).get("cells") or [])
        try:
            table = self._empty_table(str(decision["store_id"]), timestamp)
            table = self._from_request_cells(table, cells) if cells else self._from_project_snapshot(table, str(decision["store_id"]), timestamp)
            requested_source = str((request.get("state") or {}).get("source") or "REQUEST_CELLS")
            state_source = requested_source if cells else "PROJECT_DATA_SNAPSHOT"
            return self._finalize(table, str(decision["store_id"]), timestamp, state_source)
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(ErrorCode.STATE_TENSOR_BUILD_ERROR, str(exc), "STATE_TENSOR_BUILD") from exc

    def _empty_table(self, store_id: str, timestamp: pd.Timestamp) -> pd.DataFrame:
        local_timestamp = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
        date = local_timestamp.normalize()
        if store_id not in self.store.index:
            raise ValueError(f"Unknown store_id: {store_id}")
        schedule = resolve_store_schedule(self.root, store_id, local_timestamp, data_dir=self.data_dir)
        if date not in self.calendar.index:
            raise ValueError(f"calendar.csv has no row for {date.date()}")
        store = self.store.loc[store_id]
        calendar = self.calendar.loc[date]
        dow_values = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
        visitor_rows = self.visitor_profile[
            (self.visitor_profile.area_type.astype(str) == str(store.area_type))
            & (self.visitor_profile.close_hour.astype(int) == int(schedule["close_hour_exclusive"]))
            & (self.visitor_profile.day_type.astype(str) == str(calendar.day_type))
            & (self.visitor_profile.start_hour.astype(int) <= int(local_timestamp.hour))
            & (self.visitor_profile.end_hour.astype(int) > int(local_timestamp.hour))
        ]
        visitor_ratio = float(visitor_rows.visitor_ratio.iloc[0]) if not visitor_rows.empty else 0.0
        visitor_index = float(store.floating_idx) * visitor_ratio * float(calendar.season_index) * float(calendar.event_index)
        rows = []
        for i, pid in enumerate(self.mappings.product_ids):
            product = self.product.iloc[i]
            price, cost = float(product.base_price), float(product.base_cost)
            for j, label in enumerate(self.mappings.dte_labels):
                rows.append({
                    "store_id": store_id, "product_id": pid, "product_index": i,
                    "date": timestamp.date().isoformat(), "hour": int(timestamp.hour),
                    "decision_timestamp": timestamp.isoformat(), "dte_bucket": label, "dte_index": j,
                    "available_qty": 0.0, "freshness_score": 0.6,
                    "regular_price": price, "unit_cost": cost,
                    "current_stock_qty": 0.0, "reserved_qty": 0.0,
                    "visitor_count": visitor_index, "previous_discount_rate": 0.0,
                    "product_max_discount_rate": float(product.max_discount_rate),
                    "max_discount_rate_by_cost": float(np.clip(1.0 - cost / max(price, 1e-9), 0.0, 1.0)),
                    "active_inventory_flag": 0,
                    "hour": int(local_timestamp.hour),
                    "day_of_week_index": float(dow_values.get(str(calendar.day_of_week), 0)),
                    "weekend_flag": float(calendar.is_weekend), "holiday_flag": float(calendar.is_holiday),
                    "season_index": float(calendar.season_index), "event_index": float(calendar.event_index),
                    "store_floating_idx": float(store.floating_idx), "store_resident_pop": float(store.resident_pop),
                    "store_order_error_sigma": float(store.order_error_sigma),
                    "product_shelf_life_days": float(product.shelf_life_days),
                    "product_baseline_waste_rate": float(product.baseline_waste_rate),
                    "product_margin_rate": float(product.margin_rate), "sold_out_flag": 1.0,
                    "dte_index_numeric": float(j),
                })
        return pd.DataFrame(rows)

    def _from_request_cells(self, table: pd.DataFrame, cells: list[dict[str, Any]]) -> pd.DataFrame:
        expected_store_id = str(table["store_id"].iloc[0])
        for cell in cells:
            if cell.get("store_id") is not None and str(cell["store_id"]) != expected_store_id:
                raise ContractError(
                    ErrorCode.INPUT_SCHEMA_ERROR,
                    f"State cell store_id={cell['store_id']} does not match decision.store_id={expected_store_id}",
                    "STATE_TENSOR_BUILD",
                )
            pid = str(cell.get("product_id", ""))
            if pid not in self.mappings.product_to_index:
                raise ContractError(ErrorCode.PRODUCT_MAPPING_ERROR, f"Unknown product_id: {pid}", "STATE_TENSOR_BUILD")
            i = self.mappings.product_to_index[pid]
            j = int(cell.get("dte_index", -1))
            if j not in range(4):
                raise ContractError(ErrorCode.DTE_MAPPING_ERROR, f"Invalid dte_index for {pid}: {j}", "STATE_TENSOR_BUILD")
            if "product_index" in cell and int(cell["product_index"]) != i:
                raise ContractError(ErrorCode.PRODUCT_MAPPING_ERROR, f"product_index mismatch for {pid}", "STATE_TENSOR_BUILD")
            row = i * 4 + j
            for name in NUMERIC_FEATURES:
                if name in cell:
                    table.at[row, name] = float(cell[name])
            extra = cell.get("features") or {}
            for name in ("freshness_score", "visitor_count"):
                if name in extra and name not in cell:
                    table.at[row, name] = float(extra[name])
            qty = max(float(table.at[row, "available_qty"]), 0.0)
            requested_active = bool(cell.get("active_inventory_flag", qty > 0))
            table.at[row, "active_inventory_flag"] = int(requested_active and qty > 0)
        return table

    def _from_project_snapshot(self, table: pd.DataFrame, store_id: str, timestamp: pd.Timestamp) -> pd.DataFrame:
        # Project CSV timestamps are timezone-naive local business timestamps.
        local_timestamp = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
        inv = pd.read_csv(self.data_dir / "inventory.csv", parse_dates=["current_date"])
        current = inv[(inv.store_id.astype(str) == store_id) & (inv.current_date == local_timestamp.normalize())].copy()
        if current.empty:
            raise ValueError(f"No inventory snapshot for {store_id} at {timestamp.date()}")
        def bucket(value):
            value = int(value)
            return 0 if value <= 0 else (3 if value >= 3 else value)
        current["product_index"] = current.product_id.map(self.mappings.product_to_index)
        current["dte_index"] = current.days_to_expiry.map(bucket)
        for (i, j), group in current.groupby(["product_index", "dte_index"]):
            row = int(i) * 4 + int(j)
            qty = float(group.available_qty.clip(lower=0).sum())
            weights = group.available_qty.clip(lower=0).to_numpy(float)
            freshness = float(np.average(group.freshness_score, weights=weights)) if weights.sum() > 0 else 0.6
            discount = group.discount_rate.astype(float).to_numpy()
            discount = np.where(discount > 1, discount / 100.0, discount)
            previous = float(np.average(discount, weights=weights)) if weights.sum() > 0 else 0.0
            table.at[row, "available_qty"] = qty
            table.at[row, "current_stock_qty"] = float(group.current_stock_qty.clip(lower=0).sum())
            table.at[row, "reserved_qty"] = float(group.reserved_qty.clip(lower=0).sum())
            table.at[row, "freshness_score"] = freshness
            table.at[row, "previous_discount_rate"] = previous
            table.at[row, "active_inventory_flag"] = int(qty > 0)
            table.at[row, "sold_out_flag"] = float(qty <= 0)
        return table

    def _finalize(self, table: pd.DataFrame, store_id: str, timestamp: pd.Timestamp, state_source: str) -> RuntimePolicyState:
        for column in NUMERIC_FEATURES:
            values = pd.to_numeric(table[column], errors="coerce")
            if values.isna().any() or not np.isfinite(values.to_numpy()).all():
                raise ValueError(f"State feature contains invalid values: {column}")
            table[column] = values.astype(float)
        active = table.active_inventory_flag.astype(bool).to_numpy().reshape(POLICY_SHAPE)
        table.loc[~table.active_inventory_flag.astype(bool), "previous_discount_rate"] = 0.0
        current_policy = table.previous_discount_rate.to_numpy(float).reshape(POLICY_SHAPE)
        numeric = table.loc[:, NUMERIC_FEATURES].to_numpy(np.float32)
        mean, std = numeric.mean(0), numeric.std(0)
        std = np.where(std < 1e-8, 1.0, std)
        numeric = (numeric - mean) / std
        product_oh = np.eye(38, dtype=np.float32)[table.product_index.to_numpy(int)]
        dte_oh = np.eye(4, dtype=np.float32)[table.dte_index.to_numpy(int)]
        flat = np.concatenate([numeric, product_oh, dte_oh], axis=1).astype(np.float32)
        feature_names = tuple(NUMERIC_FEATURES) + tuple(f"product_{i}" for i in range(38)) + tuple(f"dte_{i}" for i in range(4))
        local_timestamp = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
        schedule = resolve_store_schedule(self.root, store_id, local_timestamp, data_dir=self.data_dir)
        store_state = {
            "store_id": store_id, "date": local_timestamp.normalize(), "hour": int(local_timestamp.hour),
            "decision_timestamp": local_timestamp,
            "open_hour": int(schedule["open_hour"]),
            "close_hour": int(schedule["evaluation_end_hour"]),
            "close_hour_exclusive": int(schedule["close_hour_exclusive"]),
            "store_schedule_source": str(schedule["schedule_source"]),
            "availability_matrix": table.available_qty.to_numpy(float).reshape(POLICY_SHAPE),
            "freshness_matrix": table.freshness_score.to_numpy(float).reshape(POLICY_SHAPE),
            "regular_price_vector": self.product.base_price.to_numpy(float),
            "unit_cost_vector": self.product.base_cost.to_numpy(float),
            "weight_vector": self.product.standard_weight_kg.to_numpy(float),
            "product_max_discount_vector": self.product.max_discount_rate.to_numpy(float),
            "max_discount_by_cost_vector": 1.0 - self.product.base_cost.to_numpy(float) / self.product.base_price.to_numpy(float),
            "baseline_policy_source": state_source,
        }
        return RuntimePolicyState(table, flat.reshape(38, 4, -1), flat, feature_names, active, current_policy.astype(np.float32), store_state)
