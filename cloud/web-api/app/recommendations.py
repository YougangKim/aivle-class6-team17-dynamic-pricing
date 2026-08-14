from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from typing import Any

import boto3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect_rds


router = APIRouter(prefix="/api")


class ApprovalItem(BaseModel):
    product_id: str = Field(pattern=r"^P\d{3}$")
    dte_index: int = Field(ge=0, le=3)
    approved_rate: float = Field(ge=0, le=0.40)


class ApprovalRequest(BaseModel):
    items: list[ApprovalItem] = Field(default_factory=list)
    finalize: bool = True


class RepriceItem(BaseModel):
    product_id: str = Field(pattern=r"^P\d{3}$")
    dte_index: int = Field(ge=0, le=3)
    previous_rate: float = Field(ge=0, le=0.40)
    reason_code: str
    memo: str = ""
    round: int = Field(ge=1, le=2)


class RepriceRequest(BaseModel):
    store_id: str = Field(pattern=r"^S0[1-3]$")
    items: list[RepriceItem] = Field(min_length=1)


REPRICE_CUTS = {
    "rate_too_high": 0.06,
    "stock_ok": 0.10,
    "promo_overlap": 0.12,
    "margin_guard": 0.15,
    "etc": 0.05,
}
KST = timezone(timedelta(hours=9))


def _result_from_message(body: str) -> dict[str, Any]:
    result = json.loads(body)
    output = result.get("output") if isinstance(result, dict) else None
    if isinstance(output, str):
        return json.loads(output)
    return output if isinstance(output, dict) else result


def _selection_status(result: dict[str, Any]) -> str:
    acceptance = result.get("acceptance") or {}
    if acceptance.get("selection_status"):
        return str(acceptance["selection_status"])
    dashboard = result.get("dashboard") or {}
    if "items" in dashboard:
        return "OPTIMIZED_SELECTED" if any(item.get("approval_required") for item in dashboard["items"]) else "BASELINE_RETAINED"
    return str((result.get("acceptance") or {}).get("selection_status") or "BASELINE_RETAINED")


