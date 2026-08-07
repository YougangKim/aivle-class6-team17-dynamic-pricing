"""Leakage-safe historical intraday inventory reconstruction for Model A.

Receipt rows are used only to subtract sales that occurred strictly before a
historical decision timestamp.  Receipt-derived sales, lags, and rolling values
are never exposed as model features.  Raw source CSV files are read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


RECONSTRUCTION_METHOD = "PREVIOUS_CLOSE_PLUS_INBOUND_MINUS_RECEIPT_SALES"
INBOUND_TIME_ASSUMPTION = "STORE_OPEN"
WASTE_TIME_ASSUMPTION = "STORE_CLOSE"

INVENTORY_COLUMNS = (
    "inventory_id", "store_id", "product_id", "lot_id", "current_date",
    "days_to_expiry", "inbound_qty", "daily_sold_qty", "daily_waste_qty",
    "current_stock_qty", "reserved_qty", "freshness_score", "unit_cost",
    "unit_price", "discount_rate",
)
RECEIPT_COLUMNS = ("inventory_id", "sale_datetime", "quantity")


@dataclass(frozen=True)
class IntradayInventoryArtifacts:
    snapshot_path: Path
    quality_path: Path
    metadata_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame, required: Iterable[str], source: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{source} is missing required columns: {missing}")


def reconstruct_intraday_inventory(
    inventory: pd.DataFrame,
    receipts: pd.DataFrame,
    store_calendar: pd.DataFrame,
    decision_hours: Iterable[int],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return lot-level historical snapshots and reconstruction QA metadata.

    Opening stock is reconstructed from the previous daily close plus today's
    inbound quantity.  For a decision at ``t``, only receipts with
    ``sale_datetime < t`` are subtracted.  Daily waste has no timestamp in the
    provided data, so it is applied at store close and never subtracted from a
    pre-close snapshot.
    """

    _require_columns(inventory, INVENTORY_COLUMNS, "inventory.csv")
    _require_columns(receipts, RECEIPT_COLUMNS, "receipt.csv")
    _require_columns(
        store_calendar, ("date", "store_id", "is_open", "open_hour", "close_hour"),
        "store_calendar.csv",
    )
    hours = tuple(sorted({int(value) for value in decision_hours}))
    if not hours or any(value < 0 or value > 23 for value in hours):
        raise ValueError("decision_hours must contain one or more integers in 0..23")

    inv = inventory.loc[:, INVENTORY_COLUMNS].copy()
    inv["current_date"] = pd.to_datetime(inv["current_date"], errors="raise").dt.normalize()
    inv = inv.sort_values(
        ["store_id", "product_id", "lot_id", "current_date", "inventory_id"]
    ).reset_index(drop=True)
    duplicated = inv.duplicated(["inventory_id"], keep=False)
    if duplicated.any():
        examples = inv.loc[duplicated, "inventory_id"].astype(str).head(5).tolist()
        raise ValueError(f"inventory_id must be unique; duplicate examples: {examples}")

    group_keys = ["store_id", "product_id", "lot_id"]
    grouped = inv.groupby(group_keys, sort=False, observed=True)
    previous_date = grouped["current_date"].shift(1)
    previous_close = grouped["current_stock_qty"].shift(1).fillna(0.0)
    is_consecutive = (inv["current_date"] - previous_date).dt.days.eq(1)
    previous_close = previous_close.where(is_consecutive, 0.0)
    inv["previous_close_qty"] = previous_close.astype(float)
    inv["opening_stock_qty"] = (
        inv["previous_close_qty"] + pd.to_numeric(inv["inbound_qty"], errors="raise")
    ).astype(float)

    close_reconstructed = (
        inv["opening_stock_qty"]
        - pd.to_numeric(inv["daily_sold_qty"], errors="raise")
        - pd.to_numeric(inv["daily_waste_qty"], errors="raise")
    )
    close_gap = close_reconstructed - pd.to_numeric(inv["current_stock_qty"], errors="raise")

    rec = receipts.loc[:, RECEIPT_COLUMNS].copy()
    rec["sale_datetime"] = pd.to_datetime(rec["sale_datetime"], errors="raise")
    rec["quantity"] = pd.to_numeric(rec["quantity"], errors="raise").astype(float)
    if (rec["quantity"] < 0).any():
        raise ValueError("receipt.csv contains negative quantity")
    known_inventory_ids = set(inv["inventory_id"].astype(str))
    receipt_match = rec["inventory_id"].astype(str).isin(known_inventory_ids)
    if not receipt_match.all():
        examples = rec.loc[~receipt_match, "inventory_id"].astype(str).head(5).tolist()
        raise ValueError(f"receipt inventory_id does not exist in inventory.csv: {examples}")
    rec["sale_second"] = (
        rec["sale_datetime"].dt.hour * 3600
        + rec["sale_datetime"].dt.minute * 60
        + rec["sale_datetime"].dt.second
    )

    calendar = store_calendar.loc[:, ["date", "store_id", "is_open", "open_hour", "close_hour"]].copy()
    calendar["date"] = pd.to_datetime(calendar["date"], errors="raise").dt.normalize()
    calendar["store_id"] = calendar["store_id"].astype(str)
    if calendar.duplicated(["date", "store_id"]).any():
        raise ValueError("store_calendar.csv has duplicate (date, store_id) rows")

    frames: list[pd.DataFrame] = []
    cumulative_exceeds_daily = 0
    negative_before_clip = 0
    for hour in hours:
        sales_before = (
            rec.loc[rec["sale_second"] < hour * 3600]
            .groupby("inventory_id", observed=True)["quantity"]
            .sum()
        )
        part = inv.copy()
        part["hour"] = hour
        part["decision_timestamp"] = part["current_date"] + pd.to_timedelta(hour, unit="h")
        part["cumulative_sales_before_decision"] = (
            part["inventory_id"].map(sales_before).fillna(0.0).astype(float)
        )
        cumulative_exceeds_daily += int(
            (part["cumulative_sales_before_decision"] > part["daily_sold_qty"].astype(float) + 1e-9).sum()
        )
        part = part.merge(
            calendar,
            left_on=["current_date", "store_id"],
            right_on=["date", "store_id"],
            how="left",
            validate="many_to_one",
        )
        part = part[
            part["is_open"].fillna(0).astype(int).eq(1)
            & (hour >= part["open_hour"].astype(float))
            & (hour < part["close_hour"].astype(float))
        ].copy()
        # All configured decision points are pre-close. Waste is therefore not
        # known yet and is not subtracted from the historical state.
        part["known_waste_before_decision"] = 0.0
        estimated = (
            part["opening_stock_qty"]
            - part["cumulative_sales_before_decision"]
            - part["known_waste_before_decision"]
        )
        negative_before_clip += int((estimated < -1e-9).sum())
        part["estimated_current_stock_qty"] = estimated.clip(lower=0.0)
        part["estimated_available_qty"] = (
            part["estimated_current_stock_qty"]
            - pd.to_numeric(part["reserved_qty"], errors="raise").clip(lower=0.0)
        ).clip(lower=0.0)
        part["active_inventory_flag"] = part["estimated_available_qty"].gt(0).astype(np.int8)
        part["dte_index"] = np.where(
            part["days_to_expiry"].astype(int) <= 0,
            0,
            np.where(part["days_to_expiry"].astype(int) >= 3, 3, part["days_to_expiry"].astype(int)),
        ).astype(np.int8)
        part["previous_discount_rate"] = pd.to_numeric(part["discount_rate"], errors="raise")
        part["previous_discount_rate"] = np.where(
            part["previous_discount_rate"] > 1.0,
            part["previous_discount_rate"] / 100.0,
            part["previous_discount_rate"],
        )
        frames.append(part)

    if not frames:
        raise RuntimeError("No open-store intraday snapshots were reconstructed")
    snapshots = pd.concat(frames, ignore_index=True)
    output_columns = [
        "inventory_id", "store_id", "product_id", "lot_id", "current_date",
        "decision_timestamp", "hour", "days_to_expiry", "dte_index",
        "opening_stock_qty", "cumulative_sales_before_decision",
        "known_waste_before_decision", "estimated_current_stock_qty",
        "estimated_available_qty", "reserved_qty", "freshness_score", "unit_cost",
        "unit_price", "previous_discount_rate", "active_inventory_flag",
    ]
    snapshots = snapshots.loc[:, output_columns].sort_values(
        ["current_date", "store_id", "hour", "product_id", "dte_index", "lot_id"]
    ).reset_index(drop=True)
    if not np.isfinite(
        snapshots.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    ).all():
        raise ValueError("Reconstructed snapshot contains NaN or infinite numeric values")

    quality = {
        "reconstruction_method": RECONSTRUCTION_METHOD,
        "inbound_time_assumption": INBOUND_TIME_ASSUMPTION,
        "waste_time_assumption": WASTE_TIME_ASSUMPTION,
        "inventory_is_estimated": True,
        "receipt_usage": "INVENTORY_RECONSTRUCTION_ONLY",
        "decision_hours": list(hours),
        "inventory_row_count": int(len(inv)),
        "receipt_row_count": int(len(rec)),
        "receipt_inventory_match_rate": float(receipt_match.mean()),
        "close_balance_pass_count": int(np.isclose(close_gap, 0.0, atol=1e-9).sum()),
        "close_balance_row_count": int(len(close_gap)),
        "close_balance_match_rate": float(np.isclose(close_gap, 0.0, atol=1e-9).mean()),
        "close_balance_max_abs_error": float(np.abs(close_gap).max()),
        "cumulative_sales_exceeds_daily_sold_count": int(cumulative_exceeds_daily),
        "negative_estimated_stock_before_clip_count": int(negative_before_clip),
        "snapshot_row_count": int(len(snapshots)),
        "state_group_count": int(
            snapshots[["store_id", "current_date", "hour"]].drop_duplicates().shape[0]
        ),
        "feature_leakage_guard": "receipt quantities are not emitted as LightGBM/surrogate features",
    }
    return snapshots, quality


