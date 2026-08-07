"""Authoritative per-store operating window lookup for A and B runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def resolve_store_schedule(
    project_root: str | Path,
    store_id: str,
    decision_timestamp: Any,
) -> dict[str, Any]:
    """Return the exact store-calendar row and last evaluable sales hour.

    ``close_hour`` is the exclusive business closing boundary. The B hourly
    simulator therefore evaluates through ``close_hour - 1``.
    """
    root = Path(project_root)
    timestamp = pd.Timestamp(decision_timestamp)
    local = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
    calendar = pd.read_csv(root / "data" / "store_calendar.csv", parse_dates=["date"])
    rows = calendar[
        calendar["store_id"].astype(str).eq(str(store_id))
        & calendar["date"].eq(local.normalize())
    ]
    if len(rows) != 1:
        raise ValueError(
            f"store_calendar must contain exactly one row for store_id={store_id}, "
            f"date={local.date()}; found {len(rows)}"
        )
    row = rows.iloc[0]
    if not bool(int(row["is_open"])):
        raise ValueError(
            f"Store {store_id} is closed on {local.date()}: {row.get('closure_reason', 'UNKNOWN')}"
        )
    open_hour = int(float(row["open_hour"]))
    close_hour_exclusive = int(float(row["close_hour"]))
    if close_hour_exclusive <= open_hour:
        raise ValueError(f"Invalid operating hours for {store_id}: {open_hour}..{close_hour_exclusive}")
    if int(local.hour) < open_hour or int(local.hour) >= close_hour_exclusive:
        raise ValueError(
            f"decision hour {local.hour} is outside {store_id} operating hours "
            f"[{open_hour}, {close_hour_exclusive})"
        )
    return {
        "store_id": str(store_id),
        "date": local.normalize(),
        "open_hour": open_hour,
        "close_hour_exclusive": close_hour_exclusive,
        "evaluation_end_hour": close_hour_exclusive - 1,
        "closure_reason": str(row.get("closure_reason", "NONE")),
        "schedule_source": "data/store_calendar.csv",
    }
