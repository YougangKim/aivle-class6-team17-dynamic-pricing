from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import connect_rds


app = FastAPI(title="FreshWatch WEB API", version="1.0.0")

allowed_origins = [
    value.strip()
    for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

SUPPORTED_STORES = {"S01", "S02", "S03"}

INVENTORY_SQL = """
WITH latest_snapshot AS (
    SELECT MAX(inventory_date) AS inventory_date
    FROM inventory.inventory
    WHERE store_id = %(store_id)s
),
filtered_inventory AS (
    SELECT i.*
    FROM inventory.inventory i
    JOIN latest_snapshot latest ON i.inventory_date = latest.inventory_date
    WHERE i.store_id = %(store_id)s
      AND i.product_id BETWEEN 'P001' AND 'P038'
)
SELECT
    i.product_id,
    p.product_name,
    p.category,
    MIN(i.days_to_expiry) AS days_until_expiry,
    SUM(i.current_stock_qty) AS current_stock_quantity,
    SUM(i.reserved_qty) AS reserved_quantity,
    SUM(i.available_qty) AS stock_quantity,
    MAX(i.unit_cost) AS cost,
    MAX(i.unit_price) AS regular_price,
    MAX(i.discount_rate) AS current_discount_rate,
    BOOL_OR(COALESCE(p.esl_applicable, FALSE)) AS esl_applicable,
    MAX(i.inventory_date) AS snapshot_date
FROM filtered_inventory i
JOIN product_price.product p ON p.product_id = i.product_id
WHERE i.available_qty > 0
GROUP BY i.product_id, p.product_name, p.category
ORDER BY i.product_id
"""


def _validate_store(store_id: str) -> None:
    if store_id not in SUPPORTED_STORES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 점포입니다: {store_id}")


def _normalize_rate(value: Any) -> float:
    rate = float(value or 0)
    return rate / 100.0 if rate > 1 else rate


def load_inventory(store_id: str) -> list[dict[str, Any]]:
    _validate_store(store_id)
    try:
        with connect_rds() as connection:
            with connection.cursor() as cursor:
                cursor.execute(INVENTORY_SQL, {"store_id": store_id})
                rows = cursor.fetchall()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="RDS 재고 데이터를 조회할 수 없습니다.") from exc

    return [
        {
            "product_id": str(row["product_id"]),
            "product_name": str(row["product_name"]),
            "category": str(row["category"]),
            "days_until_expiry": int(row["days_until_expiry"]),
            "stock_quantity": int(row["stock_quantity"]),
            "current_stock_quantity": int(row["current_stock_quantity"]),
            "reserved_quantity": int(row["reserved_quantity"]),
            "cost": float(row["cost"]),
            "regular_price": float(row["regular_price"]),
            "current_discount_rate": _normalize_rate(row["current_discount_rate"]),
            "recommended_rate": 0.0,
            "recommendation_available": False,
            "esl_applicable": bool(row["esl_applicable"]),
            "snapshot_date": row["snapshot_date"].isoformat(),
        }
        for row in rows
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "freshwatch-web-api"}


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        with connect_rds() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="RDS 연결 준비가 되지 않았습니다.") from exc
    return {"status": "ready", "database": "rds-postgresql"}


@app.get("/api/inventory")
def inventory(store_id: str = Query(pattern=r"^S\d{2}$")) -> list[dict[str, Any]]:
    return load_inventory(store_id)


@app.get("/api/summary")
def summary(store_id: str = Query(pattern=r"^S\d{2}$")) -> dict[str, Any]:
    items = load_inventory(store_id)
    risk_items = [item for item in items if item["days_until_expiry"] <= 2]
    risk_amount = sum(item["stock_quantity"] * item["cost"] for item in risk_items)
    category_amounts: defaultdict[str, float] = defaultdict(float)
    for item in risk_items:
        category_amounts[item["category"]] += item["stock_quantity"] * item["cost"]
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return {
        "data_source": "AWS_RDS",
        "model_status": "NOT_READY",
        "snapshot_date": items[0]["snapshot_date"] if items else None,
        "product_count": len(items),
        "total_stock_quantity": sum(item["stock_quantity"] for item in items),
        "pending": len(risk_items),
        "d_day": sum(item["days_until_expiry"] <= 0 for item in items),
        "d_1": sum(item["days_until_expiry"] == 1 for item in items),
        "d_2": sum(item["days_until_expiry"] == 2 for item in items),
        "risk_amount": round(risk_amount),
        "expected_revenue": None,
        "expected_waste_loss": None,
        "by_category": [
            {"name": category, "value": round(amount / 10_000, 1)}
            for category, amount in sorted(category_amounts.items(), key=lambda pair: pair[1], reverse=True)
        ],
        "waste_trend": [],
        "context": {
            "weather": "정보 없음",
            "temp": 0,
            "visitor_delta": 0,
            "store_time": now.strftime("%H:%M"),
        },
        "calendar": None,
    }


@app.get("/api/recommendations")
def recommendations(store_id: str = Query(pattern=r"^S\d{2}$")) -> list[Any]:
    _validate_store(store_id)
    return []


@app.get("/api/recommendations/skipped")
def skipped_recommendations(store_id: str = Query(pattern=r"^S\d{2}$")) -> list[Any]:
    _validate_store(store_id)
    return []
