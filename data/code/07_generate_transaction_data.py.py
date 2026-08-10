"""
update_transaction_from_receipt.py

목적
----
최신 receipt_0803최종.csv를 기준으로 transaction.csv(구버전)를 재생성한다.
inventory_0803최종.csv, receipt_0803최종.csv는 절대 수정하지 않고 읽기 전용으로만 사용한다.

처리 규칙 요약
--------------
1. receipt_0803최종.csv 의 receipt_id 를 기준으로 transaction 을 1행씩 재집계한다.
2. 기존 transaction.csv 에 존재하던 receipt_id 는 기존 transaction_id 를 그대로 유지한다.
3. 기존 transaction.csv 에 없던 신규 receipt_id 는 "T" + receipt_id 숫자 suffix(9자리 zero-fill) 로
   transaction_id 를 생성한다. 예: REC105388 -> T000105388
4. 기존 transaction.csv 에는 있었지만 최신 receipt 에 더 이상 없는 receipt_id 는 삭제한다.
5. 무작위 샘플링, random seed 사용 없음. 100% 결정적(deterministic) 로직만 사용한다.

컬럼 생성 공식 (receipt_id 별 집계)
----------------------------------
- visitor_id / customer_id / store_id / transaction_date(=sale_date) /
  transaction_time(=sale_time) / transaction_datetime(=sale_datetime) /
  time_slot / payment_method : receipt_id 내 단일값 (nunique==1 검증)
- item_count       = receipt_id 별 행 수 (line_no 가 1부터 연속인지 별도 검증)
- total_quantity   = sum(quantity)
- gross_amount     = sum(quantity * unit_price)
- discount_amount  = sum(quantity * (unit_price - sale_unit_price))
- final_amount     = sum(line_amount)
  => gross_amount - discount_amount == final_amount 가 항상 성립해야 함

실행 방법 (로컬 / Colab 공통)
-----------------------------
경로 변수(INVENTORY_PATH, RECEIPT_PATH, OLD_TRANSACTION_PATH, OUTPUT_PATH)만
환경에 맞게 수정한 뒤 스크립트를 실행하면 된다.
"""

import sys
import pandas as pd
import numpy as np

# ------------------------------------------------------------------
# 0. 경로 설정 (환경에 맞게 이 부분만 수정)
# ------------------------------------------------------------------
INVENTORY_PATH = "inventory_0803최종.csv"
RECEIPT_PATH = "receipt_0803최종.csv"
OLD_TRANSACTION_PATH = "transaction.csv"
OUTPUT_PATH = "transaction_0803최종.csv"

# 기존 transaction 컬럼 순서 (절대 변경하지 않음)
TRANSACTION_COLUMNS = [
    "transaction_id",
    "receipt_id",
    "visitor_id",
    "customer_id",
    "store_id",
    "transaction_date",
    "transaction_time",
    "transaction_datetime",
    "time_slot",
    "item_count",
    "total_quantity",
    "gross_amount",
    "discount_amount",
    "final_amount",
    "payment_method",
]

ID_STR_COLUMNS = ["transaction_id", "receipt_id", "visitor_id", "customer_id", "store_id"]


def load_inputs():
    """세 개의 입력 CSV를 문자열(dtype=str) 기준으로 로드한다.
    ID/날짜/시간 컬럼의 자릿수(leading zero 등)를 보존하기 위해 dtype=str 로 읽고,
    계산이 필요한 수치 컬럼만 이후 단계에서 개별적으로 형변환한다."""
    inventory = pd.read_csv(INVENTORY_PATH, dtype=str)
    receipt = pd.read_csv(RECEIPT_PATH, dtype=str)
    old_tx = pd.read_csv(OLD_TRANSACTION_PATH, dtype=str)
    return inventory, receipt, old_tx


def validate_receipt_internal(receipt: pd.DataFrame):
    """receipt 파일 자체의 line_no 연속성 및 receipt_id 내 단일값 컬럼을 검증한다.
    inventory/receipt 는 이미 Colab 에서 검증 완료된 파일이지만,
    transaction 생성 전 재확인하여 문제를 조기에 발견한다."""
    errors = []

    r = receipt.copy()
    r["line_no_int"] = r["line_no"].astype(int)

    # line_no 가 1부터 연속인지 확인
    line_no_lists = r.groupby("receipt_id")["line_no_int"].apply(lambda x: sorted(x.tolist()))
    bad_receipts = [
        rid for rid, lst in line_no_lists.items() if lst != list(range(1, len(lst) + 1))
    ]
    if bad_receipts:
        errors.append(f"line_no가 1부터 연속이지 않은 receipt_id {len(bad_receipts)}건: {bad_receipts[:5]}")

    # receipt_id 내 단일값이어야 하는 컬럼 확인
    single_cols = [
        "visitor_id", "customer_id", "store_id",
        "sale_date", "sale_time", "sale_datetime", "time_slot", "payment_method",
    ]
    nunique_df = r.groupby("receipt_id")[single_cols].nunique()
    for col in single_cols:
        bad = nunique_df.index[nunique_df[col] > 1].tolist()
        if bad:
            errors.append(f"{col} 이 receipt_id 내에서 다중값인 receipt_id {len(bad)}건: {bad[:5]}")

    return errors


