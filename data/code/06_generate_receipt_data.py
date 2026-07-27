"""
09_generate_receipt_data.py

KT AIVLE School 빅프로젝트
AI 기반 신선식품 수요예측 및 다이나믹 프라이싱 플랫폼

목적
----
store.csv, store_visitor_profile.csv, calendar.csv, store_calendar.csv,
product.csv, customer.csv, inventory.csv, visitor.csv 를 입력으로 받아
POS 영수증 상품 상세 라인 데이터인 receipt.csv 를 생성한다.

핵심 규칙 (요청사항 요약)
------------------------
1. 모든 입력 CSV는 실제로 읽어서 컬럼을 확인한다. 파일이 없거나 필수 컬럼이
   없으면 즉시 중단한다. 컬럼명을 추측하지 않는다.
2. visitor.csv 에는 visit_datetime 이 없으므로 visit_date + visit_time 을
   결합하여 sale_datetime 을 만든다.
3. 방문했지만 구매하지 않은 visitor 는 receipt 에 행을 만들지 않는다.
4. inventory.csv 의 daily_sold_qty(실제 판매수량)를 절대 변경하지 않고,
   inventory_id 별로 receipt.quantity 합계가 정확히 일치하도록 "배분"만 한다.
5. 구매전환율(고유 구매 visitor 수 / 전체 visitor 수)은 16.5% ~ 17.5% 를
   목표로 한다.
6. household_type 별 quantity 평균이 뚜렷하게 차등화되어야 한다
   (single<senior<couple<family).
7. price_sensitivity 가 높을수록 할인 상품 구매 비중이 뚜렷하게 높아야 한다
   (가격 민감도 4분위 Q4_high - Q1_low >= 5%p).
8. 모든 사전/사후 검증을 통과한 경우에만 최종 CSV 를 저장한다.

코드 구조
--------
 1. 라이브러리 import
 2. 상수 및 파일 경로 정의
 3. 공통 유틸리티 함수
 4. 파일 탐색 및 로드 함수
 5. 입력 스키마 검증 함수
 6. 날짜·시간 전처리 함수
 7. 구매전환 대상 생성 함수
 8. household_type 별 quantity 샘플링 함수
 9. price_sensitivity 기반 할인상품 배정 함수
10. inventory 판매수량 배분 함수
11. receipt 행 생성 함수
12. 사후 교차검증 함수
13. 결과 요약 함수
14. 안전한 파일 저장 함수
15. main 함수
16. if __name__ == "__main__": main()
"""

# =============================================================================
# 1. 라이브러리 import
# =============================================================================
import sys
import glob
import random
import shutil
import traceback
from pathlib import Path
from collections import defaultdict, deque

import numpy as np
import pandas as pd


# =============================================================================
# 2. 상수 및 파일 경로 정의
# =============================================================================

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
rng = np.random.default_rng(RANDOM_SEED)

BASE_DIR = Path("/content")

# Colab 에 업로드될 것으로 기대하는 정확한 파일명 (최우선으로 탐색)
INPUT_FILENAMES = {
    "store": "store.csv",
    "store_visitor_profile": "store_visitor_profile.csv",
    "calendar": "calendar.csv",
    "store_calendar": "store_calendar.csv",
    "product": "product.csv",
    "customer": "customer.csv",
    "inventory": "inventory.csv",
    "visitor": "visitor.csv",
}

TEMP_OUTPUT_PATH = BASE_DIR / "receipt_temp.csv"
FINAL_OUTPUT_PATH = BASE_DIR / "receipt.csv"

# 최종 receipt.csv 컬럼 (순서 고정, 18개)
OUTPUT_COLUMNS = [
    "receipt_id",
    "line_no",
    "visitor_id",
    "customer_id",
    "store_id",
    "sale_date",
    "sale_time",
    "sale_datetime",
    "time_slot",
    "inventory_id",
    "lot_id",
    "product_id",
    "quantity",
    "unit_price",
    "discount_rate",
    "sale_unit_price",
    "line_amount",
    "payment_method",
]

# 각 입력 파일에서 반드시 존재해야 하는 컬럼 (실제 첨부 파일을 열어서 확인한 값 기준)
REQUIRED_COLUMNS = {
    "store": [
        "store_id", "store_name", "area_type", "resident_pop", "floating_idx",
        "open_hour", "close_hour", "closure_weekday", "closure_week_1",
        "closure_week_2", "order_error_sigma",
    ],
    "store_visitor_profile": [
        "area_type", "day_type", "close_hour", "time_slot", "start_hour",
        "end_hour", "visitor_ratio", "profile_source",
    ],
    "calendar": [
        "date", "year", "month", "day", "day_of_week", "week_of_month",
        "day_type", "is_weekend", "is_holiday", "holiday_name", "season",
        "season_index", "is_event_day", "event_type", "event_index",
    ],
    "store_calendar": [
        "date", "store_id", "is_mandatory_closed", "is_open", "open_hour",
        "close_hour", "closure_reason",
    ],
    "product": [
        "product_id", "product_name", "category", "subcategory", "sales_type",
        "unit", "standard_weight_kg", "shelf_life_days", "base_cost",
        "base_price", "margin_rate", "max_discount_rate", "markdown_eligible",
        "esl_applicable", "freshness_decay_type", "baseline_waste_rate",
        "price_source",
    ],
    "customer": [
        "customer_id", "age_group", "household_type", "income_level",
        "residence_type", "price_sensitivity", "freshness_sensitivity",
        "preferred_category", "visit_frequency",
    ],
    "inventory": [
        "inventory_id", "store_id", "product_id", "lot_id", "current_date",
        "manufacture_date", "expiry_date", "days_to_expiry", "inbound_qty",
        "daily_sold_qty", "daily_waste_qty", "current_stock_qty",
        "reserved_qty", "available_qty", "freshness_score", "unit_cost",
        "unit_price", "discount_rate", "discount_price", "disposal_candidate",
        "inventory_status", "waste_reason", "weight_kg",
        # sold_out_flag 는 버전에 따라 없을 수 있어 별도로 optional 처리한다.
    ],
    "visitor": [
        "visitor_id", "customer_id", "store_id", "visit_date", "visit_time",
        "time_slot", "day_type", "visit_sequence",
    ],
}

# inventory.csv 에는 있을 수도, 없을 수도 있는 컬럼 (있으면 사용, 없으면 무시)
INVENTORY_OPTIONAL_COLUMNS = ["sold_out_flag"]

# 필수 ID 컬럼 (결측 금지)
ID_NULL_CHECK = {
    "store": ["store_id"],
    "customer": ["customer_id"],
    "visitor": ["visitor_id", "customer_id", "store_id"],
    "inventory": ["inventory_id", "lot_id", "product_id", "store_id"],
    "product": ["product_id"],
}

# 기본키 고유성 검사 대상
PRIMARY_KEY_CHECK = {
    "store": "store_id",
    "customer": "customer_id",
    "visitor": "visitor_id",
    "inventory": "inventory_id",
    "product": "product_id",
}

# 구매전환율 목표
TARGET_CONVERSION_RATE = 0.17
CONVERSION_LOWER_BOUND = 0.165
CONVERSION_UPPER_BOUND = 0.175

# 수량 규칙
MIN_QUANTITY = 1
MAX_QUANTITY = 5

# 영수증당 라인 수 규칙
MAX_LINES_PER_RECEIPT = 3
EXTRA_LINE_PROBABILITY = 1.0 / 11.0  # 평균 1.1 lines/receipt 목표 (1 / (1+0.1))
FIT_WEIGHT_POWER = 3.0  # exponent that sharpens household-type quantity fit weighting
HOUSEHOLD_TYPES = ["single", "couple", "family", "senior"]
RECEIPT_LINE_COUNT_TARGET_RANGE = (1.05, 1.20)

# 할인 정책 상한
MAX_DISCOUNT_RATE_PCT = 40

# household_type 별 quantity 확률분포 (1~5개, 합계 1.0)
# 근거: [가정] 사용자가 예시로 제시한 분포(단순 평균 1.20/1.40/1.79/1.30)를
# 그대로 쓰면, inventory 각 행의 잔여수량(중앙값 3개 수준)에 의해 quantity 가
# min(샘플, 잔여수량, 5) 로 잘리는 일이 매우 잦아(대부분의 inventory 행이
# 1~4개 단위로 소진됨), 최종 실현 평균이 목표 평균보다 15~30% 가량 낮게
# 나오는 것을 실측했다 (예: family 예시분포를 그대로 쓰면 실현 평균이 약
# 1.5 수준에 그침). 따라서 이 표는 "잘림 이후 최종 receipt.csv 에서 관찰되는
# 평균"이 목표 범위(단일 1.15~1.25, 커플 1.35~1.45, 가족 1.70~1.90, 시니어
# 1.25~1.35)에 들어오도록 역산하여 평균을 상향 보정한 분포이다. (요청사항
# 13번에서 "예시이며 inventory 판매수량을 보존하면서 목표 평균이 나오도록
# 조정해도 된다"고 명시되어 있어 이 보정을 적용했다.) 1~5개 범위, 합계 1.0
# 제약은 그대로 유지한다.
QUANTITY_PROBABILITY = {
    "single": {1: 0.72, 2: 0.22, 3: 0.06, 4: 0.00, 5: 0.00},
    "couple": {1: 0.55, 2: 0.32, 3: 0.11, 4: 0.02, 5: 0.00},
    "family": {1: 0.32, 2: 0.38, 3: 0.20, 4: 0.07, 5: 0.03},
    "senior": {1: 0.60, 2: 0.30, 3: 0.08, 4: 0.02, 5: 0.00},
}

# household_type 별 quantity 평균 목표/허용 범위
QUANTITY_TARGET_MEAN = {"single": 1.2, "couple": 1.4, "family": 1.8, "senior": 1.3}
QUANTITY_TARGET_RANGE = {
    "single": (1.15, 1.25),
    "couple": (1.35, 1.45),
    "family": (1.70, 1.90),
    "senior": (1.25, 1.35),
}

# household_type 이 quantity 뿐 아니라 "구매전환 가능성"에도 완만하게 반영되도록
# 사용하는 가중치. [가정] 가구원수가 많을수록 방문 시 실제 구매로 이어질
# 가능성이 다소 높다고 가정한다. (필수 요구사항은 아니며, 실현성을 높이기 위한 보조 장치)
HOUSEHOLD_PURCHASE_FACTOR = {
    "family": 1.15,
    "couple": 1.05,
    "senior": 1.00,
    "single": 0.90,
}

# 선호 카테고리 일치 시 선택 가중치 보너스 [가정]
PREFERRED_CATEGORY_BONUS = 1.5

# 결제수단 비율
PAYMENT_METHOD_PROBABILITY = {"CARD": 0.75, "CASH": 0.15, "MOBILE": 0.10}

# 구매전환율 보정(repair) 최대 반복 횟수 (무한루프 방지)
CONVERSION_REPAIR_MAX_ITER = 200000

# 신규 구매자 탐색 시 그룹 내 in-store candidate 가 하나도 없을 때 로그를 얼마나
# 자주 찍을지 (너무 많은 로그로 콘솔이 도배되는 것을 방지)
WARN_LOG_LIMIT = 20


# =============================================================================
# 3. 공통 유틸리티 함수
# =============================================================================

def log(msg: str) -> None:
    """진행 상황을 즉시 출력한다 (버퍼링 없이)."""
    print(msg, flush=True)


def fail(msg: str) -> None:
    """치명적 오류를 출력하고 즉시 프로그램을 중단한다."""
    log("")
    log("=" * 78)
    log("[FAIL] 실행을 중단합니다.")
    log(msg)
    log("=" * 78)
    raise SystemExit(1)


def section(title: str) -> None:
    log("")
    log("-" * 78)
    log(title)
    log("-" * 78)