def build_and_save_intraday_inventory(
    project_root: str | Path,
    decision_hours: Iterable[int] = (12, 15, 18, 21),
    output_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object], IntradayInventoryArtifacts]:
    root = Path(project_root)
    data = root / "data"
    output = Path(output_dir) if output_dir is not None else data / "derived"
    output.mkdir(parents=True, exist_ok=True)
    inventory_path = data / "inventory.csv"
    receipt_path = data / "receipt.csv"
    calendar_path = data / "store_calendar.csv"
    inventory = pd.read_csv(inventory_path, usecols=list(INVENTORY_COLUMNS))
    receipts = pd.read_csv(receipt_path, usecols=list(RECEIPT_COLUMNS))
    store_calendar = pd.read_csv(calendar_path)
    snapshots, quality = reconstruct_intraday_inventory(
        inventory, receipts, store_calendar, decision_hours
    )
    source_hashes = {
        "inventory.csv": _sha256(inventory_path),
        "receipt.csv": _sha256(receipt_path),
        "store_calendar.csv": _sha256(calendar_path),
    }
    quality["source_sha256"] = source_hashes
    artifacts = IntradayInventoryArtifacts(
        snapshot_path=output / "estimated_intraday_inventory.parquet",
        quality_path=output / "inventory_reconstruction_quality.csv",
        metadata_path=output / "inventory_reconstruction_metadata.json",
    )
    snapshots.to_parquet(artifacts.snapshot_path, index=False)
    pd.DataFrame(
        [{"metric": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}
         for key, value in quality.items()]
    ).to_csv(artifacts.quality_path, index=False, encoding="utf-8-sig")
    artifacts.metadata_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snapshots, quality, artifacts