def build_transactions(receipt: pd.DataFrame, old_tx: pd.DataFrame) -> pd.DataFrame:
    """receipt_0803최종.csv 를 receipt_id 기준으로 집계하여 transaction 을 재생성한다."""

    r = receipt.copy()
    r["quantity_num"] = r["quantity"].astype(float)
    r["unit_price_num"] = r["unit_price"].astype(float)
    r["sale_unit_price_num"] = r["sale_unit_price"].astype(float)
    r["line_amount_num"] = r["line_amount"].astype(float)

    r["line_gross"] = r["quantity_num"] * r["unit_price_num"]
    r["line_discount"] = r["quantity_num"] * (r["unit_price_num"] - r["sale_unit_price_num"])

    # 단일값 컬럼: first() 사용 (내부 검증에서 이미 nunique==1 확인)
    agg = r.groupby("receipt_id", sort=False).agg(
        visitor_id=("visitor_id", "first"),
        customer_id=("customer_id", "first"),
        store_id=("store_id", "first"),
        transaction_date=("sale_date", "first"),
        transaction_time=("sale_time", "first"),
        transaction_datetime=("sale_datetime", "first"),
        time_slot=("time_slot", "first"),
        payment_method=("payment_method", "first"),
        item_count=("line_no", "count"),
        total_quantity=("quantity_num", "sum"),
        gross_amount=("line_gross", "sum"),
        discount_amount=("line_discount", "sum"),
        final_amount=("line_amount_num", "sum"),
    ).reset_index()

    # 수치 컬럼은 정수로 캐스팅 (원본 receipt 값이 전부 정수이므로 반올림 오차 없음)
    for col in ["item_count", "total_quantity", "gross_amount", "discount_amount", "final_amount"]:
        agg[col] = agg[col].round().astype("int64")

    # -------------------------------------------------------------
    # transaction_id 매핑
    #   - 기존 receipt_id 는 기존 transaction_id 유지
    #   - 신규 receipt_id 는 T + 9자리 zero-fill 숫자 suffix
    # -------------------------------------------------------------
    old_map = dict(zip(old_tx["receipt_id"], old_tx["transaction_id"]))

    def make_transaction_id(receipt_id: str) -> str:
        if receipt_id in old_map:
            return old_map[receipt_id]
        suffix = receipt_id[3:]  # "REC" 제거
        return "T" + str(int(suffix)).zfill(9)

    agg["transaction_id"] = agg["receipt_id"].map(make_transaction_id)

    # 최종 컬럼 순서 정렬
    agg = agg[TRANSACTION_COLUMNS]

    # transaction_datetime 기준 정렬 (동일 시각 존재 가능 -> receipt_id 로 tie-break, 결정적 정렬)
    agg = agg.sort_values(
        by=["transaction_datetime", "receipt_id"], kind="mergesort"
    ).reset_index(drop=True)

    return agg