def clip01(x) -> float:
    return float(np.clip(x, 0.0, 1.0))


# =============================================================================
# 4. 파일 탐색 및 로드 함수
# =============================================================================

def find_input_file(key: str, filename: str, base_dir: Path) -> Path:
    """
    지정한 파일명을 base_dir 에서 찾는다.
    1) 정확한 파일명이 존재하면 최우선으로 사용한다.
    2) 정확한 파일명이 없고 "이름(1).csv" 형태의 유사 파일이 정확히 1개만
       있으면 그 파일을 사용한다 (근거를 로그로 남긴다).
    3) 유사 파일이 2개 이상이면 [수정] 더 이상 수정시각 기준으로 자동
       선택하지 않는다. 후보 목록을 모두 출력하고 정확한 파일명으로 맞춰
       다시 업로드하도록 안내한 뒤 즉시 실행을 중단한다.
    4) 아무 파일도 찾지 못하면 None 을 반환한다 (호출부에서 오류 처리).
    """
    exact_path = base_dir / filename
    if exact_path.exists():
        return exact_path

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    pattern = str(base_dir / f"{stem}*{suffix}")
    candidates = sorted(glob.glob(pattern))

    if not candidates:
        return None

    if len(candidates) == 1:
        log(f"  - [{key}] 정확한 파일명은 없지만 유사 파일 1개를 발견하여 사용합니다: {candidates[0]}")
        return Path(candidates[0])

    # [수정] 이전 코드는 유사 파일이 여러 개면 수정시각이 가장 최신인 파일을
    # 자동으로 선택했다. 이는 사용자가 의도하지 않은 백업/구버전 파일이
    # 조용히 선택될 위험이 있으므로, 이번 수정에서는 자동 선택을 하지 않고
    # 후보 목록을 모두 출력한 뒤 정확한 파일명으로 맞춰 다시 업로드하도록
    # 안내하고 즉시 중단한다.
    candidate_list = "\n".join(f"      - {c}" for c in candidates)
    fail(
        f"[{key}] 정확한 파일명 '{filename}' 은 없고, 유사한 파일이 여러 개 발견되어 "
        f"자동으로 선택하지 않습니다:\n{candidate_list}\n\n"
        "다음 8개 파일명을 정확히 맞춰 각각 1개씩만 " + str(base_dir) + " 에 "
        "업로드한 뒤 다시 실행해주세요:\n"
        + "\n".join(f"      - {v}" for v in INPUT_FILENAMES.values())
    )


def load_all_inputs(base_dir: Path) -> dict:
    """8개 입력 CSV 를 모두 탐색하고 로드한다. 하나라도 없으면 즉시 중단한다."""
    section("[1/16] 입력 파일 탐색 및 로드")

    resolved_paths = {}
    missing = []
    for key, filename in INPUT_FILENAMES.items():
        found = find_input_file(key, filename, base_dir)
        if found is None:
            missing.append(filename)
        else:
            resolved_paths[key] = found

    if missing:
        fail(
            "다음 입력 파일을 찾을 수 없습니다 (BASE_DIR=" + str(base_dir) + "):\n"
            + "\n".join(f"  - {m}" for m in missing)
            + "\n\n8개 입력 파일을 모두 /content 에 업로드한 뒤 다시 실행해주세요."
        )

    dfs = {}
    for key, path in resolved_paths.items():
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        except Exception as e:
            fail(f"[{key}] 파일을 읽는 중 오류가 발생했습니다: {path}\n{e}")
        dfs[key] = df
        log(f"  - [{key}] 로드 완료: {path.name}  shape={df.shape}")
        log(f"      columns={list(df.columns)}")

    return dfs


# =============================================================================
# 5. 입력 스키마 검증 함수
# =============================================================================

def check_required_columns(dfs: dict) -> None:
    """각 파일에 필수 컬럼이 모두 존재하는지 확인한다."""
    section("[2/16] 필수 컬럼 존재 여부 검증")

    problems = []
    for key, required in REQUIRED_COLUMNS.items():
        actual_cols = set(dfs[key].columns)
        missing_cols = [c for c in required if c not in actual_cols]
        if missing_cols:
            problems.append(f"  - [{key}] 누락된 필수 컬럼: {missing_cols}")
        else:
            log(f"  - [{key}] PASS (필수 컬럼 {len(required)}개 모두 존재)")

    if problems:
        fail("필수 컬럼이 누락된 파일이 있습니다:\n" + "\n".join(problems))

    # inventory 의 sold_out_flag 는 optional
    has_sold_out_flag = "sold_out_flag" in dfs["inventory"].columns
    log(f"  - [inventory] sold_out_flag 컬럼 존재 여부: {has_sold_out_flag}")

    # [수정] visitor.csv 에는 visit_datetime 컬럼이 없어야 정상이다. 이전
    # 코드는 여기서는 경고만 출력하고 계속 진행했지만, 뒤쪽 preprocess_datetime()
    # 에서는 존재 시 즉시 중단하도록 되어 있어 두 곳의 동작이 서로 모순되었다.
    # 이번 수정에서는 "예상 외 스키마가 발견된 것"으로 간주하여 이 시점에
    # 바로 명확한 오류와 함께 중단하는 방식으로 통일한다.
    if "visit_datetime" in dfs["visitor"].columns:
        fail(
            "visitor.csv 에 예상하지 못한 visit_datetime 컬럼이 존재합니다. "
            "이번 프로젝트의 visitor.csv 스키마에는 이 컬럼이 없어야 하며, "
            "sale_datetime 은 반드시 visit_date + visit_time 을 결합해 새로 "
            "생성해야 합니다. 실제 스키마가 예상과 달라 임의로 계속 진행하지 "
            "않고 중단합니다."
        )


def check_duplicate_column_names(dfs: dict) -> None:
    """모든 CSV 에서 컬럼명 중복이 없는지 확인한다."""
    section("[3/16] 중복 컬럼명 검증")
    problems = []
    for key, df in dfs.items():
        cols = list(df.columns)
        dup = {c for c in cols if cols.count(c) > 1}
        if dup:
            problems.append(f"  - [{key}] 중복 컬럼명: {sorted(dup)}")
        else:
            log(f"  - [{key}] PASS (중복 컬럼명 없음)")
    if problems:
        fail("중복 컬럼명이 발견되었습니다:\n" + "\n".join(problems))


def check_id_nulls(dfs: dict) -> None:
    """필수 ID 컬럼에 결측이 없는지 확인한다."""
    section("[4/16] 필수 ID 결측값 검증")
    problems = []
    for key, id_cols in ID_NULL_CHECK.items():
        for col in id_cols:
            if col not in dfs[key].columns:
                continue
            n_null = int(dfs[key][col].isnull().sum())
            if n_null > 0:
                problems.append(f"  - [{key}.{col}] 결측 {n_null}건")
            else:
                log(f"  - [{key}.{col}] PASS (결측 0건)")
    if problems:
        fail("필수 ID 컬럼에 결측값이 있습니다:\n" + "\n".join(problems))


def check_primary_key_uniqueness(dfs: dict) -> None:
    """기본키 고유성을 확인한다."""
    section("[5/16] ID 고유성 검증")
    problems = []
    for key, col in PRIMARY_KEY_CHECK.items():
        if col not in dfs[key].columns:
            continue
        n_dup = int(dfs[key][col].duplicated().sum())
        if n_dup > 0:
            sample = dfs[key][dfs[key][col].duplicated(keep=False)][col].unique()[:5]
            problems.append(f"  - [{key}.{col}] 중복 {n_dup}건, 샘플={list(sample)}")
        else:
            log(f"  - [{key}.{col}] PASS (고유값 {dfs[key][col].nunique()}개, 중복 0건)")
    if problems:
        fail("기본키 고유성 위반이 발견되었습니다:\n" + "\n".join(problems))


def check_numeric_ranges(dfs: dict) -> None:
    """수량/가격/할인율 등 수치 컬럼의 범위를 확인한다."""
    section("[6/16] 수량/가격/할인율 범위 검증")
    problems = []

    inv = dfs["inventory"]

    # [수정] 기존 코드는 inv[col] < 0 등 수치 비교를 바로 수행했는데, 만약
    # 컬럼이 문자열이 섞여 있거나 결측이 있으면 비교 자체가 조용히 틀린
    # 결과를 내거나 예외로 죽을 수 있었다. 이제 숫자 변환 가능 여부와
    # 결측값을 먼저 명시적으로 검사하고, daily_sold_qty 등 정수여야 하는
    # 컬럼은 실제로 정수값인지도 확인한다. 문제가 있으면 다른 검증으로
    # 넘어가지 않고 여기서 바로 중단한다.
    numeric_required_cols = [
        "inbound_qty", "daily_sold_qty", "daily_waste_qty", "current_stock_qty",
        "reserved_qty", "available_qty", "unit_cost", "unit_price",
        "discount_rate", "discount_price",
    ]
    numeric_converted = {}
    for col in numeric_required_cols:
        if col not in inv.columns:
            problems.append(f"  - [inventory.{col}] 컬럼이 존재하지 않습니다.")
            continue
        n_original_null = int(inv[col].isnull().sum())
        converted = pd.to_numeric(inv[col], errors="coerce")
        n_conversion_fail = int(converted.isnull().sum()) - n_original_null
        if n_original_null > 0:
            problems.append(f"  - [inventory.{col}] 원본 결측값 {n_original_null}건")
        elif n_conversion_fail > 0:
            problems.append(f"  - [inventory.{col}] 숫자로 변환할 수 없는 값 {n_conversion_fail}건")
        else:
            log(f"  - [inventory.{col}] PASS (숫자 변환 가능, 결측 없음)")
            numeric_converted[col] = converted

    integer_required_cols = [
        "daily_sold_qty", "daily_waste_qty", "inbound_qty", "current_stock_qty",
        "reserved_qty", "available_qty", "discount_rate",
    ]
    for col in integer_required_cols:
        if col not in numeric_converted:
            continue
        converted = numeric_converted[col]
        n_non_int = int((converted != converted.astype(np.int64)).sum())
        if n_non_int > 0:
            problems.append(f"  - [inventory.{col}] 정수가 아닌 값 {n_non_int}건")
        else:
            log(f"  - [inventory.{col}] PASS (정수값 확인)")

    if problems:
        fail("inventory 수치형 컬럼 변환/정수성 검증에 실패했습니다:\n" + "\n".join(problems))

    qty_cols = ["inbound_qty", "daily_sold_qty", "daily_waste_qty",
                "current_stock_qty", "reserved_qty", "available_qty"]
    for col in qty_cols:
        if col not in inv.columns:
            continue
        n_neg = int((inv[col] < 0).sum())
        if n_neg > 0:
            problems.append(f"  - [inventory.{col}] 음수 {n_neg}건")
        else:
            log(f"  - [inventory.{col}] PASS (음수 없음)")

    price_cols = ["unit_cost", "unit_price", "discount_price"]
    for col in price_cols:
        if col not in inv.columns:
            continue
        n_neg = int((inv[col] < 0).sum())
        if n_neg > 0:
            problems.append(f"  - [inventory.{col}] 0 미만 값 {n_neg}건")
        else:
            log(f"  - [inventory.{col}] PASS (0 미만 값 없음)")

    if "discount_rate" in inv.columns:
        dr = inv["discount_rate"]
        n_below = int((dr < 0).sum())
        n_above = int((dr > MAX_DISCOUNT_RATE_PCT).sum())
        if n_below > 0 or n_above > 0:
            problems.append(
                f"  - [inventory.discount_rate] 범위 위반: 0 미만 {n_below}건, "
                f"{MAX_DISCOUNT_RATE_PCT} 초과 {n_above}건 "
                f"(min={dr.min()}, max={dr.max()})"
            )
        else:
            log(f"  - [inventory.discount_rate] PASS (0~{MAX_DISCOUNT_RATE_PCT} 범위 내, "
                f"min={dr.min()}, max={dr.max()})")

    if problems:
        fail("수치 범위 검증에 실패했습니다:\n" + "\n".join(problems))