def snapshot_to_request_cells(
    snapshots: pd.DataFrame,
    store_id: str,
    decision_timestamp: str | pd.Timestamp,
    product_ids: Iterable[str],
    dte_labels: Iterable[str],
) -> list[dict[str, object]]:
    """Aggregate lot snapshots into the product×DTE cells accepted by A and B."""

    timestamp = pd.Timestamp(decision_timestamp)
    local = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
    products = tuple(str(value) for value in product_ids)
    labels = tuple(str(value) for value in dte_labels)
    selected = snapshots[
        snapshots["store_id"].astype(str).eq(str(store_id))
        & pd.to_datetime(snapshots["decision_timestamp"]).eq(local)
    ].copy()
    if selected.empty:
        raise ValueError(f"No reconstructed snapshot for {store_id} at {local}")
    product_to_index = {value: index for index, value in enumerate(products)}
    selected["product_index"] = selected["product_id"].astype(str).map(product_to_index)
    if selected["product_index"].isna().any():
        unknown = selected.loc[selected["product_index"].isna(), "product_id"].astype(str).unique().tolist()
        raise ValueError(f"Reconstructed inventory has products outside B mapping: {unknown[:5]}")

    cells: list[dict[str, object]] = []
    for (product_index, dte_index), group in selected.groupby(
        ["product_index", "dte_index"], sort=False, observed=True
    ):
        qty = float(group["estimated_available_qty"].sum())
        weights = group["estimated_available_qty"].to_numpy(float)
        if weights.sum() > 0:
            freshness = float(np.average(group["freshness_score"].to_numpy(float), weights=weights))
            previous_discount = float(np.average(group["previous_discount_rate"].to_numpy(float), weights=weights))
        else:
            freshness = float(group["freshness_score"].mean())
            previous_discount = 0.0
        i, j = int(product_index), int(dte_index)
        cells.append({
            "product_id": products[i],
            "product_index": i,
            "dte_index": j,
            "dte_bucket": labels[j],
            "available_qty": qty,
            "current_stock_qty": float(group["estimated_current_stock_qty"].sum()),
            "reserved_qty": float(group["reserved_qty"].sum()),
            "regular_price": float(group["unit_price"].iloc[0]),
            "unit_cost": float(group["unit_cost"].iloc[0]),
            "freshness_score": freshness,
            "previous_discount_rate": previous_discount,
            "active_inventory_flag": bool(qty > 0),
        })
    return cells