def _drain_result_queue() -> None:
    queue_url = os.getenv("RESULT_QUEUE_URL", "").strip()
    if not queue_url:
        return
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    for message in response.get("Messages", []):
        result = _result_from_message(message["Body"])
        status = "PENDING" if _dashboard_items(result) else "REJECTED"
        with connect_rds() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO pricing_ops.pricing_recommendation
                        (request_id, store_id, result_json, status, decided_at)
                    VALUES (%s, %s, %s::jsonb, %s,
                            CASE WHEN %s = 'PENDING' THEN NULL ELSE now() END)
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id
                    """,
                    (result["request_id"], result["store_id"], json.dumps(result), status, status),
                )
                if cursor.fetchone():
                    cursor.execute(
                        """
                        UPDATE pricing_ops.pricing_recommendation
                        SET status = 'REJECTED', decided_at = now()
                        WHERE store_id = %s
                          AND status = 'PENDING'
                          AND request_id <> %s
                        """,
                        (result["store_id"], result["request_id"]),
                    )
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])


def _policy_rates(result: dict[str, Any]) -> dict[tuple[str, int], float]:
    dashboard = result.get("dashboard") or {}
    if "items" in dashboard:
        return {
            (str(row["product_id"]), int(row["dte_index"])): float(row["selected_discount_rate"])
            for row in dashboard["items"]
            if row.get("approval_required")
        }
    model_a = result.get("model_a_output") or {}
    policy_long = model_a.get("policy_long") or []
    if policy_long:
        return {
            (row["product_id"], int(row["dte_index"])): float(row["discount_rate"])
            for row in policy_long
        }
    return {
        (f"P{product_index + 1:03d}", dte_index): float(rate)
        for product_index, row in enumerate(model_a.get("policy_matrix") or [])
        for dte_index, rate in enumerate(row)
    }


def _product_metrics(result: dict[str, Any], policy_name: str) -> dict[tuple[str, int], dict[str, Any]]:
    evaluation = ((result.get("model_b_output") or {}).get(policy_name) or {})
    return {
        (str(row["product_id"]), int(row["dte_index"])): row
        for row in evaluation.get("product_metrics") or []
    }


def _with_comparison(result: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    key = (str(item["product_id"]), int(item["dte_index"]))
    selected = _product_metrics(result, "selected").get(key, {})
    no_discount = _product_metrics(result, "no_discount").get(key, {})
    standard = _product_metrics(result, "standard_markdown").get(key, {})
    ai = _product_metrics(result, "ai_candidate").get(key, {})
    if not ai and (item.get("decision") == "AI" or item.get("approval_required")):
        ai = selected
    ai_rate = float(item.get("ai_discount_rate") or 0.0)
    no_discount_profit = float(item.get("no_discount_expected_profit") or no_discount.get("expected_profit") or 0.0)
    raw_ai_profit = item.get("ai_expected_profit") if item.get("ai_expected_profit") is not None else ai.get("expected_profit")
    ai_profit = no_discount_profit if ai_rate == 0.0 else (float(raw_ai_profit) if raw_ai_profit is not None else None)
    return {
        **selected,
        **item,
        "comparison": {
            "no_discount": {
                "discount_rate": 0.0,
                **no_discount,
                "expected_profit": no_discount_profit,
            },
            "standard_markdown": {
                "discount_rate": float(item.get("standard_discount_rate") or 0.0),
                **standard,
                "expected_profit": float(item.get("standard_markdown_expected_profit") or standard.get("expected_profit") or 0.0),
            },
            "ai_candidate": {
                "discount_rate": ai_rate,
                **ai,
                "score_7_to_3": float(item.get("ai_score_7_to_3") or 0.0),
                "expected_profit": ai_profit,
            },
            "selected": {
                "discount_rate": float(item.get("selected_discount_rate") or 0.0),
                "decision": item.get("decision"),
                "score_7_to_3": float(item.get("score_7_to_3") or 0.0),
                **selected,
            },
        },
    }


def _ai_outperforms_controls(result: dict[str, Any], row: dict[str, Any]) -> bool:
    key = (str(row["product_id"]), int(row["dte_index"]))
    no_discount = _product_metrics(result, "no_discount").get(key, {})
    standard = _product_metrics(result, "standard_markdown").get(key, {})
    ai = _product_metrics(result, "ai_candidate").get(key, {})
    if not ai and (row.get("decision") == "AI" or row.get("approval_required")):
        ai = _product_metrics(result, "selected").get(key, {})
    has_profit_comparison = any(
        name in row
        for name in ("ai_expected_profit", "no_discount_expected_profit", "standard_markdown_expected_profit")
    ) or any("expected_profit" in metric for metric in (ai, no_discount, standard))
    if not has_profit_comparison:
        return bool(row.get("approval_required"))
    no_discount_profit = float(row.get("no_discount_expected_profit") or no_discount.get("expected_profit") or 0.0)
    ai_rate = float(row.get("ai_discount_rate") or 0.0)
    raw_ai_profit = row.get("ai_expected_profit") if row.get("ai_expected_profit") is not None else ai.get("expected_profit")
    if ai_rate > 0.0 and raw_ai_profit is None:
        return False
    ai_profit = no_discount_profit if ai_rate == 0.0 else float(raw_ai_profit)
    standard_profit = float(row.get("standard_markdown_expected_profit") or standard.get("expected_profit") or 0.0)
    return ai_profit > max(no_discount_profit, standard_profit)


def _plain_no_discount_is_best(result: dict[str, Any], row: dict[str, Any]) -> bool:
    if float(row.get("ai_discount_rate") or 0.0) != 0.0:
        return False
    key = (str(row["product_id"]), int(row["dte_index"]))
    no_discount = _product_metrics(result, "no_discount").get(key, {})
    standard = _product_metrics(result, "standard_markdown").get(key, {})
    no_discount_profit = float(row.get("no_discount_expected_profit") or no_discount.get("expected_profit") or 0.0)
    standard_profit = float(row.get("standard_markdown_expected_profit") or standard.get("expected_profit") or 0.0)
    return no_discount_profit >= standard_profit


def _dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard = result.get("dashboard") or {}
    if "items" in dashboard:
        return [
            _with_comparison(result, {
                "request_id": result["request_id"],
                "store_id": result["store_id"],
                **row,
                "selected_discount_rate": float(row.get("ai_discount_rate") or 0.0),
                "recommended_rate": float(row.get("ai_discount_rate") or 0.0),
                "approval_required": True,
                "decision": "AI",
                "type": "ok",
                "reason_code": "AI_RECOMMENDED",
            })
            for row in dashboard["items"]
            if _ai_outperforms_controls(result, row)
        ]
    if (result.get("acceptance") or {}).get("selection_status") != "OPTIMIZED_SELECTED":
        return []
    policy = _policy_rates(result)
    metrics = ((result.get("model_b_output") or {}).get("selected") or {}).get("product_metrics") or []
    return [
        _with_comparison(result, {
            "request_id": result["request_id"],
            "store_id": result["store_id"],
            **row,
            "recommended_rate": policy.get((row["product_id"], int(row["dte_index"])), 0.0),
        })
        for row in metrics
        if policy.get((row["product_id"], int(row["dte_index"])), 0.0) > 0
    ]


_SKIP_REASONS = {
    "AI_DISCOUNT_AT_OR_BELOW_3_PERCENT": "AI 예상이익이 비교 정책보다 높지 않아 승인 대상에서 제외했습니다.",
    "STANDARD_MARKDOWN_OUTPERFORMED_AI": "표준 유통기한 할인안이 AI 할인안보다 더 적합합니다.",
    "NO_DISCOUNT_OUTPERFORMED_MARKDOWN_AND_AI": "할인 미적용 정책의 예상이익이 마감 할인과 AI 할인보다 높습니다.",
    "FINAL_POLICY_NOT_BETTER_THAN_BOTH_CONTROLS": "개별 AI 후보는 있었지만 점포 전체 기준정책보다 우수하지 않아 승인 대상에서 제외했습니다.",
}


def _comparison_reason_code(result: dict[str, Any], row: dict[str, Any]) -> str:
    comparison = _with_comparison(result, row)["comparison"]
    ai_profit = comparison["ai_candidate"].get("expected_profit")
    no_discount_profit = comparison["no_discount"].get("expected_profit")
    standard_profit = comparison["standard_markdown"].get("expected_profit")
    profits = {
        "AI": float(ai_profit) if ai_profit is not None else float("-inf"),
        "NO_DISCOUNT": float(no_discount_profit),
        "STANDARD_MARKDOWN": float(standard_profit),
    }
    if profits["NO_DISCOUNT"] >= max(profits["AI"], profits["STANDARD_MARKDOWN"]):
        return "NO_DISCOUNT_OUTPERFORMED_MARKDOWN_AND_AI"
    if profits["STANDARD_MARKDOWN"] >= max(profits["AI"], profits["NO_DISCOUNT"]):
        return "STANDARD_MARKDOWN_OUTPERFORMED_AI"
    return "FINAL_POLICY_NOT_BETTER_THAN_BOTH_CONTROLS"


def _skipped_dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard = result.get("dashboard") or {}
    if "items" not in dashboard:
        return []
    items = []
    for row in dashboard["items"]:
        if _ai_outperforms_controls(result, row):
            continue
        if _plain_no_discount_is_best(result, row):
            continue
        reason_code = _comparison_reason_code(result, row)
        item = {
            **row,
            "approval_required": False,
            "type": "skip",
            "reason_code": reason_code,
            "selected_discount_rate": float(row.get("standard_discount_rate") or 0.0)
            if reason_code == "STANDARD_MARKDOWN_OUTPERFORMED_AI" else 0.0,
        }
        items.append(_with_comparison(result, {
            "request_id": result["request_id"],
            "store_id": result["store_id"],
            **item,
            "reason": _SKIP_REASONS[reason_code],
        }))
    return items


def _approved_dashboard_items(result: dict[str, Any], decided_at: Any) -> list[dict[str, Any]]:
    approved = result.get("approved_items") or []
    rates = {
        (str(item["product_id"]), int(item["dte_index"])): float(item["approved_rate"])
        for item in approved
    }
    if not rates:
        return []
    approved_at = decided_at.isoformat() if decided_at else None
    return [
        {
            **item,
            "approved_rate": rates[(str(item["product_id"]), int(item["dte_index"]))],
            "approved_at": approved_at,
        }
        for item in _dashboard_items(result)
        if (str(item["product_id"]), int(item["dte_index"])) in rates
    ]


def _approval_key(item: dict[str, Any]) -> tuple[str, int]:
    return str(item["product_id"]), int(item["dte_index"])


def _approval_rows(items: list[ApprovalItem]) -> list[dict[str, Any]]:
    return [
        {
            "product_id": item.product_id,
            "dte_index": item.dte_index,
            "approved_rate": item.approved_rate,
        }
        for item in items
    ]


def _merge_approval_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {_approval_key(item): item for item in existing}
    merged.update({_approval_key(item): item for item in incoming})
    return list(merged.values())


def _reprice_cap(item: RepriceItem) -> float:
    cut = REPRICE_CUTS.get(item.reason_code, REPRICE_CUTS["etc"])
    return max(0.0, round(item.previous_rate - cut, 2))


def _candidate_matrix(base: list[list[float]], product_id: str, dte_index: int, rate: float) -> list[list[float]]:
    matrix = deepcopy(base)
    matrix[int(product_id[1:]) - 1][dte_index] = rate
    return matrix


def _model_state(cursor: Any, store_id: str) -> tuple[str, dict[str, Any]]:
    cursor.execute(
        """
        WITH latest AS (
            SELECT MAX(inventory_date) AS inventory_date
            FROM inventory.inventory
            WHERE store_id = %s
        )
        SELECT i.product_id,
               CASE WHEN i.days_to_expiry <= 0 THEN 0
                    WHEN i.days_to_expiry >= 3 THEN 3
                    ELSE i.days_to_expiry END AS dte_index,
               SUM(i.available_qty) AS available_qty,
               SUM(i.current_stock_qty) AS current_stock_qty,
               SUM(i.reserved_qty) AS reserved_qty,
               AVG(i.freshness_score) AS freshness_score,
               AVG(i.discount_rate) AS previous_discount_rate,
               MAX(i.unit_cost) AS unit_cost,
               MAX(i.unit_price) AS regular_price,
               MAX(i.inventory_date) AS inventory_date
        FROM inventory.inventory i
        JOIN latest l ON i.inventory_date = l.inventory_date
        WHERE i.store_id = %s
          AND i.product_id BETWEEN 'P001' AND 'P038'
        GROUP BY i.product_id,
                 CASE WHEN i.days_to_expiry <= 0 THEN 0
                      WHEN i.days_to_expiry >= 3 THEN 3
                      ELSE i.days_to_expiry END
        ORDER BY i.product_id, dte_index
        """,
        (store_id, store_id),
    )
    rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="재평가할 현재 재고가 없습니다.")
    snapshot_date = rows[0]["inventory_date"]
    if isinstance(snapshot_date, datetime):
        snapshot_date = snapshot_date.date()
    if not isinstance(snapshot_date, date):
        snapshot_date = date.fromisoformat(str(snapshot_date))
    current_time = datetime.combine(snapshot_date, datetime.min.time(), KST).replace(hour=18).isoformat()
    cells = []
    for row in rows:
        previous_rate = float(row["previous_discount_rate"] or 0)
        if previous_rate > 1:
            previous_rate /= 100
        cells.append({
            "store_id": store_id,
            "product_id": row["product_id"],
            "product_index": int(row["product_id"][1:]) - 1,
            "dte_index": int(row["dte_index"]),
            "available_qty": float(row["available_qty"] or 0),
            "current_stock_qty": float(row["current_stock_qty"] or 0),
            "reserved_qty": float(row["reserved_qty"] or 0),
            "freshness_score": float(row["freshness_score"] or 0.6),
            "previous_discount_rate": previous_rate,
            "active_inventory_flag": int(float(row["available_qty"] or 0) > 0),
            "unit_cost": float(row["unit_cost"] or 0),
            "regular_price": float(row["regular_price"] or 0),
        })
    return current_time, {"source": "RDS_REPRICE_SNAPSHOT", "cells": cells}


def _invoke_model_b(request_id: str, store_id: str, current_time: str, current_state: dict[str, Any], matrix: list[list[float]], iteration: int) -> dict[str, Any]:
    function_name = os.getenv("MODEL_B_FUNCTION_NAME", "aivle-dev-lambda-model-b-candidate")
    payload = {
        "request_id": request_id,
        "store_id": store_id,
        "current_time": current_time,
        "current_state": current_state,
        "options": {},
        "policy": {
            "request_id": request_id,
            "store_id": store_id,
            "policy_iteration": iteration,
            "policy_shape": [38, 4],
            "policy_matrix": matrix,
            "policy_source": "MANAGER_REPRICE_CONSTRAINT",
            "candidate_ready": True,
        },
    }
    response = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "ap-northeast-2")).invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    result = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise RuntimeError(result.get("errorMessage") or "Model B 재평가에 실패했습니다.")
    return result


def _target_metric(result: dict[str, Any], product_id: str, dte_index: int) -> dict[str, Any]:
    return next(
        (row for row in result.get("product_metrics") or []
         if row.get("product_id") == product_id and int(row.get("dte_index", -1)) == dte_index),
        {},
    )


def _pending_dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    handled = {
        _approval_key(item)
        for item in (
            (result.get("approved_items") or [])
            + (result.get("manager_pending_items") or [])
            + (result.get("reprice_items") or [])
        )
    }
    return [item for item in _dashboard_items(result) if _approval_key(item) not in handled]


def _reprice_dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    originals = {_approval_key(item): item for item in _dashboard_items(result)}
    return [
        {
            **originals[_approval_key(reprice)],
            "rate": int(reprice["previous_rate"]),
            "round": int(reprice["round"]),
            "reprice": reprice,
        }
        for reprice in result.get("reprice_items") or []
        if _approval_key(reprice) in originals
    ]


def _manager_pending_dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    rates = {
        _approval_key(item): float(item["approved_rate"])
        for item in result.get("manager_pending_items") or []
    }
    return [
        {**item, "approved_rate": rates[_approval_key(item)]}
        for item in _dashboard_items(result)
        if _approval_key(item) in rates
    ]


@router.get("/recommendations")
def recommendations(store_id: str) -> list[dict[str, Any]]:
    _drain_result_queue()
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _pending_dashboard_items(row["result_json"])]


@router.get("/recommendations/skipped")
def skipped_recommendations(store_id: str) -> list[dict[str, Any]]:
    _drain_result_queue()
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _skipped_dashboard_items(row["result_json"])]


@router.get("/recommendations/completed")
def completed_recommendations(store_id: str) -> list[dict[str, Any]]:
    _drain_result_queue()
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json, decided_at
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s
                  AND result_json ? 'approved_items'
                ORDER BY COALESCE(decided_at, created_at) DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _approved_dashboard_items(row["result_json"], row["decided_at"])]


@router.get("/recommendations/manager-pending")
def manager_pending_recommendations(store_id: str) -> list[dict[str, Any]]:
    _drain_result_queue()
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s
                  AND status = 'PENDING'
                  AND jsonb_array_length(COALESCE(result_json->'manager_pending_items', '[]'::jsonb)) > 0
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _manager_pending_dashboard_items(row["result_json"])]


@router.get("/recommendations/reprice-pending")
def reprice_pending_recommendations(store_id: str) -> list[dict[str, Any]]:
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s
                  AND jsonb_array_length(COALESCE(result_json->'reprice_items', '[]'::jsonb)) > 0
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _reprice_dashboard_items(row["result_json"])]


def _recommended_items(result: dict[str, Any]) -> list[ApprovalItem]:
    return [
        ApprovalItem(
            product_id=product_id,
            dte_index=dte_index,
            approved_rate=rate,
        )
        for (product_id, dte_index), rate in _policy_rates(result).items()
        if rate > 0
    ]


def _apply_inventory_rates(cursor: Any, store_id: str, items: list[ApprovalItem]) -> None:
    for item in items:
        cursor.execute(
            """
            UPDATE inventory.inventory
            SET discount_rate = %s,
                discount_price = ROUND(unit_price * (1 - %s))
            WHERE store_id = %s
              AND product_id = %s
              AND inventory_date = (
                  SELECT MAX(inventory_date)
                  FROM inventory.inventory
                  WHERE store_id = %s
              )
              AND CASE
                  WHEN days_to_expiry <= 0 THEN 0
                  WHEN days_to_expiry >= 3 THEN 3
                  ELSE days_to_expiry
              END = %s
            """,
            (
                item.approved_rate * 100,
                item.approved_rate,
                store_id,
                item.product_id,
                store_id,
                item.dte_index,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail=f"현재 재고에서 {item.product_id}/DTE-{item.dte_index} 대상을 찾지 못했습니다.",
            )


@router.post("/recommendations/{request_id}/approve")
def approve(request_id: str, approval: ApprovalRequest) -> dict[str, Any]:
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT store_id, result_json, status
                FROM pricing_ops.pricing_recommendation
                WHERE request_id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            recommendation = cursor.fetchone()
            if not recommendation:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            if recommendation["status"] != "PENDING" and not _dashboard_items(recommendation["result_json"]):
                raise HTTPException(status_code=409, detail="이미 처리된 추천입니다.")

            items = approval.items or _recommended_items(recommendation["result_json"])
            _apply_inventory_rates(cursor, recommendation["store_id"], items)
            result = recommendation["result_json"]
            approved_items = _merge_approval_rows(result.get("approved_items") or [], _approval_rows(items))
            manager_pending_items = [
                item for item in result.get("manager_pending_items") or []
                if _approval_key(item) not in {_approval_key(item) for item in _approval_rows(items)}
            ]
            result["approved_items"] = approved_items
            result["manager_pending_items"] = manager_pending_items
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET status = CASE WHEN %s THEN 'APPROVED' ELSE 'PENDING' END,
                    decided_at = CASE WHEN %s THEN now() ELSE decided_at END,
                    result_json = %s::jsonb
                WHERE request_id = %s
                """,
                (approval.finalize, approval.finalize, json.dumps(result), request_id),
            )
    return {
        "request_id": request_id,
        "status": "APPROVED" if approval.finalize else "PENDING",
        "updated_items": len(items),
    }