def check_id_referential_integrity(dfs: dict) -> None:
    """visitor -> customer/store, inventory -> store/product 연결을 사전 검증한다."""
    section("[7/16] 파일 간 외래키(FK) 연결 사전 검증")
    problems = []

    visitor = dfs["visitor"]
    customer = dfs["customer"]
    store = dfs["store"]
    inventory = dfs["inventory"]
    product = dfs["product"]

    missing_cust = set(visitor["customer_id"]) - set(customer["customer_id"])
    if missing_cust:
        problems.append(f"  - visitor.customer_id 중 customer.csv 에 없는 값 {len(missing_cust)}건, "
                         f"샘플={list(missing_cust)[:5]}")
    else:
        log("  - visitor.customer_id -> customer.customer_id PASS (전량 연결)")

    missing_store_v = set(visitor["store_id"]) - set(store["store_id"])
    if missing_store_v:
        problems.append(f"  - visitor.store_id 중 store.csv 에 없는 값: {missing_store_v}")
    else:
        log("  - visitor.store_id -> store.store_id PASS (전량 연결)")

    missing_store_i = set(inventory["store_id"]) - set(store["store_id"])
    if missing_store_i:
        problems.append(f"  - inventory.store_id 중 store.csv 에 없는 값: {missing_store_i}")
    else:
        log("  - inventory.store_id -> store.store_id PASS (전량 연결)")

    missing_product = set(inventory["product_id"]) - set(product["product_id"])
    if missing_product:
        problems.append(f"  - inventory.product_id 중 product.csv 에 없는 값: {missing_product}")
    else:
        log("  - inventory.product_id -> product.product_id PASS (전량 연결)")

    if problems:
        fail("파일 간 FK 연결이 깨져 있습니다:\n" + "\n".join(problems))


def check_product_category_scope(dfs: dict) -> None:
    """product.csv 의 카테고리가 프로젝트 공식 카테고리 범위인지 확인한다 (경고만)."""
    section("[8/16] 상품 카테고리 범위 확인")
    official = {"produce", "dairy", "meat", "cheese", "deli", "과채", "유제품", "육류", "치즈", "델리"}
    actual = set(dfs["product"]["category"].dropna().unique())
    unknown = actual - official
    if unknown:
        log(f"  - [WARNING] product.category 에 프로젝트 공식 카테고리 목록과 다른 값이 있습니다: {unknown}")
        log("    이 값들은 category 매칭(선호 카테고리 가중치) 로직에서 있는 그대로 사용됩니다.")
    else:
        log(f"  - PASS (product.category 값: {sorted(actual)})")


# =============================================================================
# 6. 날짜·시간 전처리 함수
# =============================================================================

def preprocess_datetime(dfs: dict) -> None:
    """
    visitor.csv 의 visit_date + visit_time 을 결합하여 sale_datetime(내부용) 을
    생성하고, 모든 날짜 컬럼의 파싱 가능 여부를 검증한다.
    """
    section("[9/16] 날짜·시간 파싱 및 sale_datetime 생성")

    visitor = dfs["visitor"]

    # [수정] visit_datetime 존재 여부 검사는 check_required_columns() 에서
    # 이미 수행하고 중단하므로 (통일된 단일 지점), 여기서는 중복 검사를
    # 제거한다. 이 함수에 도달했다는 것은 이미 visit_datetime 이 없음을
    # 의미한다.

    required = ["visitor_id", "customer_id", "store_id", "visit_date", "visit_time",
                "time_slot", "day_type", "visit_sequence"]
    missing = [c for c in required if c not in visitor.columns]
    if missing:
        fail(f"visitor.csv 에 필수 컬럼이 없습니다: {missing}")

    visitor["_visit_date_parsed"] = pd.to_datetime(visitor["visit_date"], errors="coerce")
    n_bad_date = int(visitor["_visit_date_parsed"].isnull().sum())
    if n_bad_date > 0:
        sample = visitor[visitor["_visit_date_parsed"].isnull()][["visitor_id", "visit_date"]].head(5)
        fail(f"visitor.visit_date 파싱 실패 {n_bad_date}건\n샘플:\n{sample}")
    log("  - visitor.visit_date 파싱 PASS")

    visitor["sale_datetime_parsed"] = pd.to_datetime(
        visitor["visit_date"].astype(str) + " " + visitor["visit_time"].astype(str),
        errors="coerce",
    )
    n_bad_dt = int(visitor["sale_datetime_parsed"].isnull().sum())
    if n_bad_dt > 0:
        sample = visitor[visitor["sale_datetime_parsed"].isnull()][
            ["visitor_id", "visit_date", "visit_time"]
        ].head(5)
        fail(f"visit_date + visit_time 결합(sale_datetime) 파싱 실패 {n_bad_dt}건\n샘플:\n{sample}")
    log("  - sale_datetime(visit_date + visit_time) 파싱 PASS")

    # inventory 의 날짜 컬럼
    inventory = dfs["inventory"]
    for col in ["current_date", "manufacture_date", "expiry_date"]:
        if col not in inventory.columns:
            continue
        parsed = pd.to_datetime(inventory[col], errors="coerce")
        n_bad = int(parsed.isnull().sum())
        if n_bad > 0:
            fail(f"inventory.{col} 파싱 실패 {n_bad}건")
        log(f"  - inventory.{col} 파싱 PASS")

    # calendar / store_calendar 날짜 컬럼
    for key in ["calendar", "store_calendar"]:
        parsed = pd.to_datetime(dfs[key]["date"], errors="coerce")
        n_bad = int(parsed.isnull().sum())
        if n_bad > 0:
            fail(f"{key}.date 파싱 실패 {n_bad}건")
        log(f"  - {key}.date 파싱 PASS")

    dfs["visitor"] = visitor


def verify_no_mandatory_closed_activity(dfs: dict) -> None:
    """의무휴업일/미영업일에 visitor 방문이 없는지 검증한다."""
    section("[10/16] 의무휴업일 방문 사전 검증")

    store_calendar = dfs["store_calendar"]
    visitor = dfs["visitor"]

    closed = store_calendar[
        (store_calendar["is_mandatory_closed"] == 1) | (store_calendar["is_open"] == 0)
    ]
    closed_set = set(zip(closed["store_id"], closed["date"].astype(str)))

    visitor_keys = list(zip(visitor["store_id"], visitor["visit_date"].astype(str)))
    violation_mask = [k in closed_set for k in visitor_keys]
    n_violation = int(sum(violation_mask))

    if n_violation > 0:
        sample = visitor.loc[violation_mask, ["visitor_id", "store_id", "visit_date"]].head(10)
        fail(
            f"의무휴업일/미영업일에 visitor 방문 기록이 {n_violation}건 발견되었습니다.\n"
            f"샘플:\n{sample}\n"
            "요구사항에 따라 이 경우 임의로 계속 진행하지 않고 중단합니다."
        )
    log(f"  - PASS (의무휴업일/미영업일 방문 0건, 휴업일 레코드 {len(closed_set)}건 전수 대조)")


# =============================================================================
# 7. 구매전환 대상 생성 함수 (가중치 / 확률 유틸)
# =============================================================================

def build_customer_features(dfs: dict) -> pd.DataFrame:
    """
    customer.csv 를 기반으로 price_sensitivity 정규화, 구매확률 가중치 등
    파생 피처를 생성한다.
    """
    section("[11/16] 고객 특성(price_sensitivity 정규화 등) 파생 변수 생성")

    customer = dfs["customer"].copy()

    ps_min = customer["price_sensitivity"].min()
    ps_max = customer["price_sensitivity"].max()
    if ps_max > ps_min:
        customer["price_sensitivity_norm"] = (customer["price_sensitivity"] - ps_min) / (ps_max - ps_min)
    else:
        # 모든 값이 동일한 경우 0으로 나누는 오류 방지
        customer["price_sensitivity_norm"] = 0.5
        log("  - [WARNING] price_sensitivity 값이 모두 동일하여 정규화 값을 0.5로 고정합니다.")

    log(f"  - price_sensitivity 원본 범위: [{ps_min}, {ps_max}]")
    log(f"  - price_sensitivity_norm 범위: "
        f"[{customer['price_sensitivity_norm'].min():.4f}, {customer['price_sensitivity_norm'].max():.4f}]")

    unknown_household = set(customer["household_type"].unique()) - set(QUANTITY_PROBABILITY.keys())
    if unknown_household:
        fail(f"customer.household_type 에 처리할 수 없는 값이 있습니다: {unknown_household}\n"
             f"허용값: {list(QUANTITY_PROBABILITY.keys())}")
    log(f"  - household_type 값 확인 PASS: {sorted(customer['household_type'].unique())}")

    customer["household_purchase_factor"] = customer["household_type"].map(HOUSEHOLD_PURCHASE_FACTOR)
    customer["purchase_base_weight"] = customer["household_purchase_factor"] * (
        1.0 + 0.3 * customer["price_sensitivity_norm"]
    )

    return customer


def compute_price_sensitivity_quartiles(customer_features: pd.DataFrame) -> pd.DataFrame:
    """
    [신규] 고객 단위(customer_id 당 1행)로 price_sensitivity 4분위를 만든다.
    기존 코드는 receipt 라인 단위(pd.qcut(receipt_with_ps["price_sensitivity"]))에
    바로 분위를 매겼기 때문에, 상품 라인이 많은 고객(가족 등)의 price_sensitivity
    값이 여러 번 중복 반영되어 분위 경계 자체가 왜곡될 수 있었다.
    이제는 customer_features 에서 고객별 price_sensitivity 를 1개씩만 뽑아
    분위를 나눈 뒤, 그 결과를 receipt 에 merge 하는 방식으로 바꾼다.
    또한 price_sensitivity 값에 동점이 많아 pd.qcut 이 "Bin edges must be
    unique" 오류를 낼 수 있으므로, rank(method="first") 로 동점을 순서대로
    풀어준 뒤 그 순위를 4분위로 나눈다 (순위는 항상 유일하므로 안전하다).
    반환값: customer_id, price_sensitivity, ps_quartile 3개 컬럼의 DataFrame.
    """
    cust = customer_features[["customer_id", "price_sensitivity"]].drop_duplicates("customer_id").copy()
    cust["_rank"] = cust["price_sensitivity"].rank(method="first")
    quartile_labels = ["Q1_low", "Q2", "Q3", "Q4_high"]
    cust["ps_quartile"] = pd.qcut(cust["_rank"], q=4, labels=quartile_labels)
    return cust[["customer_id", "price_sensitivity", "ps_quartile"]]


def build_quantity_lookup_tables() -> dict:
    """
    household_type 별, 그리고 "재고 잔여수량 cap" 별로 미리 절단(truncated)된
    quantity 확률분포 테이블을 만든다.
    cap 이 작을 때(재고가 얼마 안 남았을 때) 매번 거부추출(rejection sampling)을
    하지 않기 위해 사전 계산해 둔다.
    """
    table = {}
    for household_type, prob_dict in QUANTITY_PROBABILITY.items():
        table[household_type] = {}
        values_all = np.array(sorted(prob_dict.keys()))
        probs_all = np.array([prob_dict[v] for v in values_all])
        for cap in range(1, MAX_QUANTITY + 1):
            mask = values_all <= cap
            values = values_all[mask]
            probs = probs_all[mask]
            if probs.sum() <= 0:
                # cap=1 인데 해당 household 분포에서 1의 확률이 0인 경우는 없지만
                # 방어적으로 균등분포 처리
                values = np.array([cap])
                probs = np.array([1.0])
            else:
                probs = probs / probs.sum()
            table[household_type][cap] = (values, probs)
    return table