def run_validation(new_tx: pd.DataFrame, receipt: pd.DataFrame, old_tx: pd.DataFrame, inventory: pd.DataFrame):
    """A~F 검증 항목을 수행하고 결과 딕셔너리를 반환한다."""
    results = {}
    fail_details = {}

    receipt_unique_ids = set(receipt["receipt_id"].unique())
    old_ids = set(old_tx["receipt_id"])
    new_ids_only_from_receipt = receipt_unique_ids

    # ---------------- A. 구조 검증 ----------------
    a_cols_match = list(new_tx.columns) == TRANSACTION_COLUMNS
    a_colcount_match = len(new_tx.columns) == len(old_tx.columns)
    a_na = new_tx.isna().sum()
    a_no_missing = bool((a_na == 0).all())
    results["A_column_names_order_match"] = a_cols_match
    results["A_column_count_match"] = a_colcount_match
    results["A_no_missing_required"] = a_no_missing
    if not a_no_missing:
        fail_details["A_no_missing_required"] = a_na[a_na > 0].to_dict()

    # ---------------- B. receipt 연결 검증 ----------------
    b_rowcount = len(new_tx) == len(receipt_unique_ids)
    b_dup_receipt = new_tx["receipt_id"].duplicated().sum()
    b_missing_from_tx = receipt_unique_ids - set(new_tx["receipt_id"])
    b_extra_in_tx = set(new_tx["receipt_id"]) - receipt_unique_ids
    b_dup_tx_id = new_tx["transaction_id"].duplicated().sum()

    suffix_mismatch = []
    for tid, rid in zip(new_tx["transaction_id"], new_tx["receipt_id"]):
        if int(tid[1:]) != int(rid[3:]):
            suffix_mismatch.append((tid, rid))

    results["B_row_count_equals_receipt_unique"] = b_rowcount
    results["B_receipt_id_dup_in_tx"] = int(b_dup_receipt)
    results["B_receipt_not_in_tx"] = len(b_missing_from_tx)
    results["B_tx_receipt_not_in_receipt"] = len(b_extra_in_tx)
    results["B_transaction_id_dup"] = int(b_dup_tx_id)
    results["B_suffix_mismatch"] = len(suffix_mismatch)
    if b_missing_from_tx:
        fail_details["B_receipt_not_in_tx"] = list(b_missing_from_tx)[:5]
    if b_extra_in_tx:
        fail_details["B_tx_receipt_not_in_receipt"] = list(b_extra_in_tx)[:5]
    if suffix_mismatch:
        fail_details["B_suffix_mismatch"] = suffix_mismatch[:5]

    # ---------------- C. 고객·점포·시간 검증 ----------------
    r = receipt.copy()
    single_cols = {
        "visitor_id": "visitor_id",
        "customer_id": "customer_id",
        "store_id": "store_id",
        "transaction_date": "sale_date",
        "transaction_time": "sale_time",
        "transaction_datetime": "sale_datetime",
        "time_slot": "time_slot",
        "payment_method": "payment_method",
    }
    c_mismatch_total = 0
    c_mismatch_detail = {}
    r_first = r.groupby("receipt_id", sort=False)[list(set(single_cols.values()))].first()
    r_first = r_first.add_prefix("r_")
    tx_idx = new_tx.set_index("receipt_id")
    for tx_col, r_col in single_cols.items():
        merged = tx_idx[[tx_col]].join(r_first[["r_" + r_col]])
        mism = merged[tx_col].astype(str) != merged["r_" + r_col].astype(str)
        cnt = int(mism.sum())
        c_mismatch_total += cnt
        if cnt > 0:
            c_mismatch_detail[tx_col] = merged[mism].head(5).to_dict("index")
    results["C_customer_store_time_mismatch_total"] = c_mismatch_total
    if c_mismatch_detail:
        fail_details["C_mismatch_detail"] = c_mismatch_detail

    # ---------------- D. 수량 검증 ----------------
    r["quantity_num"] = r["quantity"].astype(float)
    item_count_check = r.groupby("receipt_id").size()
    qty_sum_check = r.groupby("receipt_id")["quantity_num"].sum()

    d_item_count_mismatch = int(
        (tx_idx["item_count"].astype(int) != item_count_check.reindex(tx_idx.index)).sum()
    )
    d_qty_mismatch = int(
        (tx_idx["total_quantity"].astype(int) != qty_sum_check.reindex(tx_idx.index).round().astype(int)).sum()
    )
    results["D_item_count_mismatch"] = d_item_count_mismatch
    results["D_total_quantity_mismatch"] = d_qty_mismatch

    # ---------------- E. 금액 검증 ----------------
    r["unit_price_num"] = r["unit_price"].astype(float)
    r["sale_unit_price_num"] = r["sale_unit_price"].astype(float)
    r["line_amount_num"] = r["line_amount"].astype(float)
    r["line_gross"] = r["quantity_num"] * r["unit_price_num"]
    r["line_discount"] = r["quantity_num"] * (r["unit_price_num"] - r["sale_unit_price_num"])

    gross_check = r.groupby("receipt_id")["line_gross"].sum().round().astype(int)
    discount_check = r.groupby("receipt_id")["line_discount"].sum().round().astype(int)
    final_check = r.groupby("receipt_id")["line_amount_num"].sum().round().astype(int)

    e_gross_mismatch = int((tx_idx["gross_amount"].astype(int) != gross_check.reindex(tx_idx.index)).sum())
    e_discount_mismatch = int((tx_idx["discount_amount"].astype(int) != discount_check.reindex(tx_idx.index)).sum())
    e_final_mismatch = int((tx_idx["final_amount"].astype(int) != final_check.reindex(tx_idx.index)).sum())
    e_balance_mismatch = int(
        (
            tx_idx["gross_amount"].astype(int) - tx_idx["discount_amount"].astype(int)
            != tx_idx["final_amount"].astype(int)
        ).sum()
    )

    results["E_gross_amount_mismatch"] = e_gross_mismatch
    results["E_discount_amount_mismatch"] = e_discount_mismatch
    results["E_final_amount_mismatch"] = e_final_mismatch
    results["E_gross_minus_discount_ne_final"] = e_balance_mismatch

    # ---------------- F. 이상치 검증 ----------------
    f_item_count_le0 = int((new_tx["item_count"].astype(int) <= 0).sum())
    f_qty_le0 = int((new_tx["total_quantity"].astype(int) <= 0).sum())
    f_gross_neg = int((new_tx["gross_amount"].astype(int) < 0).sum())
    f_discount_neg = int((new_tx["discount_amount"].astype(int) < 0).sum())
    f_final_neg = int((new_tx["final_amount"].astype(int) < 0).sum())
    f_discount_gt_gross = int(
        (new_tx["discount_amount"].astype(int) > new_tx["gross_amount"].astype(int)).sum()
    )
    f_final_gt_gross = int(
        (new_tx["final_amount"].astype(int) > new_tx["gross_amount"].astype(int)).sum()
    )
    try:
        pd.to_datetime(new_tx["transaction_datetime"], format="%Y-%m-%d %H:%M:%S")
        f_datetime_fail = 0
    except Exception:
        f_datetime_fail = -1  # 변환 실패 발생

    results["F_item_count_le0"] = f_item_count_le0
    results["F_total_quantity_le0"] = f_qty_le0
    results["F_gross_amount_negative"] = f_gross_neg
    results["F_discount_amount_negative"] = f_discount_neg
    results["F_final_amount_negative"] = f_final_neg
    results["F_discount_gt_gross"] = f_discount_gt_gross
    results["F_final_gt_gross"] = f_final_gt_gross
    results["F_datetime_convert_fail"] = f_datetime_fail

    # ---------------- 요약 통계 (보고서용) ----------------
    kept = old_ids & receipt_unique_ids
    removed = old_ids - receipt_unique_ids
    added = receipt_unique_ids - old_ids

    summary = {
        "old_transaction_rows": len(old_tx),
        "new_transaction_rows": len(new_tx),
        "kept_count": len(kept),
        "removed_count": len(removed),
        "added_count": len(added),
        "receipt_rows": len(receipt),
        "receipt_unique_ids": len(receipt_unique_ids),
        "inventory_rows": len(inventory),
    }

    return results, fail_details, summary


