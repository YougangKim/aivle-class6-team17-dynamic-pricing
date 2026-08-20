"""Matrix customer simulator preserving the delivered Code1/Code2 equations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from .artifact_loader import BArtifactBundle
from .schemas import POLICY_SHAPE, validate_policy_matrix

SLOTS = ("morning", "lunch", "afternoon", "evening", "closing")
DOW_FACTOR = {"MON": .88, "TUE": .88, "WED": .90, "THU": .93, "FRI": 1.08, "SAT": 1.32, "SUN": 1.25}


class MatrixCustomerSimulator:
    """Expected-value simulator; the full 38x4 policy is evaluated jointly."""

    def __init__(self, bundle: BArtifactBundle, parameter_overrides: dict[str, float] | None = None) -> None:
        self.bundle = bundle
        self.arr = bundle.arrays
        self.p: dict[str, Any] = deepcopy(bundle.params)
        calibrated = bundle.discriminator_params
        self.p.update({key: calibrated[key] for key in ("c", "beta_disc", "beta_fresh", "beta_bud", "gamma")})
        self.p["alpha"] = np.asarray(calibrated["alpha"], dtype=np.float64).copy()
        self.runtime_beta_disc_ops = float(bundle.params["shared"]["beta_disc_ops"])
        if not np.isclose(float(self.p["beta_disc"]), self.runtime_beta_disc_ops):
            raise ValueError(
                "Official params_discriminator beta_disc does not match "
                "params_customer_sim.shared.beta_disc_ops"
            )
        if parameter_overrides:
            allowed = {"beta_disc", "beta_fresh", "beta_bud", "gamma", "c", "visit_scale", "EQ"}
            unknown = set(parameter_overrides) - allowed
            if unknown:
                raise ValueError(f"Unsupported B sensitivity parameters: {sorted(unknown)}")
            self.p.update({k: float(v) for k, v in parameter_overrides.items()})

        category_index = self.arr["CAT_IDX"].astype(int)
        if self.p["alpha"].shape[0] != POLICY_SHAPE[0]:
            self.p["alpha"] = self.p["alpha"][category_index].copy()
        self.category_index = np.arange(POLICY_SHAPE[0], dtype=int)
        self.store_weight, self.slot_ratio, self.slot_hours, self.open_map, self.day_info = self._build_lookups()
        self._visitor_cache: dict[tuple[str, pd.Timestamp, int], np.ndarray | None] = {}

    def _build_lookups(self):
        store = self.bundle.tables["store"]
        cal = self.bundle.tables["calendar"]
        scal = self.bundle.tables["store_calendar"]
        profile = self.bundle.tables["store_visitor_profile"]
        weights = store.set_index("store_id")["floating_idx"].astype(float)
        weights = weights / weights.sum()
        day = cal[["date", "day_of_week", "day_type", "season_index", "event_index"]].copy()
        day["f_day"] = day["day_of_week"].map(DOW_FACTOR) * day["event_index"].fillna(1.0) * day["season_index"].fillna(1.0)
        day_info = {pd.Timestamp(r.date): (r.day_type, float(r.f_day)) for r in day.itertuples()}
        open_map = {(pd.Timestamp(k[0]), str(k[1])): int(v) for k, v in scal.set_index(["date", "store_id"])["is_open"].to_dict().items()}
        vp = profile.merge(store[["store_id", "area_type", "close_hour"]], on=["area_type", "close_hour"])
        slot_ratio = {(str(r.store_id), str(r.day_type), str(r.time_slot)): float(r.visitor_ratio) for r in vp.itertuples()}
        slot_hours: dict[str, dict[str, list[int]]] = {}
        for r in vp.drop_duplicates(["store_id", "time_slot"]).itertuples():
            slot_hours.setdefault(str(r.store_id), {})[str(r.time_slot)] = list(range(int(r.start_hour), int(r.end_hour)))
        return weights, slot_ratio, slot_hours, open_map, day_info

    def visitors(self, store_id: str, date: pd.Timestamp | str, hour: int) -> np.ndarray | None:
        dt = pd.Timestamp(date).normalize()
        key = (str(store_id), dt, int(hour))
        if key in self._visitor_cache:
            return self._visitor_cache[key]
        if self.open_map.get((dt, str(store_id)), 0) == 0 or dt not in self.day_info:
            self._visitor_cache[key] = None
            return None
        day_type, f_day = self.day_info[dt]
        slots = self.slot_hours.get(str(store_id), {})
        slot = next((name for name, hours in slots.items() if int(hour) in hours), None)
        if slot is None:
            self._visitor_cache[key] = None
            return None
        ratios = np.asarray([self.slot_ratio.get((str(store_id), day_type, name), 0.0) for name in SLOTS])
        if ratios.sum() <= 0:
            self._visitor_cache[key] = None
            return None
        ratio = self.slot_ratio.get((str(store_id), day_type, slot), 0.0) / ratios.sum()
        value = (
            self.arr["LAM"] / 365.0 * f_day * float(self.store_weight[str(store_id)])
            * float(self.p["visit_scale"]) * self.arr["NSEG"] * ratio / max(len(slots[slot]), 1)
        )
        self._visitor_cache[key] = value
        return value

    def utilities_dte(self, policy_matrix: np.ndarray, freshness_matrix: np.ndarray) -> np.ndarray:
        disc = validate_policy_matrix(policy_matrix)
        fresh = np.asarray(freshness_matrix, dtype=np.float64)
        if fresh.shape != POLICY_SHAPE:
            raise ValueError(f"freshness_matrix must have shape {POLICY_SHAPE}")
        price = self.arr["BASE_PRICE"][:, None] * (1.0 - disc)
        price = np.maximum(price, 1e-9)
        return (
            self.p["alpha"][self.category_index][None, :, None]
            + float(self.p["gamma"]) * self.arr["PREF_J"][:, :, None]
            + float(self.p["beta_disc"]) * self.arr["PS"][:, None, None] * disc[None, :, :]
            + float(self.p["beta_fresh"]) * self.arr["FS"][:, None, None] * (fresh[None, :, :] - 0.6)
            - float(self.p["beta_bud"]) * self.arr["PS"][:, None, None]
            * np.log(price[None, :, :] / self.arr["TRIP_BUD"][:, None, None])
            + np.log(self.arr["BSF"])[:, None, None]
            + float(self.p["c"])
        )

    def demand_by_dte(
        self,
        store_id: str,
        date: pd.Timestamp | str,
        hour: int,
        policy_matrix: np.ndarray,
        availability_matrix: np.ndarray,
        freshness_matrix: np.ndarray,
    ) -> np.ndarray:
        """Return joint DTE choice demand; accepts the complete matrix once."""
        disc = validate_policy_matrix(policy_matrix)
        avail = np.asarray(availability_matrix, dtype=np.float64)
        if avail.shape != POLICY_SHAPE:
            raise ValueError(f"availability_matrix must have shape {POLICY_SHAPE}")
        visitors = self.visitors(store_id, date, hour)
        if visitors is None:
            return np.zeros(POLICY_SHAPE, dtype=np.float64)
        utility = self.utilities_dte(disc, freshness_matrix)
        utility = np.where((avail > 0)[None, :, :], utility, -1e9)
        maximum = utility.max(axis=2, keepdims=True)
        exp_u = np.exp(utility - maximum)
        total = exp_u.sum(axis=2, keepdims=True)
        inclusive_value = (maximum + np.log(np.maximum(total, 1e-300)))[:, :, 0]
        product_probability = 1.0 / (1.0 + np.exp(-np.clip(inclusive_value, -60, 60)))
        bucket_share = exp_u / np.maximum(total, 1e-300)
        probability = product_probability[:, :, None] * bucket_share
        demand = np.einsum("s,spb->pb", visitors, probability) * float(self.p["EQ"])
        if not np.isfinite(demand).all() or (demand < -1e-12).any():
            raise RuntimeError("CustomerSimulator returned invalid demand")
        return np.maximum(demand, 0.0)


# Stable runtime name for B-team callers; Matrix prefix documents the full-policy extension.
CustomerSimulator = MatrixCustomerSimulator
