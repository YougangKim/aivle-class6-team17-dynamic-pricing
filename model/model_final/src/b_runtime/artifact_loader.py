"""Load and validate the complete B runtime artifact bundle."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .schemas import DTE_LABELS, POLICY_SHAPE, PRODUCT_COUNT


class BArtifactError(RuntimeError):
    """Raised when a real-B dependency is missing or inconsistent."""


@dataclass(frozen=True)
class BArtifactBundle:
    artifact_dir: Path
    data_dir: Path
    product_ids: tuple[str, ...]
    dte_labels: tuple[str, ...]
    arrays: dict[str, np.ndarray]
    params: dict[str, Any]
    discriminator_params: dict[str, Any]
    discriminator_params_path: Path
    product_mapping: dict[str, Any]
    product_mapping_path: Path
    dte_mapping: dict[str, Any]
    dte_mapping_path: Path
    tables: dict[str, pd.DataFrame]

    @property
    def policy_shape(self) -> tuple[int, int]:
        return POLICY_SHAPE

    @property
    def product_index(self) -> dict[str, int]:
        return {pid: i for i, pid in enumerate(self.product_ids)}


def _read_csv(path: Path, parse_dates: tuple[str, ...] = ()) -> pd.DataFrame:
    if not path.exists():
        raise BArtifactError(f"Required B source table is missing: {path}")
    frame = pd.read_csv(path)
    frame.columns = [str(c).lstrip("\ufeff") for c in frame.columns]
    for column in parse_dates:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="raise")
    return frame


def load_b_artifacts(
    artifact_dir: str | Path,
    data_dir: str | Path,
) -> BArtifactBundle:
    artifact_path = Path(artifact_dir).resolve()
    data_path = Path(data_dir).resolve()
    params_path = artifact_path / "params_customer_sim.json"
    discriminator_path = artifact_path / "params_discriminator.json"
    arrays_path = artifact_path / "sim_arrays.npz"
    product_mapping_path = artifact_path / "product_index_mapping.json"
    dte_mapping_path = artifact_path / "dte_index_mapping.json"
    required_paths = (
        params_path,
        discriminator_path,
        arrays_path,
        product_mapping_path,
        dte_mapping_path,
    )
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise BArtifactError("Real B initialization failed; missing required artifacts: " + ", ".join(missing))

    raw = np.load(arrays_path, allow_pickle=True)
    required_arrays = ("PS", "FS", "BSF", "LAM", "NSEG", "PREF_J", "TRIP_BUD", "CAT_IDX", "BASE_PRICE", "BASE_COST", "PID")
    absent = [key for key in required_arrays if key not in raw.files]
    if absent:
        raise BArtifactError(f"sim_arrays.npz is missing keys: {absent}")
    arrays = {key: np.asarray(raw[key]) for key in required_arrays}
    product_ids = tuple(str(v) for v in arrays["PID"].tolist())
    if len(product_ids) != PRODUCT_COUNT:
        raise BArtifactError(f"B product count must be {PRODUCT_COUNT}; got {len(product_ids)}")
    if arrays["PREF_J"].shape[1] != PRODUCT_COUNT:
        raise BArtifactError(f"PREF_J shape is inconsistent: {arrays['PREF_J'].shape}")

    with product_mapping_path.open(encoding="utf-8") as handle:
        product_mapping = json.load(handle)
    mapped_product_ids = tuple(
        str(product_mapping["index_to_product"][str(index)])
        for index in range(PRODUCT_COUNT)
    )
    if mapped_product_ids != product_ids:
        raise BArtifactError("product_index_mapping.json differs from sim_arrays.npz/PID order")

    with dte_mapping_path.open(encoding="utf-8") as handle:
        dte_mapping = json.load(handle)
    mapped_dte_labels = tuple(
        str(dte_mapping["index_to_dte"][str(index)])
        for index in range(POLICY_SHAPE[1])
    )
    if mapped_dte_labels != DTE_LABELS:
        raise BArtifactError("dte_index_mapping.json differs from the runtime DTE order")

    with params_path.open(encoding="utf-8") as handle:
        saved = json.load(handle)
    required_params = ("alpha", "c", "beta_disc", "beta_fresh", "beta_bud", "gamma", "visit_scale", "EQ", "shared")
    absent_params = [key for key in required_params if key not in saved]
    if absent_params:
        raise BArtifactError(f"params_customer_sim.json is missing keys: {absent_params}")
    params: dict[str, Any] = dict(saved)
    params["alpha"] = np.asarray(saved["alpha"], dtype=np.float64)
    shared = saved["shared"]
    shared_required = ("beta_disc_ops", "rule_vec", "disposal_fee_per_kg", "shrinkage_rate_daily")
    missing_shared = [key for key in shared_required if key not in shared]
    if missing_shared:
        raise BArtifactError(f"params_customer_sim.json shared block is missing keys: {missing_shared}")
    if len(shared["rule_vec"]) != POLICY_SHAPE[1]:
        raise BArtifactError("params_customer_sim.json shared.rule_vec must contain four DTE values")

    with discriminator_path.open(encoding="utf-8") as handle:
        discriminator_saved = json.load(handle)
    discriminator_required = ("alpha", "c", "beta_disc", "beta_fresh", "beta_bud", "gamma", "rule_vec")
    missing_discriminator = [key for key in discriminator_required if key not in discriminator_saved]
    if missing_discriminator:
        raise BArtifactError(
            "Official params_discriminator.json is missing keys: " + repr(missing_discriminator)
        )
    if len(discriminator_saved["alpha"]) != PRODUCT_COUNT:
        raise BArtifactError("Official params_discriminator.json alpha must contain 38 product values")

    tables = {
        "product": _read_csv(data_path / "product.csv"),
        "store": _read_csv(data_path / "store.csv"),
        "calendar": _read_csv(data_path / "calendar.csv", ("date",)),
        "store_calendar": _read_csv(data_path / "store_calendar.csv", ("date",)),
        "store_visitor_profile": _read_csv(data_path / "store_visitor_profile.csv"),
        "inventory": _read_csv(data_path / "inventory.csv", ("current_date", "expiry_date")),
    }
    prod_ids = set(tables["product"]["product_id"].astype(str))
    missing_products = [pid for pid in product_ids if pid not in prod_ids]
    if missing_products:
        raise BArtifactError(f"product.csv is missing B products: {missing_products}")
    aligned = tables["product"].set_index("product_id").loc[list(product_ids)].reset_index()
    if tuple(aligned["product_id"].astype(str)) != product_ids:
        raise BArtifactError("Product mapping could not be aligned to B PID order")
    tables["product_aligned"] = aligned

    return BArtifactBundle(
        artifact_dir=artifact_path,
        data_dir=data_path,
        product_ids=product_ids,
        dte_labels=DTE_LABELS,
        arrays=arrays,
        params=params,
        discriminator_params=dict(discriminator_saved),
        discriminator_params_path=discriminator_path,
        product_mapping=dict(product_mapping),
        product_mapping_path=product_mapping_path,
        dte_mapping=dict(dte_mapping),
        dte_mapping_path=dte_mapping_path,
        tables=tables,
    )