def sample_quantity(household_type: str, cap: int, quantity_table: dict, rng: np.random.Generator) -> int:
    """household_type 과 잔여수량 상한(cap) 을 고려하여 quantity 를 샘플링한다."""
    cap = int(max(MIN_QUANTITY, min(cap, MAX_QUANTITY)))
    values, probs = quantity_table[household_type][cap]
    return int(rng.choice(values, p=probs))


def build_expected_quantity_table(quantity_table: dict) -> dict:
    """
    household_type 별로, 잔여수량 상한(cap=1~5) 이 주어졌을 때 기대 구매수량을
    미리 계산해 둔다. inventory 잔여수량이 넉넉할 때는 family/couple 처럼
    평균 수요가 큰 household 를 우선 배정하고, 잔여수량이 얼마 남지 않았을 때는
    어차피 수요가 작은 single/senior 를 배정해도 손해가 없으므로, 이 기대값을
    "적합도 가중치"로 사용해 household_type 별 목표 평균이 재고 배분 과정에서
    한쪽으로만 깎이지 않도록 한다.
    반환값: {household_type: np.array(길이5, index=cap-1)}
    """
    table = {}
    for household_type, cap_dict in quantity_table.items():
        expected = np.zeros(MAX_QUANTITY, dtype=float)
        for cap in range(1, MAX_QUANTITY + 1):
            values, probs = cap_dict[cap]
            expected[cap - 1] = float(np.sum(values * probs))
        table[household_type] = expected
    return table


def discount_assignment_weight(price_sensitivity_norm: np.ndarray, is_discounted: bool) -> np.ndarray:
    """
    price_sensitivity_norm(0~1) 이 높을수록 할인 상품에 더 높은 가중치를,
    price_sensitivity_norm 이 낮을수록 정상가 상품에 더 높은 가중치를 부여한다.
    (요청 사항 16번의 exp 기반 가중치 공식을 그대로 사용)
    """
    p = np.clip(price_sensitivity_norm, 0.0, 1.0)
    if is_discounted:
        return np.exp(2.0 * (p - 0.4))
    return 1.05 - 0.10 * p


# =============================================================================
# 8~10. 핵심 배분 로직: 그룹(store, date) 단위 receipt 라인 생성
# =============================================================================

class GroupAllocationState:
    """store_id + current_date(=visit_date) 그룹 하나에 대한 배분 상태를 담는다."""

    __slots__ = (
        "visitor_ids", "customer_ids", "household_types", "price_sensitivity_norm",
        "preferred_categories", "purchase_base_weight",
        "visit_times", "time_slots", "day_types",
        "available_mask", "n", "expected_qty_matrix", "household_fit_probs",
        "purchaser_order",  # local index list, 오늘 구매자로 등록된 순서
        "purchaser_line_count", "purchaser_used_inventory", "purchaser_used_product",
    )

    def __init__(self, sub_visitor: pd.DataFrame, expected_qty_table: dict):
        self.visitor_ids = sub_visitor["visitor_id"].to_numpy()
        self.customer_ids = sub_visitor["customer_id"].to_numpy()
        self.household_types = sub_visitor["household_type"].to_numpy()
        self.price_sensitivity_norm = sub_visitor["price_sensitivity_norm"].to_numpy(dtype=float)
        self.preferred_categories = sub_visitor["preferred_category"].to_numpy()
        self.purchase_base_weight = sub_visitor["purchase_base_weight"].to_numpy(dtype=float)
        self.visit_times = sub_visitor["visit_time"].to_numpy()
        self.time_slots = sub_visitor["time_slot"].to_numpy()
        self.day_types = sub_visitor["day_type"].to_numpy()

        self.n = len(sub_visitor)
        self.available_mask = np.ones(self.n, dtype=bool)

        # household_type quantity fit matrix: shape=(n, MAX_QUANTITY).
        # column index c corresponds to cap = c + 1. Used so that when the
        # remaining inventory quantity (cap) is large, household types with
        # higher expected demand (family/couple) are preferentially matched,
        # and when cap is small the effect vanishes naturally.
        self.expected_qty_matrix = np.vstack(
            [expected_qty_table[h] for h in self.household_types]
        )

        # household_fit_probs[cap-1] = selection-probability array over
        # HOUSEHOLD_TYPES, derived from each household type's expected
        # quantity at this cap (raised to FIT_WEIGHT_POWER). Used by the
        # two-stage picker below: stage 1 picks a household_type using
        # these probabilities, stage 2 picks an actual visitor of that
        # household_type using price_sensitivity/category weighting.
        fit_by_cap = np.array(
            [[expected_qty_table[h][c] for h in HOUSEHOLD_TYPES] for c in range(MAX_QUANTITY)]
        ) ** FIT_WEIGHT_POWER
        self.household_fit_probs = fit_by_cap / fit_by_cap.sum(axis=1, keepdims=True)

        self.purchaser_order = []          # list[int] local idx, 등록된 순서 유지
        self.purchaser_line_count = {}     # local idx -> int
        self.purchaser_used_inventory = {} # local idx -> set(inventory_id)
        self.purchaser_used_product = {}   # local idx -> set(product_id)

    def pick_new_purchaser(self, is_discounted: bool, product_category: str, cap: int,
                            rng: np.random.Generator):
        """
        2-stage weighted selection.
        Stage 1: choose which household_type this draw should target, using
        household_fit_probs[cap-1] (each household_type's expected quantity
        at this cap). This is what makes family/couple preferentially absorb
        larger-capacity draws while single/senior still receive their fair
        share of small-capacity draws, so the household_type quantity
        averages differentiate as required.
        Stage 2: within that household_type (restricted to still-available
        visitors), choose the actual visitor using price_sensitivity /
        preferred_category weighting, same as before.
        If no visitor of the chosen household_type remains available today,
        fall back to the overall available pool so quantity is never lost.
        """
        idxs_all = np.nonzero(self.available_mask)[0]
        if idxs_all.size == 0:
            return None

        household_probs = self.household_fit_probs[cap - 1]
        chosen_household = rng.choice(HOUSEHOLD_TYPES, p=household_probs)

        mask_h = self.available_mask & (self.household_types == chosen_household)
        idxs = np.nonzero(mask_h)[0]
        if idxs.size == 0:
            idxs = idxs_all

        ps = self.price_sensitivity_norm[idxs]
        base_w = self.purchase_base_weight[idxs]
        discount_w = np.where(
            is_discounted,
            np.exp(2.0 * (np.clip(ps, 0.0, 1.0) - 0.4)),
            1.05 - 0.10 * np.clip(ps, 0.0, 1.0),
        )
        cat = self.preferred_categories[idxs]
        cat_bonus = np.where(cat == product_category, PREFERRED_CATEGORY_BONUS, 1.0)

        weights = np.clip(base_w * discount_w * cat_bonus, 1e-6, None)
        probs = weights / weights.sum()

        pos = rng.choice(idxs.size, p=probs)
        chosen = int(idxs[pos])

        self.available_mask[chosen] = False
        self.purchaser_order.append(chosen)
        self.purchaser_line_count[chosen] = 0
        self.purchaser_used_inventory[chosen] = set()
        self.purchaser_used_product[chosen] = set()
        return chosen

    def pick_extra_line_target(self, inventory_id: str, product_id: str, is_discounted: bool,
                                product_category: str, cap: int, rng: np.random.Generator):
        """Same 2-stage idea as pick_new_purchaser, restricted to visitors who are
        already purchasers today and still eligible for an additional line."""
        eligible = [
            idx for idx in self.purchaser_order
            if self.purchaser_line_count[idx] < MAX_LINES_PER_RECEIPT
            and inventory_id not in self.purchaser_used_inventory[idx]
            and product_id not in self.purchaser_used_product[idx]
        ]
        if not eligible:
            return None
        eligible_arr = np.array(eligible)

        household_probs = self.household_fit_probs[cap - 1]
        chosen_household = rng.choice(HOUSEHOLD_TYPES, p=household_probs)

        mask_h = self.household_types[eligible_arr] == chosen_household
        idxs = eligible_arr[mask_h]
        if idxs.size == 0:
            idxs = eligible_arr

        ps = self.price_sensitivity_norm[idxs]
        discount_w = np.where(
            is_discounted,
            np.exp(2.0 * (np.clip(ps, 0.0, 1.0) - 0.4)),
            1.05 - 0.10 * np.clip(ps, 0.0, 1.0),
        )
        cat = self.preferred_categories[idxs]
        cat_bonus = np.where(cat == product_category, PREFERRED_CATEGORY_BONUS, 1.0)
        weights = np.clip(discount_w * cat_bonus, 1e-6, None)
        probs = weights / weights.sum()

        pos = rng.choice(idxs.size, p=probs)
        return int(idxs[pos])

    def register_line(self, local_idx: int, inventory_id: str, product_id: str):
        self.purchaser_line_count[local_idx] += 1
        self.purchaser_used_inventory[local_idx].add(inventory_id)
        self.purchaser_used_product[local_idx].add(product_id)


