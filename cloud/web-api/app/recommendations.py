from __future__ import annotations

import json
import os
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
        is_optimized = _selection_status(result) == "OPTIMIZED_SELECTED"
        status = "PENDING" if is_optimized else "REJECTED"
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


def _dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard = result.get("dashboard") or {}
    if "items" in dashboard:
        if _selection_status(result) != "OPTIMIZED_SELECTED":
            return []
        selected_metrics = {
            (str(row["product_id"]), int(row["dte_index"])): row
            for row in ((result.get("model_b_output") or {}).get("selected") or {}).get("product_metrics") or []
        }
        return [
            {
                "request_id": result["request_id"],
                "store_id": result["store_id"],
                **selected_metrics.get((str(row["product_id"]), int(row["dte_index"])), {}),
                **row,
                "recommended_rate": float(row["selected_discount_rate"]),
            }
            for row in dashboard["items"]
            if row.get("approval_required")
        ]
    if (result.get("acceptance") or {}).get("selection_status") != "OPTIMIZED_SELECTED":
        return []
    policy = _policy_rates(result)
    metrics = ((result.get("model_b_output") or {}).get("selected") or {}).get("product_metrics") or []
    return [
        {
            "request_id": result["request_id"],
            "store_id": result["store_id"],
            **row,
            "recommended_rate": policy.get((row["product_id"], int(row["dte_index"])), 0.0),
        }
        for row in metrics
        if policy.get((row["product_id"], int(row["dte_index"])), 0.0) > 0
    ]


_SKIP_REASONS = {
    "AI_DISCOUNT_AT_OR_BELOW_3_PERCENT": "AI 할인 효과는 있으나 3% 이하라 승인 대기열에는 올리지 않았습니다.",
    "STANDARD_MARKDOWN_OUTPERFORMED_AI": "표준 유통기한 할인안이 AI 할인안보다 더 적합합니다.",
    "NO_DISCOUNT_OUTPERFORMED_MARKDOWN_AND_AI": "할인 없이 판매하는 편이 표준 할인과 AI 할인보다 적합합니다.",
    "FINAL_POLICY_NOT_BETTER_THAN_BOTH_CONTROLS": "개별 AI 후보는 있었지만 점포 전체 기준정책보다 우수하지 않아 승인 대상에서 제외했습니다.",
}


def _skipped_dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard = result.get("dashboard") or {}
    if "items" not in dashboard:
        return []
    optimized = _selection_status(result) == "OPTIMIZED_SELECTED"
    items = []
    for row in dashboard["items"]:
        if row.get("approval_required") and optimized:
            continue
        item = dict(row)
        if row.get("approval_required"):
            item.update({
                "approval_required": False,
                "type": "skip",
                "reason_code": "FINAL_POLICY_NOT_BETTER_THAN_BOTH_CONTROLS",
                "selected_discount_rate": float(row["standard_discount_rate"])
                if float(row["standard_markdown_score_7_to_3"]) > 0 else 0.0,
            })
        items.append({
            "request_id": result["request_id"],
            "store_id": result["store_id"],
            **item,
            "reason": _SKIP_REASONS.get(str(item.get("reason_code")), "AI 추천 조건을 충족하지 않았습니다."),
        })
    return items


@router.get("/recommendations")
def recommendations(store_id: str) -> list[dict[str, Any]]:
    _drain_result_queue()
    with connect_rds() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json
                FROM pricing_ops.pricing_recommendation
                WHERE store_id = %s AND status = 'PENDING'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _dashboard_items(row["result_json"])]


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
            if recommendation["status"] != "PENDING":
                raise HTTPException(status_code=409, detail="이미 처리된 추천입니다.")

            items = approval.items or _recommended_items(recommendation["result_json"])
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
                        recommendation["store_id"],
                        item.product_id,
                        recommendation["store_id"],
                        item.dte_index,
                    ),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(
                        status_code=409,
                        detail=f"현재 재고에서 {item.product_id}/DTE-{item.dte_index} 대상을 찾지 못했습니다.",
                    )
            cursor.execute(
                """
                UPDATE pricing_ops.pricing_recommendation
                SET status = 'APPROVED', decided_at = now()
                WHERE request_id = %s
                """,
                (request_id,),
            )
    return {"request_id": request_id, "status": "APPROVED", "updated_items": len(items)}


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
