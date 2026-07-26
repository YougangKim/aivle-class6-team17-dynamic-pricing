import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "mock_erp.db"))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH
STATIC_DIR = BASE_DIR / "static"

INVENTORY_STATUSES = {"ON_SALE", "OUT_OF_STOCK", "DISPOSAL", "RESERVED"}


@contextmanager
def database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class InventoryRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    inventory_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=50)
    store_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=50)
    product_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=50)
    lot_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=80)
    current_date: date
    manufacture_date: date
    expiry_date: date
    days_to_expiry: int | None = None
    inbound_qty: int = Field(ge=0)
    daily_sold_qty: int = Field(ge=0)
    daily_waste_qty: int = Field(ge=0)
    current_stock_qty: int = Field(ge=0)
    reserved_qty: int = Field(ge=0)
    available_qty: int | None = Field(default=None, ge=0)
    freshness_score: float | None = Field(default=None, ge=0, le=100)
    unit_cost: int = Field(ge=0)
    unit_price: int = Field(ge=0)
    discount_rate: int = Field(ge=0, le=100)
    discount_price: int | None = Field(default=None, ge=0)
    disposal_candidate: Literal["Y", "N"] | None = None
    inventory_status: str = Field(default="ON_SALE", max_length=30)
    waste_reason: str | None = Field(default=None, max_length=100)
    weight_kg: float = Field(gt=0)

    @model_validator(mode="after")
    def calculate_and_validate(self):
        if self.manufacture_date > self.expiry_date:
            raise ValueError("manufacture_date는 expiry_date보다 늦을 수 없습니다")
        if self.reserved_qty > self.current_stock_qty:
            raise ValueError("reserved_qty는 current_stock_qty보다 클 수 없습니다")
        if self.inventory_status not in INVENTORY_STATUSES:
            raise ValueError(f"inventory_status는 {sorted(INVENTORY_STATUSES)} 중 하나여야 합니다")

        calculated_days = (self.expiry_date - self.current_date).days
        self.days_to_expiry = calculated_days
        self.available_qty = self.current_stock_qty - self.reserved_qty
        self.discount_price = round(self.unit_price * (100 - self.discount_rate) / 100)

        shelf_life = max((self.expiry_date - self.manufacture_date).days, 1)
        if self.freshness_score is None:
            self.freshness_score = round(max(0, min(100, calculated_days / shelf_life * 100)), 1)
        if self.disposal_candidate is None:
            self.disposal_candidate = "Y" if calculated_days <= 0 or self.inventory_status == "DISPOSAL" else "N"

        if self.inventory_status == "OUT_OF_STOCK" and self.current_stock_qty != 0:
            raise ValueError("OUT_OF_STOCK 상태의 current_stock_qty는 0이어야 합니다")
        return self


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS inventory (
    inventory_id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    "current_date" TEXT NOT NULL,
    manufacture_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    days_to_expiry INTEGER NOT NULL,
    inbound_qty INTEGER NOT NULL CHECK (inbound_qty >= 0),
    daily_sold_qty INTEGER NOT NULL CHECK (daily_sold_qty >= 0),
    daily_waste_qty INTEGER NOT NULL CHECK (daily_waste_qty >= 0),
    current_stock_qty INTEGER NOT NULL CHECK (current_stock_qty >= 0),
    reserved_qty INTEGER NOT NULL CHECK (reserved_qty >= 0),
    available_qty INTEGER NOT NULL CHECK (available_qty >= 0),
    freshness_score REAL NOT NULL CHECK (freshness_score BETWEEN 0 AND 100),
    unit_cost INTEGER NOT NULL CHECK (unit_cost >= 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    discount_rate INTEGER NOT NULL CHECK (discount_rate BETWEEN 0 AND 100),
    discount_price INTEGER NOT NULL CHECK (discount_price >= 0),
    disposal_candidate TEXT NOT NULL CHECK (disposal_candidate IN ('Y', 'N')),
    inventory_status TEXT NOT NULL,
    waste_reason TEXT,
    weight_kg REAL NOT NULL CHECK (weight_kg > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (store_id, product_id, lot_id, "current_date")
);
CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_store ON inventory(store_id);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory(expiry_date);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(inventory_status);
"""

SYNC_COLUMNS = {
    "aws_sync_status": "TEXT NOT NULL DEFAULT 'PENDING'",
    "aws_sync_error": "TEXT",
    "aws_synced_at": "TEXT",
}

SEED_RECORDS = [
    {
        "inventory_id": "INV000001", "store_id": "STORE001", "product_id": "PROD001",
        "lot_id": "LOT20260718001", "current_date": "2026-07-22",
        "manufacture_date": "2026-07-18", "expiry_date": "2026-07-25",
        "inbound_qty": 50, "daily_sold_qty": 12, "daily_waste_qty": 0,
        "current_stock_qty": 38, "reserved_qty": 3, "unit_cost": 3500,
        "unit_price": 4980, "discount_rate": 20, "inventory_status": "ON_SALE",
        "waste_reason": None, "weight_kg": 0.45,
    },
    {
        "inventory_id": "INV000002", "store_id": "STORE001", "product_id": "PROD002",
        "lot_id": "LOT20260719001", "current_date": "2026-07-22",
        "manufacture_date": "2026-07-19", "expiry_date": "2026-07-23",
        "inbound_qty": 30, "daily_sold_qty": 8, "daily_waste_qty": 1,
        "current_stock_qty": 21, "reserved_qty": 2, "unit_cost": 2100,
        "unit_price": 3200, "discount_rate": 30, "inventory_status": "ON_SALE",
        "waste_reason": None, "weight_kg": 0.3,
    },
    {
        "inventory_id": "INV000003", "store_id": "STORE002", "product_id": "PROD003",
        "lot_id": "LOT20260715002", "current_date": "2026-07-22",
        "manufacture_date": "2026-07-15", "expiry_date": "2026-07-22",
        "inbound_qty": 20, "daily_sold_qty": 3, "daily_waste_qty": 2,
        "current_stock_qty": 15, "reserved_qty": 0, "unit_cost": 4700,
        "unit_price": 6900, "discount_rate": 50, "inventory_status": "DISPOSAL",
        "waste_reason": "EXPIRING_TODAY", "weight_kg": 0.5,
    },
]


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def record_values(record: InventoryRecord) -> dict:
    return record.model_dump(mode="json")


def upsert_inventory(connection: sqlite3.Connection, record: InventoryRecord) -> None:
    values = record_values(record)
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO inventory (
            inventory_id, store_id, product_id, lot_id, "current_date", manufacture_date,
            expiry_date, days_to_expiry, inbound_qty, daily_sold_qty, daily_waste_qty,
            current_stock_qty, reserved_qty, available_qty, freshness_score, unit_cost,
            unit_price, discount_rate, discount_price, disposal_candidate,
            inventory_status, waste_reason, weight_kg, created_at, updated_at
        ) VALUES (
            :inventory_id, :store_id, :product_id, :lot_id, :current_date, :manufacture_date,
            :expiry_date, :days_to_expiry, :inbound_qty, :daily_sold_qty, :daily_waste_qty,
            :current_stock_qty, :reserved_qty, :available_qty, :freshness_score, :unit_cost,
            :unit_price, :discount_rate, :discount_price, :disposal_candidate,
            :inventory_status, :waste_reason, :weight_kg, :created_at, :updated_at
        )
        ON CONFLICT(inventory_id) DO UPDATE SET
            store_id=excluded.store_id, product_id=excluded.product_id, lot_id=excluded.lot_id,
            current_date=excluded.current_date, manufacture_date=excluded.manufacture_date,
            expiry_date=excluded.expiry_date, days_to_expiry=excluded.days_to_expiry,
            inbound_qty=excluded.inbound_qty, daily_sold_qty=excluded.daily_sold_qty,
            daily_waste_qty=excluded.daily_waste_qty, current_stock_qty=excluded.current_stock_qty,
            reserved_qty=excluded.reserved_qty, available_qty=excluded.available_qty,
            freshness_score=excluded.freshness_score, unit_cost=excluded.unit_cost,
            unit_price=excluded.unit_price, discount_rate=excluded.discount_rate,
            discount_price=excluded.discount_price, disposal_candidate=excluded.disposal_candidate,
            inventory_status=excluded.inventory_status, waste_reason=excluded.waste_reason,
            weight_kg=excluded.weight_kg, updated_at=excluded.updated_at,
            aws_sync_status='PENDING', aws_sync_error=NULL, aws_synced_at=NULL
        """,
        {**values, "created_at": now, "updated_at": now},
    )


def ensure_sync_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(inventory)").fetchall()
    }
    for column, definition in SYNC_COLUMNS.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE inventory ADD COLUMN {column} {definition}")