def allocate_receipts(dfs: dict, customer_features: pd.DataFrame, quantity_table: dict,
                       expected_qty_table: dict, rng: np.random.Generator) -> dict:
    """
    store_id + current_date(visit_date) 단위로 inventory 의 daily_sold_qty 를
    실제 방문객에게 배분하여 receipt 라인을 생성한다.

    반환값: visitor_id -> {
        "customer_id", "store_id", "sale_date", "sale_time", "sale_datetime",
        "time_slot", "payment_method",
        "lines": [ {inventory_id, lot_id, product_id, quantity, unit_price,
                     discount_rate, sale_unit_price}, ... ],
        "group_key": (store_id, date_str),
    }
    """
    section("[12/16] inventory 판매수량 -> 방문객 배분 (receipt 라인 생성)")

    # dfs["visitor"] 는 main() 에서 이미 customer 파생 피처(household_type,
    # price_sensitivity_norm, preferred_category 등)가 merge 되어 있다.
    visitor = dfs["visitor"]
    if visitor["household_type"].isnull().any():
        fail("visitor 와 customer 병합 후 household_type 이 NULL 인 행이 있습니다. "
             "customer_id 연결에 문제가 있을 수 있습니다.")

    product = dfs["product"][["product_id", "category"]].drop_duplicates("product_id")
    product_category_map = dict(zip(product["product_id"], product["category"]))

    inventory = dfs["inventory"].copy()
    inventory["current_date"] = inventory["current_date"].astype(str)
    sold_inventory = inventory[inventory["daily_sold_qty"] > 0].copy()

    log(f"  - 배분 대상 inventory 행(daily_sold_qty>0): {len(sold_inventory):,} 건")
    log(f"  - 배분해야 할 총 판매수량: {int(sold_inventory['daily_sold_qty'].sum()):,} 개")

    visitor["visit_date_str"] = visitor["visit_date"].astype(str)

    visitor_groups = visitor.groupby(["store_id", "visit_date_str"], sort=False)
    inv_groups = sold_inventory.groupby(["store_id", "current_date"], sort=False)

    visitor_group_index = {key: idx for key, idx in visitor_groups.groups.items()}

    visitor_lines = {}          # visitor_id -> dict (라인/메타데이터)
    group_all_visitor_ids = {}  # group_key -> np.array(visitor_id) (전체, repair 단계에서 사용)
    group_purchaser_ids = defaultdict(list)  # group_key -> [visitor_id...] (repair 단계에서 사용)

    n_groups_total = inv_groups.ngroups
    n_groups_done = 0
    n_unallocated_qty = 0
    n_warn_no_candidate = 0

    for (store_id, date_str), inv_sub in inv_groups:
        n_groups_done += 1
        group_key = (store_id, date_str)

        if group_key not in visitor_group_index:
            n_unallocated_qty += int(inv_sub["daily_sold_qty"].sum())
            if n_warn_no_candidate < WARN_LOG_LIMIT:
                log(f"  - [WARNING] 방문객이 없는 (store={store_id}, date={date_str}) 그룹에 "
                    f"판매수량 {int(inv_sub['daily_sold_qty'].sum())}개가 존재하여 배분할 수 없습니다.")
            n_warn_no_candidate += 1
            continue

        sub_visitor = visitor.loc[visitor_group_index[group_key]]
        state = GroupAllocationState(sub_visitor, expected_qty_table)

        group_all_visitor_ids[group_key] = state.visitor_ids

        # 그룹 내 payment_method 를 구매자 등록 시점에 즉시 할당하기 위한 준비
        # (receipt 단위로 결제수단이 하나로 고정되어야 하므로 구매자 최초 등록 시 결정)

        inv_rows = inv_sub[[
            "inventory_id", "lot_id", "product_id", "daily_sold_qty",
            "unit_price", "discount_rate", "discount_price",
        ]].to_numpy()
        # 매장-일자 내 inventory 처리 순서를 무작위화하여 특정 상품 순서에 의한
        # 편향을 방지한다.
        order = rng.permutation(len(inv_rows))

        for oi in order:
            inventory_id, lot_id, product_id, remaining, unit_price, discount_rate, discount_price = inv_rows[oi]
            remaining = int(remaining)
            unit_price = int(unit_price)
            discount_rate = float(discount_rate)
            discount_price = int(discount_price)
            is_discounted = discount_rate > 0
            product_category = product_category_map.get(product_id)

            while remaining > 0:
                local_idx = None
                used_extra = False
                cap = min(remaining, MAX_QUANTITY)

                if state.purchaser_order and rng.random() < EXTRA_LINE_PROBABILITY:
                    local_idx = state.pick_extra_line_target(
                        inventory_id, product_id, is_discounted, product_category, cap, rng
                    )
                    if local_idx is not None:
                        used_extra = True

                if local_idx is None:
                    local_idx = state.pick_new_purchaser(is_discounted, product_category, cap, rng)

                if local_idx is None:
                    # [수정] 이전 코드는 "오늘 신규 구매자 후보가 없으면 기존
                    # 구매자 중 아무나"에게 배정했는데, 이는 영수증당 최대
                    # MAX_LINES_PER_RECEIPT 라인 제한이나 동일 inventory_id/
                    # product_id 중복 금지 규칙을 어길 수 있었다 (요청사항
                    # 5번). 이제는 pick_extra_line_target() 을 다시 호출해
                    # 두 규칙을 모두 지키는 기존 구매자가 있는지 탐색하고,
                    # 그런 대상이 전혀 없으면 판매수량을 임의로 누락하거나
                    # 규칙을 위반하지 않기 위해 즉시 명확한 오류로 중단한다.
                    local_idx = state.pick_extra_line_target(
                        inventory_id, product_id, is_discounted, product_category, cap, rng
                    )
                    if local_idx is not None:
                        used_extra = True
                    else:
                        fail(
                            f"(store={store_id}, date={date_str}) inventory_id={inventory_id} 의 "
                            f"잔여 판매수량 {remaining}개를 배정할 방문객을 찾지 못했습니다.\n"
                            "오늘 이 매장을 방문한 모든 고객이 이미 구매자로 등록되었거나, "
                            f"남은 구매자 전원이 영수증당 최대 {MAX_LINES_PER_RECEIPT}라인 제한 "
                            "또는 동일 inventory_id/product_id 중복 금지 규칙에 걸려 있어 더 "
                            "이상 배정할 수 없습니다. 판매수량을 임의로 누락하거나 규칙을 "
                            "위반하지 않기 위해 실행을 중단합니다."
                        )

                visitor_id = state.visitor_ids[local_idx]

                if visitor_id not in visitor_lines:
                    customer_id = state.customer_ids[local_idx]
                    payment_method = str(
                        rng.choice(
                            list(PAYMENT_METHOD_PROBABILITY.keys()),
                            p=list(PAYMENT_METHOD_PROBABILITY.values()),
                        )
                    )
                    visitor_lines[visitor_id] = {
                        "customer_id": customer_id,
                        "store_id": store_id,
                        "sale_date": date_str,
                        "sale_time": state.visit_times[local_idx],
                        "time_slot": state.time_slots[local_idx],
                        "payment_method": payment_method,
                        "lines": [],
                        "group_key": group_key,
                    }
                    group_purchaser_ids[group_key].append(visitor_id)

                household_type = state.household_types[local_idx]
                cap = min(remaining, MAX_QUANTITY)
                qty = sample_quantity(household_type, cap, quantity_table, rng)
                qty = min(qty, remaining, MAX_QUANTITY)
                if qty <= 0:
                    qty = 1

                visitor_lines[visitor_id]["lines"].append({
                    "inventory_id": inventory_id,
                    "lot_id": lot_id,
                    "product_id": product_id,
                    "quantity": int(qty),
                    "unit_price": unit_price,
                    "discount_rate": discount_rate,
                    "sale_unit_price": discount_price,
                })

                state.register_line(local_idx, inventory_id, product_id)
                remaining -= qty

        if n_groups_done % 200 == 0 or n_groups_done == n_groups_total:
            log(f"  - 진행률: {n_groups_done}/{n_groups_total} 그룹 처리 완료 "
                f"(누적 receipt 수={len(visitor_lines):,})")

    if n_unallocated_qty > 0:
        fail(
            f"방문객 부족 등으로 배분하지 못한 판매수량이 {n_unallocated_qty}개 있습니다. "
            "inventory 의 판매수량을 보존해야 하는 요구사항을 만족할 수 없으므로 중단합니다."
        )

    log(f"  - 배분 완료: 고유 구매 visitor 수 = {len(visitor_lines):,}")

    return {
        "visitor_lines": visitor_lines,
        "group_all_visitor_ids": group_all_visitor_ids,
        "group_purchaser_ids": group_purchaser_ids,
        "total_visitors": len(visitor),
    }


def repair_conversion_rate(alloc_result: dict, customer_features: pd.DataFrame,
                            visitor_meta: pd.DataFrame, rng: np.random.Generator) -> None:
    """
    최종 구매전환율이 16.5%~17.5% 범위를 벗어나면, 같은 (store, date) 그룹
    내부에서 라인을 다른 방문객으로 옮기는 방식으로 구매자 수를 조정한다.
    (inventory 판매수량 합계는 변하지 않는다 - 그룹 내부에서 "누구의 영수증인가"
    만 바뀐다.)
    """
    section("[13/16] 구매전환율 보정 (16.5% ~ 17.5% 목표)")

    visitor_lines = alloc_result["visitor_lines"]
    group_all_visitor_ids = alloc_result["group_all_visitor_ids"]
    group_purchaser_ids = alloc_result["group_purchaser_ids"]
    total_visitors = alloc_result["total_visitors"]

    customer_lookup = customer_features.set_index("customer_id")
    visitor_meta_lookup = visitor_meta.set_index("visitor_id")

    def current_conversion():
        return len(visitor_lines) / total_visitors

    conv = current_conversion()
    log(f"  - 보정 전 구매전환율: {conv:.4%} (구매자 {len(visitor_lines):,} / 전체 {total_visitors:,})")

    target_count_low = int(np.ceil(CONVERSION_LOWER_BOUND * total_visitors))
    target_count_high = int(np.floor(CONVERSION_UPPER_BOUND * total_visitors))

    n_iter = 0

    # ---- 구매자가 너무 많은 경우: 일부 구매자를 같은 그룹의 다른 구매자에게 합친다 ----
    while len(visitor_lines) > target_count_high and n_iter < CONVERSION_REPAIR_MAX_ITER:
        n_iter += 1
        # 단일 라인 구매자 중 임의로 하나 선택 (라인이 1개인 구매자를 우선 대상으로 함)
        single_line_visitors = [vid for vid, v in visitor_lines.items() if len(v["lines"]) == 1]
        if not single_line_visitors:
            log("  - [WARNING] 더 이상 병합 가능한 단일 라인 구매자가 없어 보정을 중단합니다.")
            break

        src_vid = single_line_visitors[int(rng.integers(0, len(single_line_visitors)))]
        src = visitor_lines[src_vid]
        group_key = src["group_key"]

        candidates = [
            vid for vid in group_purchaser_ids[group_key]
            if vid != src_vid and vid in visitor_lines
            and len(visitor_lines[vid]["lines"]) < MAX_LINES_PER_RECEIPT
        ]
        if not candidates:
            continue

        src_line = src["lines"][0]
        valid_targets = []
        for vid in candidates:
            tgt = visitor_lines[vid]
            used_inv = {ln["inventory_id"] for ln in tgt["lines"]}
            used_prod = {ln["product_id"] for ln in tgt["lines"]}
            if src_line["inventory_id"] in used_inv or src_line["product_id"] in used_prod:
                continue
            valid_targets.append(vid)
        if not valid_targets:
            continue

        tgt_vid = valid_targets[int(rng.integers(0, len(valid_targets)))]
        visitor_lines[tgt_vid]["lines"].append(src_line)
        del visitor_lines[src_vid]
        group_purchaser_ids[group_key] = [v for v in group_purchaser_ids[group_key] if v != src_vid]

    # ---- 구매자가 너무 적은 경우: 일부 다중 라인 구매자의 라인을 같은 그룹의
    #      비구매 방문객에게 분리해 새 receipt 로 만든다 ----
    while len(visitor_lines) < target_count_low and n_iter < CONVERSION_REPAIR_MAX_ITER:
        n_iter += 1
        multi_line_visitors = [vid for vid, v in visitor_lines.items() if len(v["lines"]) >= 2]
        if not multi_line_visitors:
            log("  - [WARNING] 더 이상 분리 가능한 다중 라인 구매자가 없어 보정을 중단합니다.")
            break

        src_vid = multi_line_visitors[int(rng.integers(0, len(multi_line_visitors)))]
        src = visitor_lines[src_vid]
        group_key = src["group_key"]

        all_ids = group_all_visitor_ids.get(group_key)
        if all_ids is None or len(all_ids) == 0:
            continue
        non_purchasers = [vid for vid in all_ids if vid not in visitor_lines]
        if not non_purchasers:
            continue

        new_vid = non_purchasers[int(rng.integers(0, len(non_purchasers)))]
        moved_line = src["lines"].pop()

        cust_id = visitor_meta_lookup.loc[new_vid, "customer_id"]
        sale_time = visitor_meta_lookup.loc[new_vid, "visit_time"]
        time_slot = visitor_meta_lookup.loc[new_vid, "time_slot"]

        payment_method = str(
            rng.choice(list(PAYMENT_METHOD_PROBABILITY.keys()), p=list(PAYMENT_METHOD_PROBABILITY.values()))
        )
        visitor_lines[new_vid] = {
            "customer_id": cust_id,
            "store_id": group_key[0],
            "sale_date": group_key[1],
            "sale_time": sale_time,
            "time_slot": time_slot,
            "payment_method": payment_method,
            "lines": [moved_line],
            "group_key": group_key,
        }
        group_purchaser_ids[group_key].append(new_vid)

    conv_after = current_conversion()
    log(f"  - 보정 반복 횟수: {n_iter}")
    log(f"  - 보정 후 구매전환율: {conv_after:.4%} (구매자 {len(visitor_lines):,} / 전체 {total_visitors:,})")

    if not (CONVERSION_LOWER_BOUND <= conv_after <= CONVERSION_UPPER_BOUND):
        log(f"  - [WARNING] 목표 범위(16.5%~17.5%) 를 벗어났습니다. "
            f"현재 데이터 구조(그룹별 재고/방문객 비율)상 도달 가능한 값이 아닐 수 있습니다.")


