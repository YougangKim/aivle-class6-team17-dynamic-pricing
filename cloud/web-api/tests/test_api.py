from datetime import date
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app import recommendations


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

    def fetchone(self):
        return self.rows[0] if self.rows else None


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
        "dte_index": 1,
        "current_stock_quantity": 10,
        "reserved_quantity": 2,
        "stock_quantity": 8,
        "daily_sold_quantity": 4,
        "daily_waste_quantity": 1,
        "cost": 1000,
        "regular_price": 1500,
        "current_discount_rate": 20,
        "esl_applicable": 1,
        "snapshot_date": date(2026, 8, 11),
    }


class WebApiTests(unittest.TestCase):
    def test_reprice_changes_only_target_cell(self):
        matrix = [[0.10, 0.20, 0.30, 0.40] for _ in range(38)]
        candidate = recommendations._candidate_matrix(matrix, "P002", 1, 0.15)
        self.assertEqual(candidate[1][1], 0.15)
        self.assertEqual(candidate[0], matrix[0])
        self.assertEqual(matrix[1][1], 0.20)

    def test_reprice_reason_reduces_cap(self):
        item = recommendations.RepriceItem(
            product_id="P001", dte_index=0, previous_rate=0.40,
            reason_code="margin_guard", round=1,
        )
        self.assertEqual(recommendations._reprice_cap(item), 0.25)

    def test_inventory_and_summary(self):
        with patch.object(main, "connect_rds", return_value=FakeConnection([sample_row()])):
            inventory = main.inventory("S01")
            self.assertEqual(inventory[0]["product_id"], "P001")
            self.assertEqual(inventory[0]["current_discount_rate"], 0.2)
            self.assertFalse(inventory[0]["recommendation_available"])
            self.assertEqual(inventory[0]["category"], "축산")
            self.assertAlmostEqual(inventory[0]["turnover"], 4 / 15)
            self.assertTrue(inventory[0]["turnover_available"])
            self.assertEqual(inventory[0]["daily_sold_quantity"], 4)
            self.assertEqual(inventory[0]["daily_waste_quantity"], 1)
            self.assertEqual(inventory[0]["expected_loss"], 8000)

            summary = main.summary("S01")
            self.assertEqual(summary["data_source"], "AWS_RDS")
            self.assertEqual(summary["risk_amount"], 8000)
            self.assertEqual(summary["model_status"], "NOT_READY")

    def test_rejects_unsupported_store(self):
        with self.assertRaises(HTTPException) as context:
            main.inventory("S04")
        self.assertEqual(context.exception.status_code, 400)

    def test_maps_rds_category_codes(self):
        row = sample_row()
        row["category"] = "produce"
        with patch.object(main, "connect_rds", return_value=FakeConnection([row])):
            inventory = main.inventory("S01")
        self.assertEqual(inventory[0]["category"], "청과")
        self.assertEqual(inventory[0]["category_code"], "produce")

    def test_turnover_is_zero_when_no_stock_activity(self):
        self.assertEqual(main._turnover(0, 0, 0), 0.0)

    def test_baseline_result_clears_dashboard_recommendations(self):
        result = {
            "request_id": "S02-187",
            "store_id": "S02",
            "acceptance": {"selection_status": "BASELINE_RETAINED"},
            "model_a_output": {"policy_matrix": [[0.2, 0.2, 0.2, 0.2]]},
            "model_b_output": {"selected": {"product_metrics": [{"product_id": "P001", "dte_index": 0}]}},
        }
        self.assertEqual(recommendations._dashboard_items(result), [])

    def test_zero_ai_discount_matches_no_discount_and_is_hidden(self):
        result = {
            "request_id": "S01-201", "store_id": "S01",
            "dashboard": {"items": [{
                "product_id": "P001", "dte_index": 3,
                "ai_discount_rate": 0.0, "standard_discount_rate": 0.0,
                "ai_expected_profit": 0.0, "no_discount_expected_profit": 475.0,
                "standard_markdown_expected_profit": 475.0,
            }]},
        }
        self.assertEqual(recommendations._dashboard_items(result), [])
        self.assertEqual(recommendations._skipped_dashboard_items(result), [])
        inventory_decisions = recommendations._skipped_dashboard_items(result, include_plain_no_discount=True)
        self.assertEqual(len(inventory_decisions), 1)
        self.assertEqual(inventory_decisions[0]["reason_code"], "NO_DISCOUNT_RECOMMENDED")

    def test_profitable_ai_candidate_moves_to_approval_queue(self):
        result = {
            "request_id": "S01-202", "store_id": "S01",
            "dashboard": {"items": [{
                "product_id": "P001", "dte_index": 0,
                "ai_discount_rate": 0.11, "standard_discount_rate": 0.40,
                "ai_expected_profit": 1.0, "no_discount_expected_profit": -15380.0,
                "standard_markdown_expected_profit": -20000.0,
                "approval_required": False, "type": "skip",
            }]},
        }
        pending = recommendations._dashboard_items(result)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["recommended_rate"], 0.11)
        self.assertEqual(recommendations._skipped_dashboard_items(result), [])

    def test_missing_ai_metrics_are_not_treated_as_zero_profit(self):
        result = {
            "request_id": "S02-203", "store_id": "S02",
            "dashboard": {"items": [{
                "product_id": "P003", "dte_index": 0,
                "ai_discount_rate": 0.19, "standard_discount_rate": 0.40,
                "decision": "STANDARD_MARKDOWN", "approval_required": False,
            }]},
            "model_b_output": {
                "no_discount": {"product_metrics": [{"product_id": "P003", "dte_index": 0, "expected_profit": -100.0}]},
                "standard_markdown": {"product_metrics": [{"product_id": "P003", "dte_index": 0, "expected_profit": -120.0}]},
                "selected": {"product_metrics": [{"product_id": "P003", "dte_index": 0, "expected_profit": -120.0}]},
            },
        }
        self.assertEqual(recommendations._dashboard_items(result), [])

    def test_skip_reason_uses_displayed_profit_comparison(self):
        result = {
            "request_id": "S02-204", "store_id": "S02",
            "dashboard": {"items": [{
                "product_id": "P001", "dte_index": 0,
                "ai_discount_rate": 0.01, "standard_discount_rate": 0.40,
                "ai_expected_profit": -215032.0,
                "standard_markdown_expected_profit": -216134.0,
                "no_discount_expected_profit": -215024.0,
                "reason_code": "STANDARD_MARKDOWN_OUTPERFORMED_AI",
            }]},
        }
        skipped = recommendations._skipped_dashboard_items(result)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason_code"], "NO_DISCOUNT_OUTPERFORMED_MARKDOWN_AND_AI")
        self.assertEqual(skipped[0]["selected_discount_rate"], 0.0)
        self.assertIn("할인 미적용 정책", skipped[0]["reason"])

    def test_skip_reason_keeps_standard_when_standard_profit_is_best(self):
        result = {
            "request_id": "S02-205", "store_id": "S02",
            "dashboard": {"items": [{
                "product_id": "P001", "dte_index": 0,
                "ai_discount_rate": 0.10, "standard_discount_rate": 0.40,
                "ai_expected_profit": -120.0,
                "standard_markdown_expected_profit": -90.0,
                "no_discount_expected_profit": -100.0,
            }]},
        }
        skipped = recommendations._skipped_dashboard_items(result)
        self.assertEqual(skipped[0]["reason_code"], "STANDARD_MARKDOWN_OUTPERFORMED_AI")
        self.assertEqual(skipped[0]["selected_discount_rate"], 0.40)

    def test_approval_stages_keep_manager_items_out_of_rds_pending_list(self):
        result = {
            "request_id": "S01-200",
            "store_id": "S01",
            "acceptance": {"selection_status": "OPTIMIZED_SELECTED"},
            "dashboard": {"items": [
                {"product_id": "P001", "dte_index": 0, "approval_required": True, "selected_discount_rate": 0.10},
                {"product_id": "P002", "dte_index": 1, "approval_required": True, "selected_discount_rate": 0.30},
            ]},
            "approved_items": [{"product_id": "P001", "dte_index": 0, "approved_rate": 0.10}],
            "manager_pending_items": [{"product_id": "P002", "dte_index": 1, "approved_rate": 0.30}],
        }
        self.assertEqual(recommendations._pending_dashboard_items(result), [])
        manager_items = recommendations._manager_pending_dashboard_items(result)
        self.assertEqual([(item["product_id"], item["approved_rate"]) for item in manager_items], [("P002", 0.30)])


if __name__ == "__main__":
    unittest.main()
