import os
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ["DATABASE_PATH"] = str(Path(__file__).parent / "test_mock_erp.db")

from fastapi.testclient import TestClient
from app.main import app


def test_inventory_crud_and_calculated_fields():
    with TestClient(app) as client:
        response = client.post("/api/inventory", json={
            "inventory_id": "TEST001", "store_id": "STORE001", "product_id": "PROD999",
            "lot_id": "LOTTEST001", "current_date": "2026-07-22",
            "manufacture_date": "2026-07-20", "expiry_date": "2026-07-27",
            "inbound_qty": 10, "daily_sold_qty": 2, "daily_waste_qty": 0,
            "current_stock_qty": 8, "reserved_qty": 3, "unit_cost": 1000,
            "unit_price": 2000, "discount_rate": 25, "inventory_status": "ON_SALE",
            "weight_kg": 0.5
        })
        assert response.status_code in (201, 409)
        item = client.get("/api/inventory/TEST001").json()
        assert item["days_to_expiry"] == 5
        assert item["available_qty"] == 5
        assert item["discount_price"] == 1500


def test_rejects_reserved_quantity_above_stock():
    with TestClient(app) as client:
        response = client.post("/api/inventory", json={
            "inventory_id": "BAD001", "store_id": "STORE001", "product_id": "PROD999",
            "lot_id": "LOTBAD001", "current_date": "2026-07-22",
            "manufacture_date": "2026-07-20", "expiry_date": "2026-07-27",
            "inbound_qty": 10, "daily_sold_qty": 0, "daily_waste_qty": 0,
            "current_stock_qty": 3, "reserved_qty": 4, "unit_cost": 1000,
            "unit_price": 2000, "discount_rate": 0, "inventory_status": "ON_SALE",
            "weight_kg": 0.5
        })
        assert response.status_code == 422


def test_aws_sync_is_disabled_without_configuration():
    with TestClient(app) as client:
        response = client.post("/api/aws/sync")
        assert response.status_code == 503


def test_aws_sync_sends_existing_inventory_in_expected_format(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"success":true,"saved_count":1}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv(
        "AWS_SYNC_URL",
        "https://example.execute-api.ap-northeast-2.amazonaws.com/demo/erp/sync",
    )
    monkeypatch.setenv("ERP_SHARED_TOKEN", "test-token-at-least-24-characters")

    with patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen):
        with TestClient(app) as client:
            response = client.post("/api/aws/sync?limit=1")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured["headers"]["X-erp-api-key"] == "test-token-at-least-24-characters"
    assert captured["payload"]["source"] == "local-mock-erp"
    assert captured["payload"]["data_type"] == "inventory"
    assert len(captured["payload"]["records"]) == 1
    assert captured["timeout"] == 15


def test_new_inventory_is_sent_to_aws_automatically(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"success":true,"saved_count":1}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv(
        "AWS_SYNC_URL",
        "https://example.execute-api.ap-northeast-2.amazonaws.com/demo/erp/sync",
    )
    monkeypatch.setenv("ERP_SHARED_TOKEN", "test-token-at-least-24-characters")
    monkeypatch.setenv("AWS_AUTO_SYNC", "true")
    inventory_id = f"AUTO{uuid4().hex[:8].upper()}"

    with patch("app.main.urllib.request.urlopen", side_effect=fake_urlopen):
        with TestClient(app) as client:
            response = client.post("/api/inventory", json={
                "inventory_id": inventory_id,
                "store_id": "STORE001",
                "product_id": "PROD-AUTO",
                "lot_id": f"LOT-{inventory_id}",
                "current_date": "2026-07-23",
                "manufacture_date": "2026-07-20",
                "expiry_date": "2026-07-27",
                "inbound_qty": 10,
                "daily_sold_qty": 1,
                "daily_waste_qty": 0,
                "current_stock_qty": 9,
                "reserved_qty": 0,
                "unit_cost": 1000,
                "unit_price": 2000,
                "discount_rate": 10,
                "inventory_status": "ON_SALE",
                "weight_kg": 0.5,
            })
            saved = client.get(f"/api/inventory/{inventory_id}").json()

    assert response.status_code == 201
    assert response.json()["aws_sync"]["success"] is True
    assert captured["payload"]["records"][0]["inventory_id"] == inventory_id
    assert saved["aws_sync_status"] == "SYNCED"
    assert saved["aws_synced_at"] is not None