def initialize_database() -> None:
    with database() as connection:
        connection.executescript(CREATE_TABLE_SQL)
        ensure_sync_columns(connection)
        count = connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        if count == 0:
            for item in SEED_RECORDS:
                upsert_inventory(connection, InventoryRecord.model_validate(item))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Fresh Food Mock ERP",
    version="1.0.0",
    description="신선식품 재고·로트·가격 데이터를 관리하고 AWS 연동을 연습하는 로컬 Mock ERP",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    with database() as connection:
        count = connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    return {"status": "ok", "database": "sqlite", "inventory_count": count}


@app.get("/api/inventory")
def list_inventory(
    store_id: str | None = None,
    product_id: str | None = None,
    status: str | None = Query(default=None, alias="inventory_status"),
    disposal_candidate: Literal["Y", "N"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    clauses = []
    parameters: list[str | int] = []
    for column, value in (
        ("store_id", store_id), ("product_id", product_id),
        ("inventory_status", status), ("disposal_candidate", disposal_candidate),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit)
    with database() as connection:
        rows = connection.execute(
            f"SELECT * FROM inventory {where} ORDER BY expiry_date, inventory_id LIMIT ?",
            parameters,
        ).fetchall()
    return {"count": len(rows), "items": [row_to_dict(row) for row in rows]}


@app.get("/api/inventory/{inventory_id}")
def get_inventory(inventory_id: str):
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM inventory WHERE inventory_id = ?", (inventory_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="재고를 찾을 수 없습니다")
    return row_to_dict(row)


@app.post("/api/inventory", status_code=201)
def create_inventory(record: InventoryRecord):
    with database() as connection:
        exists = connection.execute(
            "SELECT 1 FROM inventory WHERE inventory_id = ?", (record.inventory_id,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="이미 존재하는 inventory_id입니다")
        try:
            upsert_inventory(connection, record)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    sync_result = auto_sync_inventory(record.inventory_id)
    return {**record_values(record), "aws_sync": sync_result}


@app.put("/api/inventory/{inventory_id}")
def update_inventory(inventory_id: str, record: InventoryRecord):
    if inventory_id != record.inventory_id:
        raise HTTPException(status_code=400, detail="경로와 본문의 inventory_id가 다릅니다")
    with database() as connection:
        exists = connection.execute(
            "SELECT 1 FROM inventory WHERE inventory_id = ?", (inventory_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="재고를 찾을 수 없습니다")
        upsert_inventory(connection, record)
    sync_result = auto_sync_inventory(record.inventory_id)
    return {**record_values(record), "aws_sync": sync_result}


@app.delete("/api/inventory/{inventory_id}", status_code=204)
def delete_inventory(inventory_id: str):
    with database() as connection:
        cursor = connection.execute("DELETE FROM inventory WHERE inventory_id = ?", (inventory_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="재고를 찾을 수 없습니다")


@app.get("/api/aws/payload-preview")
def aws_payload_preview(limit: int = Query(default=10, ge=1, le=100)):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM inventory ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "source": "local-mock-erp",
        "data_type": "inventory",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "records": [row_to_dict(row) for row in rows],
    }


def payload_for_inventory_ids(inventory_ids: list[str]) -> dict:
    if not inventory_ids:
        return {
            "source": "local-mock-erp",
            "data_type": "inventory",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "records": [],
        }
    placeholders = ",".join("?" for _ in inventory_ids)
    with database() as connection:
        rows = connection.execute(
            f"SELECT * FROM inventory WHERE inventory_id IN ({placeholders}) "
            "ORDER BY updated_at DESC",
            inventory_ids,
        ).fetchall()
    return {
        "source": "local-mock-erp",
        "data_type": "inventory",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "records": [row_to_dict(row) for row in rows],
    }


def post_payload_to_aws(payload: dict) -> dict:
    url = os.getenv("AWS_SYNC_URL", "").strip()
    token = os.getenv("ERP_SHARED_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("AWS_SYNC_URL과 ERP_SHARED_TOKEN이 설정되지 않았습니다")
    if not url.lower().startswith("https://"):
        raise ValueError("AWS_SYNC_URL은 https:// 주소여야 합니다")

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-ERP-API-KEY": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
        return {
            "success": True,
            "status_code": response.status,
            "response": body,
        }


def set_sync_status(inventory_ids: list[str], status: str, error: str | None = None) -> None:
    placeholders = ",".join("?" for _ in inventory_ids)
    synced_at = datetime.now(timezone.utc).isoformat() if status == "SYNCED" else None
    with database() as connection:
        connection.execute(
            f"""
            UPDATE inventory
            SET aws_sync_status = ?, aws_sync_error = ?, aws_synced_at = ?
            WHERE inventory_id IN ({placeholders})
            """,
            [status, error, synced_at, *inventory_ids],
        )


def sync_inventory_ids(inventory_ids: list[str]) -> dict:
    payload = payload_for_inventory_ids(inventory_ids)
    if not payload["records"]:
        return {"success": True, "saved_count": 0}
    try:
        result = post_payload_to_aws(payload)
        set_sync_status(inventory_ids, "SYNCED")
        return {**result, "saved_count": len(payload["records"])}
    except urllib.error.HTTPError as exc:
        message = f"AWS API 응답 오류: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        message = f"AWS API 연결 실패: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        message = f"AWS API 연결 실패: {exc}"
    except (RuntimeError, ValueError) as exc:
        message = str(exc)

    set_sync_status(inventory_ids, "FAILED", message[:500])
    return {"success": False, "message": message}


def auto_sync_inventory(inventory_id: str) -> dict:
    enabled = os.getenv("AWS_AUTO_SYNC", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not enabled:
        return {"success": False, "skipped": True, "message": "자동 전송이 비활성화되어 있습니다"}
    return sync_inventory_ids([inventory_id])


@app.post("/api/aws/sync")
def sync_to_aws(limit: int = Query(default=10, ge=1, le=100)):
    url = os.getenv("AWS_SYNC_URL", "").strip()
    token = os.getenv("ERP_SHARED_TOKEN", "").strip()
    if not url or not token:
        raise HTTPException(
            status_code=503,
            detail="AWS_SYNC_URL과 ERP_SHARED_TOKEN이 설정되지 않아 외부 전송을 실행하지 않았습니다",
        )
    if not url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="AWS_SYNC_URL은 https:// 주소여야 합니다")

    with database() as connection:
        rows = connection.execute(
            """
            SELECT inventory_id
            FROM inventory
            WHERE aws_sync_status != 'SYNCED'
            ORDER BY updated_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    inventory_ids = [row["inventory_id"] for row in rows]
    result = sync_inventory_ids(inventory_ids)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result