# =============================================================================
# 11. receipt 행 생성 함수 (최종 DataFrame 조립)
# =============================================================================

def build_receipt_dataframe(alloc_result: dict) -> pd.DataFrame:
    """visitor_lines 딕셔너리를 최종 18개 컬럼의 DataFrame 으로 변환한다."""
    section("[14/16] 최종 receipt DataFrame 조립")

    visitor_lines = alloc_result["visitor_lines"]

    # visitor_id 기준으로 정렬하여 receipt_id 를 결정론적으로 부여한다.
    ordered_visitor_ids = sorted(visitor_lines.keys())
    n_receipts = len(ordered_visitor_ids)
    digits = max(6, len(str(n_receipts)))

    rows = []
    for i, vid in enumerate(ordered_visitor_ids, start=1):
        v = visitor_lines[vid]
        receipt_id = "REC" + str(i).zfill(digits)
        sale_date = v["sale_date"]
        sale_time = v["sale_time"]
        sale_datetime = f"{sale_date} {sale_time}"

        for line_no, ln in enumerate(v["lines"], start=1):
            quantity = int(ln["quantity"])
            unit_price = int(ln["unit_price"])
            discount_rate = ln["discount_rate"]
            sale_unit_price = int(ln["sale_unit_price"])
            line_amount = int(quantity * sale_unit_price)

            rows.append({
                "receipt_id": receipt_id,
                "line_no": line_no,
                "visitor_id": vid,
                "customer_id": v["customer_id"],
                "store_id": v["store_id"],
                "sale_date": sale_date,
                "sale_time": sale_time,
                "sale_datetime": sale_datetime,
                "time_slot": v["time_slot"],
                "inventory_id": ln["inventory_id"],
                "lot_id": ln["lot_id"],
                "product_id": ln["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_rate": discount_rate,
                "sale_unit_price": sale_unit_price,
                "line_amount": line_amount,
                "payment_method": v["payment_method"],
            })

    receipt_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)

    # 정수형 컬럼 dtype 명시적 고정
    int_cols = ["line_no", "quantity", "unit_price", "sale_unit_price", "line_amount"]
    for col in int_cols:
        receipt_df[col] = receipt_df[col].astype(np.int64)

    # discount_rate 는 inventory.csv 원본과 동일한 단위를 사용해야 하므로,
    # 값이 전부 정수라면(예: 0, 30, 40) int64 로, 소수가 섞여 있다면 float 로 둔다.
    dr = receipt_df["discount_rate"]
    if (dr.dropna() == dr.dropna().astype(np.int64)).all():
        receipt_df["discount_rate"] = dr.astype(np.int64)
    else:
        receipt_df["discount_rate"] = dr.astype(float)

    log(f"  - 조립 완료: {len(receipt_df):,} 행, 고유 receipt_id {receipt_df['receipt_id'].nunique():,}개")

    return receipt_df


# =============================================================================
# 12. 사후 교차검증 함수
# =============================================================================

