from datetime import date
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _parameters=None):
        return None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return FakeCursor(self.rows)


def sample_row():
    return {
        "product_id": "P001",
        "product_name": "테스트 상품",
        "category": "축산",
        "days_until_expiry": 1,
        "current_stock_quantity": 10,
        "reserved_quantity": 2,
        "stock_quantity": 8,
        "cost": 1000,
        "regular_price": 1500,
        "current_discount_rate": 20,
        "esl_applicable": 1,
        "snapshot_date": date(2026, 8, 11),
    }


class WebApiTests(unittest.TestCase):
    def test_inventory_and_summary(self):
        with patch.object(main, "connect_rds", return_value=FakeConnection([sample_row()])):
            inventory = main.inventory("S01")
            self.assertEqual(inventory[0]["product_id"], "P001")
            self.assertEqual(inventory[0]["current_discount_rate"], 0.2)
            self.assertFalse(inventory[0]["recommendation_available"])

            summary = main.summary("S01")
            self.assertEqual(summary["data_source"], "AWS_RDS")
            self.assertEqual(summary["risk_amount"], 8000)
            self.assertEqual(summary["model_status"], "NOT_READY")

    def test_rejects_unsupported_store(self):
        with self.assertRaises(HTTPException) as context:
            main.inventory("S04")
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
