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


def _drain_result_queue() -> None:
    queue_url = os.getenv("RESULT_QUEUE_URL", "").strip()
    if not queue_url:
        return
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    for message in response.get("Messages", []):
        result = json.loads(message["Body"])
        if (result.get("acceptance") or {}).get("selection_status") == "OPTIMIZED_SELECTED":
            with connect_rds() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO pricing_ops.pricing_recommendation
                            (request_id, store_id, result_json)
                        VALUES (%s, %s, %s::jsonb)
                        ON CONFLICT (request_id) DO NOTHING
                        """,
                        (result["request_id"], result["store_id"], json.dumps(result)),
                    )
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])


def _dashboard_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    policy = {
        (row["product_id"], int(row["dte_index"])): float(row["discount_rate"])
        for row in ((result.get("model_a_output") or {}).get("policy_long") or [])
    }
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
                """,
                (store_id,),
            )
            rows = cursor.fetchall()
    return [item for row in rows for item in _dashboard_items(row["result_json"])]


def _recommended_items(result: dict[str, Any]) -> list[ApprovalItem]:
    return [
        ApprovalItem(
            product_id=row["product_id"],
            dte_index=int(row["dte_index"]),
            approved_rate=float(row["discount_rate"]),
        )
        for row in ((result.get("model_a_output") or {}).get("policy_long") or [])
        if row.get("active_inventory_flag") and float(row.get("discount_rate", 0)) > 0
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