def run_post_validations(receipt_df: pd.DataFrame, dfs: dict, customer_features: pd.DataFrame) -> dict:
    """요구사항 31번의 모든 사후 검증을 수행한다. 하나라도 FAIL 이면 예외를 발생시킨다."""
    section("[15/16] 사후 교차검증 (PASS / WARNING / FAIL)")

    results = {}
    fail_messages = []

    def record(name, ok, detail, level="PASS/FAIL"):
        status = "PASS" if ok else "FAIL"
        results[name] = status
        log(f"  - [{status}] {name}: {detail}")
        if not ok:
            fail_messages.append(f"{name}: {detail}")

    def record_warn(name, ok, detail):
        status = "PASS" if ok else "WARNING"
        results[name] = status
        log(f"  - [{status}] {name}: {detail}")

    # 31-1 출력 컬럼 검증
    ok = list(receipt_df.columns) == OUTPUT_COLUMNS
    record("31-1 출력 컬럼/순서", ok, f"실제={list(receipt_df.columns)}")

    # 31-2 결측값 검증
    n_null = int(receipt_df[OUTPUT_COLUMNS].isnull().sum().sum())
    record("31-2 결측값", n_null == 0, f"결측 셀 수={n_null}")

    # 31-3 receipt_id + line_no 중복 검증
    dup = receipt_df.duplicated(subset=["receipt_id", "line_no"]).sum()
    record("31-3 receipt_id+line_no 중복", dup == 0, f"중복 {dup}건")

    # 31-4 방문 연결 검증
    visitor_ids_set = set(dfs["visitor"]["visitor_id"])
    missing_visitor = set(receipt_df["visitor_id"]) - visitor_ids_set
    record("31-4 visitor_id 연결", len(missing_visitor) == 0, f"미연결 {len(missing_visitor)}건")

    # 31-5, 31-6, 31-7 visitor 메타데이터 일치 검증
    visitor_key = dfs["visitor"].set_index("visitor_id")
    merged_check = receipt_df.drop_duplicates("visitor_id").set_index("visitor_id")
    merged_check = merged_check.join(
        visitor_key[["customer_id", "store_id", "visit_date", "visit_time", "time_slot"]],
        rsuffix="_visitor",
    )
    n_cust_mismatch = int((merged_check["customer_id"] != merged_check["customer_id_visitor"]).sum())
    record("31-5 customer_id 일치", n_cust_mismatch == 0, f"불일치 {n_cust_mismatch}건")

    n_store_mismatch = int((merged_check["store_id"] != merged_check["store_id_visitor"]).sum())
    record("31-6 store_id 일치", n_store_mismatch == 0, f"불일치 {n_store_mismatch}건")

    n_date_mismatch = int((merged_check["sale_date"].astype(str) != merged_check["visit_date"].astype(str)).sum())
    n_time_mismatch = int((merged_check["sale_time"].astype(str) != merged_check["visit_time"].astype(str)).sum())
    n_slot_mismatch = int((merged_check["time_slot"] != merged_check["time_slot_visitor"]).sum())
    record(
        "31-7 sale_date/sale_time/time_slot 일치",
        (n_date_mismatch == 0 and n_time_mismatch == 0 and n_slot_mismatch == 0),
        f"date불일치={n_date_mismatch}, time불일치={n_time_mismatch}, slot불일치={n_slot_mismatch}",
    )

    # 31-8 inventory 연결 검증 (inventory_id, lot_id, product_id)
    inv = dfs["inventory"]
    inv_key = inv.set_index("inventory_id")
    missing_inv = set(receipt_df["inventory_id"]) - set(inv["inventory_id"])
    record("31-8a inventory_id 연결", len(missing_inv) == 0, f"미연결 {len(missing_inv)}건")

    joined_inv = receipt_df.join(
        inv_key[["lot_id", "product_id", "store_id", "current_date"]], on="inventory_id", rsuffix="_inv"
    )
    n_lot_mismatch = int((joined_inv["lot_id"] != joined_inv["lot_id_inv"]).sum())
    n_prod_mismatch = int((joined_inv["product_id"] != joined_inv["product_id_inv"]).sum())
    record("31-8b lot_id 일치", n_lot_mismatch == 0, f"불일치 {n_lot_mismatch}건")
    record("31-8c product_id 일치", n_prod_mismatch == 0, f"불일치 {n_prod_mismatch}건")

    # 31-9 inventory 매장/날짜 검증
    n_store_inv_mismatch = int((joined_inv["store_id"] != joined_inv["store_id_inv"]).sum())
    n_date_inv_mismatch = int((joined_inv["sale_date"].astype(str) != joined_inv["current_date"].astype(str)).sum())
    record(
        "31-9 inventory store/date 일치",
        (n_store_inv_mismatch == 0 and n_date_inv_mismatch == 0),
        f"store불일치={n_store_inv_mismatch}, date불일치={n_date_inv_mismatch}",
    )

    # 31-10 판매수량 보존 검증
    inv_sold = inv[inv["daily_sold_qty"] > 0].set_index("inventory_id")["daily_sold_qty"]
    receipt_qty_sum = receipt_df.groupby("inventory_id")["quantity"].sum()
    compare = pd.DataFrame({"inventory_qty": inv_sold, "receipt_qty": receipt_qty_sum}).fillna(0)
    n_mismatch = int((compare["inventory_qty"] != compare["receipt_qty"]).sum())
    record(
        "31-10 inventory_id별 판매수량 보존",
        n_mismatch == 0,
        f"불일치 inventory_id {n_mismatch}건 "
        f"(inventory 합계={int(inv_sold.sum()):,}, receipt 합계={int(receipt_qty_sum.sum()):,})",
    )
    zero_sold_ids = set(inv[inv["daily_sold_qty"] == 0]["inventory_id"])
    n_zero_in_receipt = len(zero_sold_ids & set(receipt_df["inventory_id"]))
    record("31-10b 판매수량 0인 inventory 미포함", n_zero_in_receipt == 0, f"위반 {n_zero_in_receipt}건")

    # 31-11 수량 범위 검증
    qmin, qmax = receipt_df["quantity"].min(), receipt_df["quantity"].max()
    record("31-11 quantity 범위(1~5)", (qmin >= MIN_QUANTITY and qmax <= MAX_QUANTITY), f"min={qmin}, max={qmax}")

    # 31-12 household_type 평균 검증
    cust_lookup = customer_features.set_index("customer_id")["household_type"]
    receipt_with_hh = receipt_df.join(cust_lookup, on="customer_id")
    hh_avg = receipt_with_hh.groupby("household_type")["quantity"].mean()
    log(f"      household_type 별 quantity 평균: {hh_avg.to_dict()}")
    hh_ok = True
    for hh, (low, high) in QUANTITY_TARGET_RANGE.items():
        val = hh_avg.get(hh, np.nan)
        in_range = (not np.isnan(val)) and (low <= val <= high)
        log(f"      · {hh}: 실제={val:.4f} / 목표범위=({low}~{high}) -> {'PASS' if in_range else 'WARNING'}")
        hh_ok = hh_ok and in_range
    order_ok = (
        hh_avg.get("family", -1) > hh_avg.get("couple", -1) > hh_avg.get("senior", -1) > hh_avg.get("single", -1)
    )
    all_same = len(set(np.round(hh_avg.values, 2))) == 1
    # [수정] 기존 코드는 hh_ok(4개 가구유형이 모두 목표 범위 내에 있는지)를
    # 계산만 하고 실제 PASS 판정에는 반영하지 않아, 순서와 비동일성만
    # 만족하면 목표 범위를 벗어나도 PASS 로 처리되는 문제가 있었다. 이제는
    # hh_ok 를 반드시 AND 조건에 포함해, 4개 가구유형 평균이 각각 지정된
    # 목표 범위 안에 있어야만 PASS 가 되도록 한다.
    record(
        "31-12 household_type quantity 평균",
        order_ok and (not all_same) and hh_ok,
        f"family>couple>senior>single 순서 만족={order_ok}, 전부동일값={all_same}, 목표범위충족(hh_ok)={hh_ok}",
    )

    # 31-13 price_sensitivity 4분위 할인 구매 비중 검증
    # [수정] (1) 분위를 receipt 라인 단위가 아니라 customer_id 단위로 먼저
    # 만든 뒤 receipt 에 many_to_one 으로 병합한다 (compute_price_sensitivity_
    # quartiles 사용, 요청사항 3번). (2) 기존에는 Q4_high > Q1_low 이기만
    # 하면 PASS, 5%p 미만이면 WARNING 만 출력했는데, 이제는 diff >= 0.05 를
    # 만족해야만 PASS 이고 미만이면 FAIL 로 처리한다 (요청사항 2번). (3) 기본
    # PASS 판정 지표가 discount_line_share(할인 라인 수/전체 라인 수) 임을
    # 로그에 명시하고, discount_qty_share 와 "할인 포함 영수증 비중"은 참고
    # 지표로만 함께 출력한다 (요청사항 4번).
    customer_quartiles = compute_price_sensitivity_quartiles(customer_features)
    receipt_with_ps = receipt_df.merge(
        customer_quartiles, on="customer_id", how="left", validate="many_to_one"
    )
    if receipt_with_ps["ps_quartile"].isnull().any():
        fail("receipt 를 고객별 price_sensitivity 분위와 병합하는 과정에서 "
             "ps_quartile 이 NULL 인 행이 발생했습니다. customer_id 연결을 확인해주세요.")

    quartile_labels = ["Q1_low", "Q2", "Q3", "Q4_high"]
    receipt_with_ps["is_discount_line"] = receipt_with_ps["discount_rate"] > 0

    quartile_stats = receipt_with_ps.groupby("ps_quartile", observed=True).agg(
        n_customers=("customer_id", "nunique"),
        n_lines=("receipt_id", "size"),
        total_qty=("quantity", "sum"),
        discount_lines=("is_discount_line", "sum"),
    )
    # 기본 PASS 판정 지표: 할인 상품 라인 수 / 전체 상품 라인 수
    quartile_stats["discount_line_share"] = quartile_stats["discount_lines"] / quartile_stats["n_lines"]
    # 참고 지표: 할인 상품 "수량" 비중
    discount_qty = receipt_with_ps[receipt_with_ps["is_discount_line"]].groupby(
        "ps_quartile", observed=True
    )["quantity"].sum()
    quartile_stats["discount_qty_share"] = (discount_qty / quartile_stats["total_qty"]).fillna(0)
    # 참고 지표: 할인 상품이 1개 이상 포함된 영수증 비중
    receipt_has_discount = receipt_with_ps.groupby(["ps_quartile", "receipt_id"], observed=True)[
        "is_discount_line"
    ].any().reset_index()
    quartile_stats["discount_receipt_share"] = receipt_has_discount.groupby(
        "ps_quartile", observed=True
    )["is_discount_line"].mean()

    log("      가격민감도 분위는 receipt 라인이 아니라 customer_id 단위로 생성했습니다 "
        "(rank(method='first')로 동점 처리 후 4분위).")
    log("      PASS 판정 기준 지표 = discount_line_share (할인 상품 라인 수 / 전체 상품 라인 수)")
    log(f"      가격민감도 분위별 통계:\n{quartile_stats}")

    q1_share = quartile_stats.loc["Q1_low", "discount_line_share"] if "Q1_low" in quartile_stats.index else np.nan
    q4_share = quartile_stats.loc["Q4_high", "discount_line_share"] if "Q4_high" in quartile_stats.index else np.nan
    diff = q4_share - q1_share
    monotonic = list(quartile_stats.reindex(quartile_labels)["discount_line_share"])
    is_monotonic_nondecreasing = all(
        monotonic[i] <= monotonic[i + 1] + 1e-9 for i in range(len(monotonic) - 1) if not np.isnan(monotonic[i])
    )
    record(
        "31-13 Q4_high-Q1_low discount_line_share 차이 >= 5%p",
        (not np.isnan(diff)) and (diff >= 0.05),
        f"discount_line_share 기준 Q1_low={q1_share:.4f}, Q4_high={q4_share:.4f}, "
        f"차이={diff:.4f} (PASS 기준: diff >= 0.05, 단순 Q4>Q1 만으로는 PASS 처리하지 않음)",
    )
    record_warn("31-13b 분위 단조증가 여부(Q1<Q2<Q3<Q4)", is_monotonic_nondecreasing, f"분위별 비중={monotonic}")

    # 31-14 가격 계산 검증
    calc_amount = receipt_df["quantity"] * receipt_df["sale_unit_price"]
    n_amount_mismatch = int((calc_amount != receipt_df["line_amount"]).sum())
    record("31-14a line_amount = quantity*sale_unit_price", n_amount_mismatch == 0, f"불일치 {n_amount_mismatch}건")

    zero_discount = receipt_df[receipt_df["discount_rate"] == 0]
    n_zero_mismatch = int((zero_discount["sale_unit_price"] != zero_discount["unit_price"]).sum())
    record("31-14b 할인율0 -> sale_unit_price=unit_price", n_zero_mismatch == 0, f"불일치 {n_zero_mismatch}건")

    pos_discount = receipt_df[receipt_df["discount_rate"] > 0]
    n_gt_mismatch = int((pos_discount["sale_unit_price"] > pos_discount["unit_price"]).sum())
    record("31-14c 할인율>0 -> sale_unit_price<=unit_price", n_gt_mismatch == 0, f"위반 {n_gt_mismatch}건")

    n_negative_price = int((receipt_df["sale_unit_price"] < 0).sum())
    record("31-14d sale_unit_price>=0", n_negative_price == 0, f"음수 {n_negative_price}건")

    # 31-15 할인율 상한 검증
    max_dr = receipt_df["discount_rate"].max()
    record("31-15 discount_rate<=40", max_dr <= MAX_DISCOUNT_RATE_PCT, f"최대값={max_dr}")

    # 31-16 영수증 단위 검증
    receipt_visitor_count = receipt_df.groupby("receipt_id")["visitor_id"].nunique()
    visitor_receipt_count = receipt_df.groupby("visitor_id")["receipt_id"].nunique()
    receipt_payment_count = receipt_df.groupby("receipt_id")["payment_method"].nunique()
    record("31-16a receipt_id당 visitor_id 1개", (receipt_visitor_count == 1).all(),
           f"위반 {(receipt_visitor_count != 1).sum()}건")
    record("31-16b visitor_id당 receipt_id 최대 1개", (visitor_receipt_count == 1).all(),
           f"위반 {(visitor_receipt_count != 1).sum()}건")
    record("31-16c receipt_id당 payment_method 1개", (receipt_payment_count == 1).all(),
           f"위반 {(receipt_payment_count != 1).sum()}건")

    # 31-17 line_no 검증
    def check_line_no(group):
        expected = list(range(1, len(group) + 1))
        return sorted(group["line_no"].tolist()) == expected

    line_no_ok = receipt_df.groupby("receipt_id").apply(check_line_no, include_groups=False)
    n_line_no_bad = int((~line_no_ok).sum())
    record("31-17 line_no 1부터 연속", n_line_no_bad == 0, f"위반 receipt {n_line_no_bad}건")

    # [신규] 31-21 영수증 최대 라인 수 검증 (요청사항 5번)
    # MAX_LINES_PER_RECEIPT = 3 이므로, 어떤 receipt_id 도 3개 초과 라인을
    # 가지면 안 된다.
    lines_per_receipt = receipt_df.groupby("receipt_id").size()
    n_over_max_lines = int((lines_per_receipt > MAX_LINES_PER_RECEIPT).sum())
    record(
        f"31-21 receipt_id당 최대 {MAX_LINES_PER_RECEIPT}라인 이하",
        n_over_max_lines == 0,
        f"위반 receipt {n_over_max_lines}건 (관측된 최대 라인 수={int(lines_per_receipt.max())})",
    )

    # [신규] 31-22 / 31-23 영수증 내 동일 inventory_id / product_id 중복 금지
    # 검증 (요청사항 6번). groupby().apply() 는 receipt_id 그룹이 10만개
    # 이상일 때 매우 느리므로, duplicated(subset=[...]) 를 이용한 벡터화
    # 방식으로 구현한다 (동일 receipt_id 안에서 같은 값이 2번째 이상
    # 등장하는 행을 찾아 해당 receipt_id 집합의 크기를 센다).
    dup_inv_mask = receipt_df.duplicated(subset=["receipt_id", "inventory_id"])
    n_receipts_with_dup_inv = int(receipt_df.loc[dup_inv_mask, "receipt_id"].nunique())
    record(
        "31-22 영수증 내 동일 inventory_id 중복 금지",
        n_receipts_with_dup_inv == 0,
        f"위반 receipt {n_receipts_with_dup_inv}건",
    )

    dup_prod_mask = receipt_df.duplicated(subset=["receipt_id", "product_id"])
    n_receipts_with_dup_prod = int(receipt_df.loc[dup_prod_mask, "receipt_id"].nunique())
    record(
        "31-23 영수증 내 동일 product_id 중복 금지",
        n_receipts_with_dup_prod == 0,
        f"위반 receipt {n_receipts_with_dup_prod}건",
    )

    # 31-18 구매전환율 검증
    total_visitors = len(dfs["visitor"])
    unique_purchasers = receipt_df["visitor_id"].nunique()
    conversion = unique_purchasers / total_visitors
    record(
        "31-18 구매전환율(16.5%~17.5%)",
        CONVERSION_LOWER_BOUND <= conversion <= CONVERSION_UPPER_BOUND,
        f"전환율={conversion:.4%} (구매자 {unique_purchasers:,} / 전체 {total_visitors:,})",
    )

    # 31-19 영수증당 평균 상품 종류 수
    avg_lines_per_receipt = len(receipt_df) / receipt_df["receipt_id"].nunique()
    low, high = RECEIPT_LINE_COUNT_TARGET_RANGE
    record(
        "31-19 영수증당 평균 상품종류(1.05~1.20)",
        low <= avg_lines_per_receipt <= high,
        f"실제={avg_lines_per_receipt:.4f}",
    )

    # 31-20 의무휴업일 검증
    store_calendar = dfs["store_calendar"]
    closed = store_calendar[(store_calendar["is_mandatory_closed"] == 1) | (store_calendar["is_open"] == 0)]
    closed_set = set(zip(closed["store_id"], closed["date"].astype(str)))
    receipt_keys = list(zip(receipt_df["store_id"], receipt_df["sale_date"].astype(str)))
    n_closed_violation = sum(1 for k in receipt_keys if k in closed_set)
    record("31-20 의무휴업일 판매 0건", n_closed_violation == 0, f"위반 {n_closed_violation}건")

    if fail_messages:
        fail("사후 검증에서 FAIL 항목이 발견되어 receipt.csv 를 저장하지 않습니다:\n" +
             "\n".join(f"  - {m}" for m in fail_messages))

    return results


# =============================================================================
# 13. 결과 요약 함수
# =============================================================================