@router.post("/recommendations/{request_id}/manager-request")
def request_manager_approval(request_id: str, approval: ApprovalRequest) -> dict[str, Any]:
    if not approval.items:
        raise HTTPException(status_code=400, detail="점장 승인 요청 상품이 없습니다.")
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json, status
                FROM pricing_ops.pricing_recommendation
                WHERE request_id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            recommendation = cursor.fetchone()
            if not recommendation:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            if recommendation["status"] != "PENDING" and not _dashboard_items(recommendation["result_json"]):
                raise HTTPException(status_code=409, detail="이미 처리된 추천입니다.")
            result = recommendation["result_json"]
            result["manager_pending_items"] = _merge_approval_rows(
                result.get("manager_pending_items") or [],
                _approval_rows(approval.items),
            )
            requested_keys = {_approval_key(item) for item in _approval_rows(approval.items)}
            result["reprice_items"] = [
                item for item in result.get("reprice_items") or []
                if _approval_key(item) not in requested_keys
            ]
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET result_json = %s::jsonb,
                    status = 'PENDING',
                    decided_at = NULL
                WHERE request_id = %s
                """,
                (json.dumps(result), request_id),
            )
    return {"request_id": request_id, "status": "MANAGER_PENDING", "requested_items": len(approval.items)}


@router.post("/recommendations/{request_id}/manager-approve")
def approve_by_manager(request_id: str, approval: ApprovalRequest) -> dict[str, Any]:
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT store_id, result_json, status
                FROM pricing_ops.pricing_recommendation
                WHERE request_id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            recommendation = cursor.fetchone()
            if not recommendation:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            if recommendation["status"] != "PENDING":
                raise HTTPException(status_code=409, detail="이미 처리된 추천입니다.")
            result = recommendation["result_json"]
            pending_rates = {
                _approval_key(item): float(item["approved_rate"])
                for item in result.get("manager_pending_items") or []
            }
            requested = approval.items or [
                ApprovalItem(product_id=product_id, dte_index=dte_index, approved_rate=rate)
                for (product_id, dte_index), rate in pending_rates.items()
            ]
            if not requested:
                raise HTTPException(status_code=409, detail="점장 최종 승인 대기 상품이 없습니다.")
            for item in requested:
                if pending_rates.get((item.product_id, item.dte_index)) != item.approved_rate:
                    raise HTTPException(status_code=409, detail="점장 승인 대기 중인 할인율과 일치하지 않습니다.")
            _apply_inventory_rates(cursor, recommendation["store_id"], requested)
            approved_items = _merge_approval_rows(result.get("approved_items") or [], _approval_rows(requested))
            approved_keys = {_approval_key(item) for item in _approval_rows(requested)}
            manager_pending_items = [
                item for item in result.get("manager_pending_items") or []
                if _approval_key(item) not in approved_keys
            ]
            result["approved_items"] = approved_items
            result["manager_pending_items"] = manager_pending_items
            final = not manager_pending_items and not result.get("reprice_items")
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET status = CASE WHEN %s THEN 'APPROVED' ELSE 'PENDING' END,
                    decided_at = CASE WHEN %s THEN now() ELSE decided_at END,
                    result_json = %s::jsonb
                WHERE request_id = %s
                """,
                (final, final, json.dumps(result), request_id),
            )
    return {"request_id": request_id, "status": "APPROVED" if final else "PENDING", "updated_items": len(requested)}