def is_pass(results: dict) -> bool:
    """핵심 검증 항목이 모두 통과했는지 여부. 하나라도 실패시 False."""
    bool_true_keys = [
        "A_column_names_order_match",
        "A_column_count_match",
        "A_no_missing_required",
        "B_row_count_equals_receipt_unique",
    ]
    zero_keys = [
        "B_receipt_id_dup_in_tx", "B_receipt_not_in_tx", "B_tx_receipt_not_in_receipt",
        "B_transaction_id_dup", "B_suffix_mismatch",
        "C_customer_store_time_mismatch_total",
        "D_item_count_mismatch", "D_total_quantity_mismatch",
        "E_gross_amount_mismatch", "E_discount_amount_mismatch", "E_final_amount_mismatch",
        "E_gross_minus_discount_ne_final",
        "F_item_count_le0", "F_total_quantity_le0", "F_gross_amount_negative",
        "F_discount_amount_negative", "F_final_amount_negative",
        "F_discount_gt_gross", "F_final_gt_gross", "F_datetime_convert_fail",
    ]
    for k in bool_true_keys:
        if not results.get(k, False):
            return False
    for k in zero_keys:
        if results.get(k, -1) != 0:
            return False
    return True


def main():
    inventory, receipt, old_tx = load_inputs()

    internal_errors = validate_receipt_internal(receipt)
    if internal_errors:
        print("[경고] receipt 내부 검증에서 문제가 발견되었습니다:")
        for e in internal_errors:
            print(" -", e)

    new_tx = build_transactions(receipt, old_tx)

    # dtype: ID/날짜/시간 컬럼은 문자열, 나머지 수치 컬럼은 정수로 CSV 저장
    for col in ID_STR_COLUMNS + ["transaction_date", "transaction_time", "transaction_datetime", "time_slot", "payment_method"]:
        new_tx[col] = new_tx[col].astype(str)

    new_tx.to_csv(OUTPUT_PATH, index=False)
    print(f"저장 완료: {OUTPUT_PATH} ({len(new_tx)} rows)")

    results, fail_details, summary = run_validation(new_tx, receipt, old_tx, inventory)
    verdict = "PASS" if is_pass(results) else "FAIL"

    print("\n=== 요약 ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\n=== 검증 결과 ===")
    for k, v in results.items():
        print(f"{k}: {v}")

    print(f"\n최종 판정: {verdict}")
    if fail_details:
        print("\n=== FAIL 상세 (샘플) ===")
        for k, v in fail_details.items():
            print(f"{k}: {v}")

    return new_tx, results, fail_details, summary, verdict


if __name__ == "__main__":
    main()