def print_summary(dfs: dict, receipt_df: pd.DataFrame, customer_features: pd.DataFrame,
                   validation_results: dict) -> None:
    """
    [수정] 사용자가 요청한 19개 항목(재생성 및 검증 섹션)을 번호를 붙여
    명시적으로 모두 출력하도록 재작성했다. price_sensitivity 분위는
    compute_price_sensitivity_quartiles() 로 고객 단위로 통일해서 사용한다
    (run_post_validations 의 31-13 검증과 동일한 로직/결과를 보장하기 위함).
    """
    section("[16/16] 생성 결과 요약")

    log("")
    log("=== 입력 데이터 요약 ===")
    for key in ["store", "store_visitor_profile", "calendar", "store_calendar",
                "product", "customer", "inventory", "visitor"]:
        log(f"  {key}.csv shape = {dfs[key].shape}")

    total_visitors = len(dfs["visitor"])
    unique_purchasers = receipt_df["visitor_id"].nunique()
    unique_receipts = receipt_df["receipt_id"].nunique()
    conversion = unique_purchasers / total_visitors

    inv = dfs["inventory"]
    inv_sold = inv[inv["daily_sold_qty"] > 0].set_index("inventory_id")["daily_sold_qty"]
    receipt_qty_by_inv = receipt_df.groupby("inventory_id")["quantity"].sum()
    qty_compare = pd.DataFrame({"inv_qty": inv_sold, "receipt_qty": receipt_qty_by_inv}).fillna(0)
    n_qty_mismatch = int((qty_compare["inv_qty"] != qty_compare["receipt_qty"]).sum())
    inv_sold_sum = int(inv_sold.sum())
    receipt_qty_sum = int(receipt_df["quantity"].sum())

    lines_per_receipt = receipt_df.groupby("receipt_id").size()
    avg_lines = len(receipt_df) / unique_receipts
    max_lines = int(lines_per_receipt.max())

    dup_inv_mask = receipt_df.duplicated(subset=["receipt_id", "inventory_id"])
    n_receipts_with_dup_inv = int(receipt_df.loc[dup_inv_mask, "receipt_id"].nunique())
    dup_prod_mask = receipt_df.duplicated(subset=["receipt_id", "product_id"])
    n_receipts_with_dup_prod = int(receipt_df.loc[dup_prod_mask, "receipt_id"].nunique())

    log("")
    log("=== receipt.csv 생성 결과 (요청 항목 1~9) ===")
    log(f"  1. receipt 상세 행 수 = {len(receipt_df):,}")
    log(f"  2. 고유 receipt 수 = {unique_receipts:,}")
    log(f"  3. 전체 방문자 수 = {total_visitors:,}")
    log(f"  4. 구매전환율 = {conversion:.4%} (구매자 {unique_purchasers:,}명, 목표 16.5%~17.5%)")
    log(f"  5. 총 quantity = {receipt_qty_sum:,}")
    log(f"  6. inventory.daily_sold_qty 합계 = {inv_sold_sum:,} / receipt.quantity 합계 = {receipt_qty_sum:,}")
    log(f"  7. inventory_id별 quantity 불일치 건수 = {n_qty_mismatch}")
    log(f"  8. 영수증당 평균 상품종류 = {avg_lines:.4f}")
    log(f"  9. 영수증당 최대 상품종류 = {max_lines} (제한 MAX_LINES_PER_RECEIPT={MAX_LINES_PER_RECEIPT})")
    log(f"  (참고) 전체 매출액 = {int(receipt_df['line_amount'].sum()):,} 원")
    log(f"  (참고) quantity 최소값={receipt_df['quantity'].min()}, 최대값={receipt_df['quantity'].max()}, "
        f"최대 할인율={receipt_df['discount_rate'].max()}")

    log("")
    log("=== 10. household_type별 quantity 평균과 목표 범위 ===")
    cust_lookup = customer_features.set_index("customer_id")["household_type"]
    tmp = receipt_df.join(cust_lookup, on="customer_id")
    hh_stat = tmp.groupby("household_type")["quantity"].agg(["count", "mean", "median", "max", "sum"])
    log(f"\n{hh_stat}")
    for hh, (low, high) in QUANTITY_TARGET_RANGE.items():
        val = float(hh_stat.loc[hh, "mean"]) if hh in hh_stat.index else float("nan")
        in_range = low <= val <= high
        log(f"      {hh}: 실제 평균={val:.4f} / 목표범위=({low}~{high}) -> {'PASS' if in_range else 'FAIL'}")

    log("")
    log("=== 11~15. price_sensitivity 분위별 할인 구매 분석 (고객 단위 분위) ===")
    customer_quartiles = compute_price_sensitivity_quartiles(customer_features)
    tmp2 = receipt_df.merge(customer_quartiles, on="customer_id", how="left", validate="many_to_one")
    tmp2["is_discount"] = tmp2["discount_rate"] > 0
    qstat = tmp2.groupby("ps_quartile", observed=True).agg(
        n_customers=("customer_id", "nunique"),
        n_lines=("receipt_id", "size"),
        total_qty=("quantity", "sum"),
    )
    disc_lines = tmp2[tmp2["is_discount"]].groupby("ps_quartile", observed=True).size()
    disc_qty = tmp2[tmp2["is_discount"]].groupby("ps_quartile", observed=True)["quantity"].sum()
    qstat["discount_line_share"] = (disc_lines / qstat["n_lines"]).fillna(0)
    qstat["discount_qty_share"] = (disc_qty / qstat["total_qty"]).fillna(0)
    receipt_has_discount = tmp2.groupby(["ps_quartile", "receipt_id"], observed=True)["is_discount"].any().reset_index()
    qstat["discount_receipt_share"] = receipt_has_discount.groupby("ps_quartile", observed=True)["is_discount"].mean()

    log(f"  11. 분위별 고객 수:\n{qstat['n_customers']}")
    log(f"  12. 분위별 할인 라인 비중(discount_line_share, PASS 판정 기준):\n{qstat['discount_line_share']}")
    if "Q1_low" in qstat.index and "Q4_high" in qstat.index:
        gap = qstat.loc["Q4_high", "discount_line_share"] - qstat.loc["Q1_low", "discount_line_share"]
        log(f"  13. Q4_high - Q1_low (discount_line_share 차이) = {gap:.4f} ({gap * 100:.2f}%p, 기준 >=5.00%p)")
    log(f"  14. 분위별 할인 수량 비중(discount_qty_share, 참고지표):\n{qstat['discount_qty_share']}")
    log(f"  15. 분위별 할인 포함 영수증 비중(discount_receipt_share, 참고지표):\n{qstat['discount_receipt_share']}")

    log("")
    log("=== 16~17. 영수증 내 중복 검증 ===")
    log(f"  16. 영수증 내 동일 inventory_id 중복 건수 = {n_receipts_with_dup_inv}")
    log(f"  17. 영수증 내 동일 product_id 중복 건수 = {n_receipts_with_dup_prod}")

    log("")
    log("=== 18. 사후검증 항목별 PASS/FAIL/WARNING ===")
    for name, status in validation_results.items():
        log(f"  [{status}] {name}")

    n_fail = sum(1 for v in validation_results.values() if v == "FAIL")
    log("")
    log(f"  19. 총 FAIL 건수 = {n_fail}")


# =============================================================================
# 14. 안전한 파일 저장 함수
# =============================================================================

def save_receipt_csv(receipt_df: pd.DataFrame, temp_path: Path, final_path: Path) -> None:
    """
    임시 파일로 먼저 저장한 뒤, 저장 결과를 재검증하고 문제가 없을 때만
    최종 파일명으로 이동한다.
    """
    section("최종 CSV 저장")

    receipt_df.to_csv(temp_path, index=False, encoding="utf-8-sig")
    log(f"  - 임시 파일 저장 완료: {temp_path}")

    reread = pd.read_csv(temp_path, encoding="utf-8-sig")

    problems = []
    if reread.shape[0] != receipt_df.shape[0]:
        problems.append(f"행 수 불일치: 저장 전={receipt_df.shape[0]}, 재로드={reread.shape[0]}")
    if list(reread.columns) != OUTPUT_COLUMNS:
        problems.append(f"컬럼 순서 불일치: {list(reread.columns)}")
    if reread[OUTPUT_COLUMNS].isnull().sum().sum() > 0:
        problems.append("재로드한 파일에 결측값이 있습니다 (파일이 잘렸을 가능성).")

    last_row = reread.iloc[-1]
    if last_row[["receipt_id", "line_no", "visitor_id", "quantity", "line_amount"]].isnull().any():
        problems.append(f"마지막 행이 비정상적으로 잘려 있습니다: {last_row.to_dict()}")

    int_cols = ["line_no", "quantity", "unit_price", "sale_unit_price", "line_amount"]
    for col in int_cols:
        if not np.issubdtype(reread[col].dtype, np.integer):
            try:
                as_int = reread[col].astype(np.int64)
                if not (as_int == reread[col]).all():
                    problems.append(f"{col} 컬럼이 정수로 정확히 복원되지 않습니다.")
            except Exception:
                problems.append(f"{col} 컬럼이 정수형이 아닙니다 (dtype={reread[col].dtype}).")

    total_qty_before = int(receipt_df["quantity"].sum())
    total_qty_after = int(reread["quantity"].sum())
    total_amount_before = int(receipt_df["line_amount"].sum())
    total_amount_after = int(reread["line_amount"].sum())
    if total_qty_before != total_qty_after:
        problems.append(f"총 판매수량 불일치: 저장 전={total_qty_before}, 재로드={total_qty_after}")
    if total_amount_before != total_amount_after:
        problems.append(f"총 매출액 불일치: 저장 전={total_amount_before}, 재로드={total_amount_after}")

    if problems:
        if temp_path.exists():
            temp_path.unlink()
        fail("저장된 파일 재검증에 실패했습니다 (기존 receipt.csv 를 덮어쓰지 않습니다):\n"
             + "\n".join(f"  - {p}" for p in problems))

    shutil.move(str(temp_path), str(final_path))
    log(f"  - 재검증 PASS. 최종 파일로 이동 완료: {final_path}")
    log(f"    shape={reread.shape}, 총 판매수량={total_qty_after:,}, 총 매출액={total_amount_after:,}원")


# =============================================================================
# 15. main 함수
# =============================================================================

def main():
    log("=" * 78)
    log("09_generate_receipt_data.py 실행 시작")
    log(f"RANDOM_SEED = {RANDOM_SEED}")
    log(f"BASE_DIR = {BASE_DIR}")
    log("=" * 78)

    # 1) 로드
    dfs = load_all_inputs(BASE_DIR)

    # 2) 사전 검증
    check_required_columns(dfs)
    check_duplicate_column_names(dfs)
    check_id_nulls(dfs)
    check_primary_key_uniqueness(dfs)
    check_numeric_ranges(dfs)
    check_id_referential_integrity(dfs)
    check_product_category_scope(dfs)

    # 3) 날짜/시간 전처리 + 의무휴업일 검증
    preprocess_datetime(dfs)
    verify_no_mandatory_closed_activity(dfs)

    # 4) 고객 파생 피처 + quantity 확률 테이블
    customer_features = build_customer_features(dfs)
    quantity_table = build_quantity_lookup_tables()
    expected_qty_table = build_expected_quantity_table(quantity_table)

    # visitor 에 customer 파생 피처를 미리 merge 해 둔다 (배분 단계에서 재사용).
    visitor_with_features = dfs["visitor"].merge(
        customer_features[[
            "customer_id", "household_type", "price_sensitivity", "price_sensitivity_norm",
            "freshness_sensitivity", "preferred_category", "purchase_base_weight",
        ]],
        on="customer_id", how="left", validate="many_to_one",
    )
    if visitor_with_features["household_type"].isnull().any():
        fail("visitor 와 customer 병합 후 household_type 이 NULL 인 행이 있습니다.")
    dfs["visitor"] = visitor_with_features

    # 5) 배분 (핵심 로직)
    alloc_result = allocate_receipts(dfs, customer_features, quantity_table, expected_qty_table, rng)

    # 6) 구매전환율 보정
    repair_conversion_rate(alloc_result, customer_features, dfs["visitor"], rng)

    # 7) 최종 DataFrame 조립
    receipt_df = build_receipt_dataframe(alloc_result)

    # 8) 사후 검증 (FAIL 시 여기서 SystemExit 발생 -> 저장하지 않음)
    validation_results = run_post_validations(receipt_df, dfs, customer_features)

    # 9) 결과 요약 출력
    print_summary(dfs, receipt_df, customer_features, validation_results)

    # 10) 저장 (검증 통과 시에만)
    save_receipt_csv(receipt_df, TEMP_OUTPUT_PATH, FINAL_OUTPUT_PATH)

    log("")
    log("=" * 78)
    log("receipt.csv 생성이 정상적으로 완료되었습니다.")
    log(f"결과 파일: {FINAL_OUTPUT_PATH}")
    log("=" * 78)


# =============================================================================
# 16. entry point
# =============================================================================
if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("")
        log("=" * 78)
        log("[FAIL] 예기치 못한 오류가 발생하여 실행을 중단합니다.")
        log(traceback.format_exc())
        log("=" * 78)
        raise