@router.post("/recommendations/{request_id}/reprice")
def reprice(request_id: str, request: RepriceRequest) -> list[dict[str, Any]]:
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT store_id, result_json, status FROM pricing_ops.pricing_recommendation WHERE request_id = %s",
                (request_id,),
            )
            recommendation = cursor.fetchone()
            if not recommendation:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            if recommendation["store_id"] != request.store_id:
                raise HTTPException(status_code=409, detail="추천 결과의 점포가 일치하지 않습니다.")
            if recommendation["status"] != "PENDING":
                raise HTTPException(status_code=409, detail="대기 중인 추천만 반려할 수 있습니다.")
            result = recommendation["result_json"]
            base_matrix = (result.get("model_a_output") or {}).get("policy_matrix")
            if not isinstance(base_matrix, list) or len(base_matrix) != 38 or any(len(row) != 4 for row in base_matrix):
                raise HTTPException(status_code=409, detail="원본 전체 할인 정책을 찾을 수 없습니다.")
            current_time, current_state = _model_state(cursor, request.store_id)

    responses = []
    for item in request.items:
        cap = _reprice_cap(item)
        evaluation_id = f"{request_id}-reprice-{item.product_id}-{item.dte_index}-{item.round}"
        previous_metric = _product_metrics(result, "selected").get((item.product_id, item.dte_index))
        no_discount_metric = _product_metrics(result, "no_discount").get((item.product_id, item.dte_index), {})
        evaluated = _invoke_model_b(
            evaluation_id,
            request.store_id,
            current_time,
            current_state,
            _candidate_matrix(base_matrix, item.product_id, item.dte_index, cap),
            item.round,
        )
        metric = _target_metric(evaluated, item.product_id, item.dte_index)
        if not metric:
            raise HTTPException(status_code=502, detail=f"{item.product_id}의 Model B 상품별 결과가 없습니다.")
        responses.append({
            "request_id": request_id,
            "product_id": item.product_id,
            "dte_index": item.dte_index,
            "round": item.round,
            "status": "RESTAGED",
            "reason_code": item.reason_code,
            "memo": item.memo,
            "previous_rate": round(item.previous_rate * 100),
            "cap": round(cap * 100),
            "new_rate": round(cap * 100),
            "expected_profit": float(metric.get("expected_profit") or 0),
            "expected_sales_qty": float(metric.get("expected_sales_qty") or 0),
            "expected_waste_qty": float(metric.get("expected_waste_qty") or 0),
            "expected_waste_rate": float(metric.get("expected_waste_rate") or 0),
            "sell_through_rate": float(metric.get("sell_through_rate") or 0),
            "prob": round(float(metric.get("sell_through_rate") or 0) * 100),
            "no_discount_profit": float(no_discount_metric.get("expected_profit") or 0),
            "previous_policy_profit": None if previous_metric is None else float(previous_metric.get("expected_profit") or 0),
            "expected_gain": float(metric.get("expected_profit") or 0) - float(no_discount_metric.get("expected_profit") or 0),
            "gain_delta": 0 if previous_metric is None else float(metric.get("expected_profit") or 0) - float(previous_metric.get("expected_profit") or 0),
            "needs_manager": cap > 0.30,
        })

    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_json FROM pricing_ops.pricing_recommendation WHERE request_id = %s FOR UPDATE",
                (request_id,),
            )
            latest = cursor.fetchone()
            if not latest:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            result = latest["result_json"]
            keys = {(row["product_id"], int(row["dte_index"])) for row in responses}
            result["manager_pending_items"] = [
                row for row in result.get("manager_pending_items") or []
                if _approval_key(row) not in keys
            ]
            existing = {
                (row["product_id"], int(row["dte_index"])): row
                for row in result.get("reprice_items") or []
            }
            existing.update({(row["product_id"], int(row["dte_index"])): row for row in responses})
            result["reprice_items"] = list(existing.values())
            cursor.execute(
                "UPDATE pricing_ops.pricing_recommendation SET result_json = %s::jsonb WHERE request_id = %s",
                (json.dumps(result), request_id),
            )
    return responses


