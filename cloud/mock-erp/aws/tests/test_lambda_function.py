import importlib.util
import os
import sys
import types
from pathlib import Path


os.environ.update(
    {
        "DB_HOST": "database.internal",
        "DB_NAME": "erp_sync",
        "DB_USER": "erp_admin",
        "DB_PASSWORD": "not-used-in-unit-tests",
        "ERP_SHARED_TOKEN": "test-token-at-least-24-characters",
    }
)

fake_psycopg = types.ModuleType("psycopg")
fake_psycopg.Connection = object
fake_psycopg.Error = Exception
fake_psycopg.connect = lambda **_kwargs: None
sys.modules.setdefault("psycopg", fake_psycopg)

module_path = Path(__file__).parents[1] / "receiver" / "lambda_function.py"
spec = importlib.util.spec_from_file_location("erp_receiver_lambda", module_path)
lambda_function = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lambda_function)


def sample_payload():
    return {
        "source": "local-mock-erp",
        "data_type": "inventory",
        "sent_at": "2026-07-23T00:00:00+00:00",
        "records": [
            {
                "inventory_id": "INV1",
                "store_id": "STORE1",
                "product_id": "PROD1",
                "lot_id": "LOT1",
                "current_date": "2026-07-23",
                "manufacture_date": "2026-07-20",
                "expiry_date": "2026-07-25",
                "days_to_expiry": 2,
                "inbound_qty": 10,
                "daily_sold_qty": 2,
                "daily_waste_qty": 0,
                "current_stock_qty": 8,
                "reserved_qty": 1,
                "available_qty": 7,
                "freshness_score": 40.0,
                "unit_cost": 1000,
                "unit_price": 2000,
                "discount_rate": 20,
                "discount_price": 1600,
                "disposal_candidate": "N",
                "inventory_status": "ON_SALE",
                "waste_reason": None,
                "weight_kg": 0.5,
                "created_at": "2026-07-23T00:00:00+00:00",
                "updated_at": "2026-07-23T00:00:00+00:00",
            }
        ],
    }


def test_rejects_invalid_token_before_database_access():
    result = lambda_function.lambda_handler(
        {"headers": {"x-erp-api-key": "wrong"}, "body": "{}"},
        None,
    )
    assert result["statusCode"] == 401


def test_accepts_the_existing_mock_erp_payload_shape():
    records = lambda_function.validate_payload(sample_payload())
    assert records[0]["inventory_id"] == "INV1"


def test_rejects_missing_inventory_fields():
    payload = sample_payload()
    del payload["records"][0]["product_id"]
    try:
        lambda_function.validate_payload(payload)
    except ValueError as exc:
        assert "product_id" in str(exc)
    else:
        raise AssertionError("missing product_id should be rejected")
