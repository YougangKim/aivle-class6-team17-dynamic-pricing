import base64
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg


DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
ERP_SHARED_TOKEN = os.environ["ERP_SHARED_TOKEN"]
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS erp_sync_batches (
    batch_id BIGSERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    data_type VARCHAR(50) NOT NULL,
    source_sent_at TIMESTAMPTZ,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id VARCHAR(50) PRIMARY KEY,
    store_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    lot_id VARCHAR(80) NOT NULL,
    "current_date" DATE NOT NULL,
    manufacture_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    days_to_expiry INTEGER NOT NULL,
    inbound_qty INTEGER NOT NULL CHECK (inbound_qty >= 0),
    daily_sold_qty INTEGER NOT NULL CHECK (daily_sold_qty >= 0),
    daily_waste_qty INTEGER NOT NULL CHECK (daily_waste_qty >= 0),
    current_stock_qty INTEGER NOT NULL CHECK (current_stock_qty >= 0),
    reserved_qty INTEGER NOT NULL CHECK (reserved_qty >= 0),
    available_qty INTEGER NOT NULL CHECK (available_qty >= 0),
    freshness_score NUMERIC(5, 1) NOT NULL CHECK (freshness_score BETWEEN 0 AND 100),
    unit_cost INTEGER NOT NULL CHECK (unit_cost >= 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    discount_rate INTEGER NOT NULL CHECK (discount_rate BETWEEN 0 AND 100),
    discount_price INTEGER NOT NULL CHECK (discount_price >= 0),
    disposal_candidate CHAR(1) NOT NULL CHECK (disposal_candidate IN ('Y', 'N')),
    inventory_status VARCHAR(30) NOT NULL,
    waste_reason VARCHAR(100),
    weight_kg NUMERIC(10, 3) NOT NULL CHECK (weight_kg > 0),
    source_created_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (store_id, product_id, lot_id, "current_date")
);

CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_store ON inventory(store_id);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory(expiry_date);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(inventory_status);
"""


UPSERT_INVENTORY_SQL = """
INSERT INTO inventory (
    inventory_id, store_id, product_id, lot_id, "current_date", manufacture_date,
    expiry_date, days_to_expiry, inbound_qty, daily_sold_qty, daily_waste_qty,
    current_stock_qty, reserved_qty, available_qty, freshness_score, unit_cost,
    unit_price, discount_rate, discount_price, disposal_candidate,
    inventory_status, waste_reason, weight_kg, source_created_at, source_updated_at
) VALUES (
    %(inventory_id)s, %(store_id)s, %(product_id)s, %(lot_id)s, %(current_date)s,
    %(manufacture_date)s, %(expiry_date)s, %(days_to_expiry)s, %(inbound_qty)s,
    %(daily_sold_qty)s, %(daily_waste_qty)s, %(current_stock_qty)s,
    %(reserved_qty)s, %(available_qty)s, %(freshness_score)s, %(unit_cost)s,
    %(unit_price)s, %(discount_rate)s, %(discount_price)s,
    %(disposal_candidate)s, %(inventory_status)s, %(waste_reason)s,
    %(weight_kg)s, %(created_at)s, %(updated_at)s
)
ON CONFLICT (inventory_id) DO UPDATE SET
    store_id = EXCLUDED.store_id,
    product_id = EXCLUDED.product_id,
    lot_id = EXCLUDED.lot_id,
    "current_date" = EXCLUDED."current_date",
    manufacture_date = EXCLUDED.manufacture_date,
    expiry_date = EXCLUDED.expiry_date,
    days_to_expiry = EXCLUDED.days_to_expiry,
    inbound_qty = EXCLUDED.inbound_qty,
    daily_sold_qty = EXCLUDED.daily_sold_qty,
    daily_waste_qty = EXCLUDED.daily_waste_qty,
    current_stock_qty = EXCLUDED.current_stock_qty,
    reserved_qty = EXCLUDED.reserved_qty,
    available_qty = EXCLUDED.available_qty,
    freshness_score = EXCLUDED.freshness_score,
    unit_cost = EXCLUDED.unit_cost,
    unit_price = EXCLUDED.unit_price,
    discount_rate = EXCLUDED.discount_rate,
    discount_price = EXCLUDED.discount_price,
    disposal_candidate = EXCLUDED.disposal_candidate,
    inventory_status = EXCLUDED.inventory_status,
    waste_reason = EXCLUDED.waste_reason,
    weight_kg = EXCLUDED.weight_kg,
    source_created_at = EXCLUDED.source_created_at,
    source_updated_at = EXCLUDED.source_updated_at,
    synced_at = NOW()
"""

GET_INVENTORY_SQL = """
SELECT
    inventory_id, store_id, product_id, lot_id, "current_date",
    manufacture_date, expiry_date, current_stock_qty, available_qty,
    freshness_score, unit_price, discount_rate, discount_price,
    disposal_candidate, inventory_status, synced_at
FROM inventory
WHERE inventory_id = %s
"""

GET_INVENTORY_COLUMNS = (
    "inventory_id",
    "store_id",
    "product_id",
    "lot_id",
    "current_date",
    "manufacture_date",
    "expiry_date",
    "current_stock_qty",
    "available_qty",
    "freshness_score",
    "unit_price",
    "discount_rate",
    "discount_price",
    "disposal_candidate",
    "inventory_status",
    "synced_at",
)


REQUIRED_FIELDS = {
    "inventory_id",
    "store_id",
    "product_id",
    "lot_id",
    "current_date",
    "manufacture_date",
    "expiry_date",
    "days_to_expiry",
    "inbound_qty",
    "daily_sold_qty",
    "daily_waste_qty",
    "current_stock_qty",
    "reserved_qty",
    "available_qty",
    "freshness_score",
    "unit_cost",
    "unit_price",
    "discount_rate",
    "discount_price",
    "disposal_candidate",
    "inventory_status",
    "weight_kg",
}


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def request_header(event: dict[str, Any], name: str) -> str:
    headers = event.get("headers") or {}
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    return lowered.get(name.lower(), "")


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None and ("records" in event or "action" in event):
        return event
    if not isinstance(raw_body, str):
        raise ValueError("요청 본문이 없습니다.")
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    body = json.loads(raw_body)
    if not isinstance(body, dict):
        raise ValueError("요청 본문은 JSON 객체여야 합니다.")
    return body


def validate_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("source") != "local-mock-erp":
        raise ValueError("지원하지 않는 source입니다.")
    if payload.get("data_type") != "inventory":
        raise ValueError("지원하지 않는 data_type입니다.")

    records = payload.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("records는 1~100건의 배열이어야 합니다.")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}]는 JSON 객체여야 합니다.")
        missing = sorted(REQUIRED_FIELDS - record.keys())
        if missing:
            raise ValueError(f"records[{index}] 필수값 누락: {', '.join(missing)}")
    return records


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
        sslmode="require",
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    supplied_token = request_header(event, "x-erp-api-key")
    if not supplied_token or not hmac.compare_digest(supplied_token, ERP_SHARED_TOKEN):
        return response(401, {"success": False, "message": "인증에 실패했습니다."})

    try:
        payload = parse_body(event)
        if payload.get("action") == "get_inventory":
            inventory_id = str(payload.get("inventory_id", "")).strip()
            if not inventory_id or len(inventory_id) > 50:
                return response(
                    400,
                    {"success": False, "message": "올바른 inventory_id가 필요합니다."},
                )
            with connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(GET_INVENTORY_SQL, (inventory_id,))
                    row = cursor.fetchone()
            if row is None:
                return response(
                    404,
                    {"success": False, "message": "해당 재고가 RDS에 없습니다."},
                )
            return response(
                200,
                {
                    "success": True,
                    "source": "Amazon RDS PostgreSQL",
                    "inventory": dict(zip(GET_INVENTORY_COLUMNS, row)),
                },
            )
        records = validate_payload(payload)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return response(400, {"success": False, "message": str(exc)})
    except psycopg.Error as exc:
        logger.exception("RDS read failed (%s)", type(exc).__name__)
        return response(
            500,
            {
                "success": False,
                "message": "RDS 조회에 실패했습니다. CloudWatch 로그를 확인하세요.",
            },
        )

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(CREATE_SCHEMA_SQL)
                for record in records:
                    cursor.execute(UPSERT_INVENTORY_SQL, record)
                cursor.execute(
                    """
                    INSERT INTO erp_sync_batches
                        (source, data_type, source_sent_at, record_count)
                    VALUES (%s, %s, %s, %s)
                    RETURNING batch_id, received_at
                    """,
                    (
                        payload["source"],
                        payload["data_type"],
                        payload.get("sent_at") or datetime.now(timezone.utc).isoformat(),
                        len(records),
                    ),
                )
                batch_id, received_at = cursor.fetchone()
    except psycopg.Error as exc:
        logger.exception("RDS save failed (%s)", type(exc).__name__)
        return response(
            500,
            {
                "success": False,
                "message": "RDS 저장에 실패했습니다. CloudWatch 로그를 확인하세요.",
            },
        )

    return response(
        200,
        {
            "success": True,
            "batch_id": batch_id,
            "saved_count": len(records),
            "received_at": received_at,
        },
    )