@router.post("/recommendations/{request_id}/reprice-approve")
def approve_reprice(request_id: str, approval: ApprovalRequest) -> dict[str, Any]:
    if not approval.items:
        raise HTTPException(status_code=400, detail="승인할 재추천 상품이 없습니다.")
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT store_id, result_json
                FROM pricing_ops.pricing_recommendation
                WHERE request_id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            recommendation = cursor.fetchone()
            if not recommendation:
                raise HTTPException(status_code=404, detail="추천 결과가 없습니다.")
            result = recommendation["result_json"]
            reprice_rates = {
                _approval_key(item): float(item["new_rate"]) / 100
                for item in result.get("reprice_items") or []
            }
            for item in approval.items:
                expected_rate = reprice_rates.get((item.product_id, item.dte_index))
                if expected_rate is None or abs(expected_rate - item.approved_rate) > 1e-9:
                    raise HTTPException(status_code=409, detail="저장된 재추천 할인율과 승인 요청이 일치하지 않습니다.")
                if item.approved_rate > 0.30:
                    raise HTTPException(status_code=409, detail="30% 초과 할인은 점장 승인이 필요합니다.")

            _apply_inventory_rates(cursor, recommendation["store_id"], approval.items)
            approved_rows = _approval_rows(approval.items)
            approved_keys = {_approval_key(item) for item in approved_rows}
            result["approved_items"] = _merge_approval_rows(
                result.get("approved_items") or [], approved_rows
            )
            result["reprice_items"] = [
                item for item in result.get("reprice_items") or []
                if _approval_key(item) not in approved_keys
            ]
            final = not result.get("manager_pending_items") and not result.get("reprice_items")
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET status = CASE WHEN %s THEN 'APPROVED' ELSE 'PENDING' END,
                    decided_at = CASE WHEN %s THEN now() ELSE decided_at END,
                    result_json = %s::jsonb
                WHERE request_id = %s
                """,
                (final, final, json.dumps(result), request_id),
            )
    return {
        "request_id": request_id,
        "status": "APPROVED" if final else "PENDING",
        "updated_items": len(approval.items),
    }


@router.post("/recommendations/{request_id}/reject")
def reject(request_id: str) -> dict[str, str]:
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET status = 'REJECTED', decided_at = now()
                WHERE request_id = %s AND status = 'PENDING'
                """,
                (request_id,),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="대기 중인 추천이 없습니다.")
    return {"request_id": request_id, "status": "REJECTED"}
