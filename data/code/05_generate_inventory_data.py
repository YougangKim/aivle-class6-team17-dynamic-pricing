# -*- coding: utf-8 -*-
"""
07_generate_inventory_data.py

[프로젝트]
KT AIVLE School 빅프로젝트
「AI 신선식품 수요예측 및 다이나믹 프라이싱 플랫폼」

[목적]
inventory.csv (재고 데이터) 생성 스크립트.
inventory = "점포에 존재하는 개별 재고(lot)의 날짜별 이력" 데이터이며
transactions.csv / receipts.csv / disposal.csv 보다 먼저 만들어지는 기초 데이터이다.

[마스터 데이터 - 4개 모두 필수]
- product.csv        : 상품 마스터 (상품명/카테고리/가격/유통기한/baseline_waste_rate 등)
- store.csv           : 점포 마스터 (store_id, open_hour, close_hour 등)
- calendar.csv         : 날짜 마스터 (date 컬럼, 1년치 날짜 그대로 존재해야 함)
- store_calendar.csv   : 점포별 영업/의무휴업 캘린더 (store_id, date, is_mandatory_closed 등)

상품명, 카테고리, 가격, 유통기한, 점포 ID 등은 절대 코드에 하드코딩하지 않고
반드시 위 4개 CSV를 읽어서 사용한다. 임시 store_id(S001~S010 등)는 사용하지 않는다.

[가정값 표시 원칙]
데이터.pdf / product.csv / store.csv 어디에도 수치가 명시되어 있지 않아
합성 데이터 생성을 위해 임의로 정한 값은 반드시 코드 주석에 [가정] 이라고
표시한다. 근거가 있는 값에는 [가정]을 붙이지 않는다.

===========================================================================
[v6 변경 이력 - 이전 버전(v5) inventory.csv 검토에서 발견된 문제 수정]
===========================================================================
v5까지는 "판매+감모"로 인한 재고 감소가 current_stock_qty 컬럼 하나에만
반영되고, 그 원인(판매인지 감모/폐기인지)을 CSV만 보고는 구분할 수 없었다.
이로 인해 다음과 같은 구조적 문제가 있었다.

  [문제1] EXPIRED 상태인데 current_stock_qty > 0으로 남아, 그 수량이 실물
          재고인지 폐기수량인지 알 수 없었다.
  [문제2] current_stock_qty=0(SOLD_OUT)인데 disposal_candidate=1이 되는
          모순이 있었다 (재고가 없는데 "폐기 후보"로 표시).
  [문제3] freshness_score 계산식이 (days_to_expiry+1)/shelf_life_days를
          사용해, shelf_life_days=1인 상품은 유통기한 당일(days_to_expiry=0)
          에도 freshness_score=1.0(제조일과 동일)이 되는 오류가 있었다.
  [문제4] days_to_expiry=0인데 discount_rate=0, inventory_status=NORMAL로
          남는 행이 존재했다 (유통기한이 오늘 끝나는데 "정상" 취급).
  [문제5] 판매량과 감모·폐기량이 컬럼으로 분리되어 있지 않아, 이후
          receipts.csv를 "전날 재고-오늘 재고"로 역산하면 감모·폐기량까지
          판매량으로 잘못 계산될 위험이 있었다.
  [문제6] 폐기 KPI(폐기 최소화가 이 프로젝트의 핵심 목표)를 산출할 컬럼이
          없었다.

v6는 위 문제를 다음과 같이 해결한다.

  1) daily_sold_qty(그 날 실제 판매수량), daily_waste_qty(그 날 감모/파손/
     품질저하/유통기한경과로 제거된 수량), inbound_qty(그 LOT가 최초로
     생성된 날의 입고수량, 이후에는 0), waste_reason(폐기 원인) 4개 컬럼을
     신규로 추가한다. 이 컬럼들이 앞으로 receipts.csv/transactions.csv/
     disposal.csv가 사용해야 할 "유일하게 신뢰 가능한" 판매·폐기 수량이다.
     ("전날 current_stock_qty - 오늘 current_stock_qty"로 판매량을 역산하는
     방식은 이제 명백히 틀린 방법이므로 절대 사용하지 않는다. 아래
     [receipts.csv 연동 시 필독] 참고.)
  2) 유통기한이 지난(days_to_expiry<0) LOT은 그날 즉시 전량 폐기 처리한다
     (당일 폐기 방식으로 통일). daily_waste_qty에 폐기수량을 기록하고
     current_stock_qty/available_qty/reserved_qty를 모두 0으로 만든 뒤,
     inventory_status=EXPIRED, disposal_candidate=0(이미 폐기 완료되었으므로
     "후보"가 아니다), waste_reason=EXPIRED로 기록한다. 단, 의무휴업일에는
     이 폐기 처리 자체를 그날 수행하지 않고 다음 영업일로 미룬다(4번 참고).
  3) 상태(inventory_status) 판정 우선순위를 한 곳(step 5)에서만 계산한다.
     1. EXPIRED (당일 유통기한 경과로 폐기 처리된 경우, step 2에서 확정)
     2. SOLD_OUT (판매/감모로 재고가 0이 된 경우)
     3. DISCOUNT (재고>0, discount_rate>0)
     4. NORMAL   (재고>0, discount_rate=0, 이 경우 반드시 days_to_expiry>0)
     disposal_candidate는 "재고가 남아 있고(current_stock_qty>0) freshness_score가
     임계값 미만이거나 유통기한이 당일 이하(days_to_expiry<=0)"일 때만 1이며,
     재고가 0인 모든 행(SOLD_OUT, EXPIRED)은 항상 0이다.
  4) freshness_score 공식을 (days_to_expiry+1)/(shelf_life_days+1)로 수정했다.
     shelf_life_days가 몇 일이든 분모가 항상 2 이상이라 0으로 나눌 위험이
     없고, 제조일(=1.0)과 유통기한 당일(<1.0, 반드시 1.0 미만) 사이에
     최소 1단계 이상의 감소 구간이 생겨 shelf_life_days=1인 상품도 정상적으로
     신선도가 단조 감소한다.
  5) 유통기한 당일(days_to_expiry=0)에 재고가 남아 있으면, 그 상품이
     markdown_eligible=False(할인 정책 대상이 아닌 상품)이더라도 최소
     EXPIRY_DAY_MIN_DISCOUNT_PCT(마감할인)를 강제 적용해 반드시 DISCOUNT
     상태가 되도록 한다(NORMAL로 남기지 않는다). 프로젝트 할인 상한(40%)은
     그대로 지킨다.
  6) 의무휴업일(store_calendar.csv 기준 is_mandatory_closed=1)에는 모든
     LOT에 대해 daily_sold_qty=0, daily_waste_qty=0을 강제하고, 그날
     신규 입고(inbound_qty)도 발생시키지 않는다. 유통기한이 이미 지난 LOT의
     폐기 처리도 그날은 수행하지 않고 다음 영업일로 미룬다(재고가 절대
     줄어들지 않는다).

===========================================================================
[current_stock_qty 스냅샷 정의]
===========================================================================
current_stock_qty는 "그날 영업이 모두 끝난 시점(마감/종료 시점)의 실물
재고수량"이며, 폐기(EXPIRED)된 수량은 여기 포함되지 않는다(폐기되는 순간
0이 된다). 다음 항등식이 모든 행에서 성립한다(코드 검증 포함, "LOT 흐름식").

    current_stock_qty(오늘)
    = current_stock_qty(전날, 같은 LOT. 최초 생성일이면 0)
    + inbound_qty(오늘. 최초 생성일에만 값이 있고 그 외에는 0)
    - daily_sold_qty(오늘)
    - daily_waste_qty(오늘)

===========================================================================
[receipts.csv 연동 시 필독 - 절대 사용하면 안 되는 방식]
===========================================================================
receipts.csv / transactions.csv를 만들 때 판매수량의 기준은 반드시
"inventory.daily_sold_qty" 컬럼이다.

    (금지) 판매수량 = 전날 current_stock_qty - 오늘 current_stock_qty

위 방식은 daily_waste_qty(감모/파손/품질저하/유통기한경과 폐기)까지 판매량에
섞어 넣는 잘못된 계산이므로 절대 사용하지 않는다. daily_waste_qty는 반드시
disposal.csv 등 폐기 관련 집계에만 사용한다.

===========================================================================
[weight_kg 컬럼의 의미]
===========================================================================
weight_kg는 "판매 단위(포장/개) 1개당 중량"이며, "LOT 전체 중량"이나
"현재 잔여재고의 총중량"이 아니다. fixed_price 상품은 product.csv의
standard_weight_kg를 그대로 쓰고, weight_based 상품은 LOT 생성 시 1회
표준중량의 60~140% 범위에서 뽑은 대표값을 그 LOT 전체 기간 동안 고정해서
쓴다. 무게상품 결제금액은 daily_sold_qty(판매 개수) x weight_kg(개당 중량)
x kg당 단가로 계산해야 하며, 이 스크립트 자체는 결제금액을 계산하지 않는다
(receipts.csv의 책임).

===========================================================================
[출력 스키마]
===========================================================================
inventory_id, store_id, product_id, lot_id, current_date, manufacture_date,
expiry_date, days_to_expiry, inbound_qty, daily_sold_qty, daily_waste_qty,
current_stock_qty, reserved_qty, available_qty, freshness_score, unit_cost,
unit_price, discount_rate, discount_price, disposal_candidate,
inventory_status, waste_reason, weight_kg

(weight_kg는 이전 버전에서 이미 필수로 요구되었던 기존 컬럼이라 삭제하지
않고 마지막 컬럼으로 유지했다.)
"""

import os
import re
import sys
import numpy as np
import pandas as pd
from datetime import timedelta

# =========================================================
# 0. 기본 설정 (CONFIG)
# =========================================================

# ---- 저장 경로 (기존과 동일, 임의 변경 금지) ----
# [주의] 경로에 공백/한글이 포함되어 있으므로 반드시 os.path.join()으로만 다룬다.
SAVE_DIR = "/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터/"

# ---- 입력 파일 경로 (마스터 데이터, 4개 모두 필수) ----
PRODUCT_CSV_PATH = os.path.join(SAVE_DIR, "product.csv")
STORE_CSV_PATH = os.path.join(SAVE_DIR, "store.csv")
CALENDAR_CSV_PATH = os.path.join(SAVE_DIR, "calendar.csv")
STORE_CALENDAR_CSV_PATH = os.path.join(SAVE_DIR, "store_calendar.csv")

# ---- 출력 파일 ----
OUTPUT_FILENAME = "inventory.csv"

# ---- Random Seed 고정 (프로젝트 원칙, 재현성 보장) ----
RANDOM_SEED = 42

# ---- inventory 생성 기간 (1년 일별, 로트 이력이 이어지는 구조) ----
START_DATE = pd.Timestamp("2025-01-01")
END_DATE = pd.Timestamp("2025-12-31")

# ---- 현재 프로젝트 공식 카테고리 (사용자 확정, 수산 제외) ----
VALID_CATEGORIES = {"produce", "dairy", "meat", "cheese", "deli"}

# ---- product.csv에서 실제로 관측되는 판매 유형 ----
# [가정] 현재 product.csv에는 fixed_price / weight_based 두 종류만 존재하며,
# weight_kg 생성 로직이 이 두 값만 처리하도록 되어 있으므로 그 외 값은 오류로 처리한다.
ALLOWED_SALES_TYPES = {"fixed_price", "weight_based"}

# ---- product.csv에서 숫자로 강제 변환해야 하는 컬럼 ----
NUMERIC_PRODUCT_COLS = [
    "standard_weight_kg",
    "shelf_life_days",
    "base_cost",
    "base_price",
    "max_discount_rate",
    "baseline_waste_rate",
]

# ---- 카테고리별 "초기재고" 로트 개수 범위 ----
# [가정] 2025-01-01 시작 시점의 초기재고(전년도 이월분)를 몇 개의 로트로
# 나눠 담을지에 대한 가정값이다. 이후 신규 입고는 하루 1개 로트로만 생성된다.
LOT_COUNT_RANGE = {
    "produce": (1, 4),
    "dairy":   (1, 3),
    "meat":    (1, 3),
    "cheese":  (1, 3),
    "deli":    (1, 2),
}

# ---- 카테고리별 로트당 재고 수량 범위 (초기재고 및 신규 입고 공통 사용) ----
# [가정] 재고 수량 현실화 지시에 따른 값 (실측 데이터 아님)
STOCK_QTY_RANGE = {
    "produce": (5, 25),
    "dairy":   (5, 20),
    "meat":    (3, 12),
    "cheese":  (3, 15),
    "deli":    (2, 10),
}

# ---- freshness_decay_type 별 감쇠 지수 ----
# [가정] decay_type이 빠를수록(fast) 남은 유통기한 비율 대비 신선도가
# 더 급격히 낮아지도록 지수를 다르게 적용한다.
DECAY_EXPONENT = {
    "fast": 1.5,
    "medium": 1.0,
    "slow": 0.7,
}

# ---- 폐기 후보 판정 임계값 ----
# [가정] freshness_score가 이 값 미만이면 폐기 후보로 본다 (만료 여부와는 별개).
FRESHNESS_DISPOSAL_THRESHOLD = 0.15

# ---- 로트 하나의 최대 동시 활성 개수 (점포 x 상품 기준) ----
# [가정] 신규 입고가 과도하게 누적되어 행 수가 무한정 늘어나는 것을 막기 위한
# 안전장치. 재고가 이미 충분히 쌓여 있으면 이 값을 넘는 신규 입고는 만들지 않는다.
MAX_ACTIVE_LOTS_PER_COMBO = 8

# ---- 신규 입고(재입고) 확률 계산용 상수 ----
# [가정] 유통기한이 짧을수록(shelf_life_days가 작을수록) 자주 입고되도록
# base_prob = min(0.9, RESTOCK_BASE_K / shelf_life_days) 로 계산한다.
RESTOCK_BASE_K = 3.0
# [가정] 재고가 카테고리 하한(stock_low) 미만이면 입고 확률을 가중한다.
RESTOCK_LOW_STOCK_MULTIPLIER = 2.0
# [가정] 재고가 카테고리 상한(stock_high) 이상이면 입고 확률을 크게 낮춘다.
RESTOCK_AMPLE_STOCK_MULTIPLIER = 0.2
# [가정] 신규 입고 로트는 배송/입고 과정을 반영해 제조일로부터 0~2일 이내로 본다.
RESTOCK_MAX_AGE_DAYS = 2
# [설계결정 v6] 의무휴업일에는 입고(inbound_qty)도 발생시키지 않는다
# (요청사항 4: "inbound_qty는 기존 정책에 따라 0 권장"). 매장이 문을 닫으면
# 배송/입고도 없다고 가정한다. 이로 인해 의무휴업일 하루 동안 특정
# 점포x상품 조합의 활성 LOT이 0개가 되어 그날 행이 없을 수 있는데
# (직전 영업일에 이미 소진된 경우), 이는 "재고가 실제로 없다"는 사실을
# 그대로 반영한 것이므로 오류가 아니다.

# ---- 일일 판매 수량(합성 수요) 계산용 상수 ----
# [가정] 그날 판매 가능한 총 재고 중 15~45%를 하루 수요로 가정하고,
# 할인율이 높을수록 수요가 늘어나는 효과를 더한다.
DAILY_DEMAND_FRACTION_RANGE = (0.15, 0.45)
DAILY_DEMAND_DISCOUNT_BOOST = 0.5

# ---- 일일 폐기(감모) 계산용 상수 ----
# [가정] product.csv의 baseline_waste_rate(예: 과채 0.056)를 "하루 단위 감모
# 기대값"의 기준치로 사용하고, 0.5~1.5배의 난수를 곱해 매일 변동을 준다.
# baseline_waste_rate 자체는 반드시 product.csv에서 읽은 값을 사용하며
# 카테고리별 값을 코드에 다시 하드코딩하지 않는다. 이 값은 daily_waste_qty에
# waste_reason=SHRINKAGE로 기록된다 (유통기한 경과로 인한 EXPIRED 폐기와는
# 별개의, "정상적인 자연 감모"이다).
DAILY_WASTE_RATE_MULTIPLIER_RANGE = (0.5, 1.5)

# ---- 유통기한 당일(days_to_expiry=0) 강제 마감할인 최소값 ----
# [요구사항 반영] 유통기한 당일에 재고가 남아 있으면 markdown_eligible 여부와
# 무관하게 최소한 이 값 이상의 할인을 강제 적용해 NORMAL 상태로 남지 않도록
# 한다 ([가정] 구체적인 마감할인율 수치는 데이터.pdf에 명시되어 있지 않다).
# 이 값은 반드시 상품별 max_discount_pct(<=40) 이내로 clip된다.
EXPIRY_DAY_MIN_DISCOUNT_PCT = 10

# ---- inventory_status enum ----
STATUS_NORMAL = "NORMAL"
STATUS_DISCOUNT = "DISCOUNT"
STATUS_EXPIRED = "EXPIRED"
STATUS_SOLD_OUT = "SOLD_OUT"
VALID_STATUSES = {STATUS_NORMAL, STATUS_DISCOUNT, STATUS_EXPIRED, STATUS_SOLD_OUT}

# ---- waste_reason enum ----
# [가정] 이 시뮬레이션이 실제로 구분해서 생성하는 값은 NONE / SHRINKAGE(일반
# 자연감모) / EXPIRED(유통기한 경과 폐기) 3가지뿐이다. DAMAGE(파손)와
# QUALITY(품질저하)는 이를 구분할 근거 데이터가 없어([미확정]) 이번
# 시뮬레이션에서는 직접 생성하지 않지만, 스키마/후속 파일 호환성을 위해
# 허용값 집합에는 포함해 둔다("모르는 값을 임의로 생성하지 않는다"는 원칙에
# 따라 실제로 생성하지는 않는다).
WASTE_REASON_NONE = "NONE"
WASTE_REASON_SHRINKAGE = "SHRINKAGE"
WASTE_REASON_DAMAGE = "DAMAGE"
WASTE_REASON_QUALITY = "QUALITY"
WASTE_REASON_EXPIRED = "EXPIRED"
VALID_WASTE_REASONS = {
    WASTE_REASON_NONE, WASTE_REASON_SHRINKAGE, WASTE_REASON_DAMAGE,
    WASTE_REASON_QUALITY, WASTE_REASON_EXPIRED,
}

# ---- ID 형식 정규식 ----
INVENTORY_ID_PATTERN = re.compile(r"^INV\d{7}$")
LOT_ID_PATTERN = re.compile(r"^LOT\d{7}$")

# ---- markdown_eligible 값 정규화용 허용 집합 ----
MARKDOWN_TRUE_VALUES = {"1", "1.0", "true", "y", "yes"}
MARKDOWN_FALSE_VALUES = {"0", "0.0", "false", "n", "no"}

# ---- 출력 컬럼 순서 (v6 확정 스키마) ----
COLUMN_ORDER = [
    "inventory_id",
    "store_id",
    "product_id",
    "lot_id",
    "current_date",
    "manufacture_date",
    "expiry_date",
    "days_to_expiry",
    "inbound_qty",
    "daily_sold_qty",
    "daily_waste_qty",
    "current_stock_qty",
    "reserved_qty",
    "available_qty",
    "freshness_score",
    "unit_cost",
    "unit_price",
    "discount_rate",
    "discount_price",
    "disposal_candidate",
    "inventory_status",
    "waste_reason",
    "weight_kg",
]

# ---- lot 그룹 키 ----
# lot_id는 전역 카운터로 순차 발급되어 전역적으로 유일하지만, "다른 매장/
# 상품의 lot이 섞이지 않는다"는 것을 코드 스스로 다시 보장하기 위해 lot
# 단위 연산(정렬, 이전/다음 값 비교 등)은 항상 이 조합키로 그룹화한다.
LOT_KEYS = ["store_id", "product_id", "lot_id"]

# ---- FEFO 판매 검증용 내부 로그 (CSV로 저장되지 않는 내부 시뮬레이션 기록) ----
# generate_inventory_data() 호출 시마다 초기화되고, validate_inventory()에서
# "FEFO(유통기한이 빠른 로트부터 판매) 순서가 실제로 지켜졌는지"를 독립적으로
# 재검증하는 데에만 사용한다. 그날 판매되지 않은(sold_qty=0) lot도 포함해
# "그날 store+product 조합에 존재했던 모든 lot"을 빠짐없이 기록한다.
_FIFO_SALE_LOG = []

# ---- 생성 과정 누적 통계 (CSV로 저장되지 않는 요약용 내부 기록) ----
_GENERATION_STATS = {}

# ---- 최종 검증 통계 (CSV로 저장되지 않는 요약용 내부 기록) ----
_VALIDATION_STATS = {}


def _reset_module_state():
    global _FIFO_SALE_LOG, _GENERATION_STATS, _VALIDATION_STATS
    _FIFO_SALE_LOG = []
    _GENERATION_STATS = {
        "initial_seed_qty": 0,
        "restock_qty": 0,
        "total_sold_qty": 0,
        "total_waste_qty_shrinkage": 0,
        "total_waste_qty_expired": 0,
        "mandatory_closed_skip_events": 0,
        "mandatory_closed_expiry_deferred_events": 0,
    }
    _VALIDATION_STATS = {}


_reset_module_state()


# =========================================================
# 1. 마스터 데이터 로드
# =========================================================
def _coerce_numeric_column(df: pd.DataFrame, col: str, file_label: str = "product.csv") -> pd.Series:
    """
    문자열 컬럼에 포함된 쉼표(예: "1,234")를 제거한 뒤 pd.to_numeric(errors="raise")로
    강제 변환한다. 이미 숫자형(int64/float64)인 컬럼은 쉼표 제거 없이 그대로 변환을 시도한다.
    숫자로 변환할 수 없는 값이 하나라도 있으면 즉시 ValueError를 발생시킨다.
    """
    series = df[col]
    if series.dtype == object:
        series = series.astype(str).str.strip().str.replace(",", "", regex=False)
    try:
        return pd.to_numeric(series, errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"{file_label}의 '{col}' 컬럼에 숫자로 변환할 수 없는 값이 있습니다: {e}"
        )


def resolve_max_discount_pct_column(product_df: pd.DataFrame) -> pd.Series:
    """
    product.csv의 max_discount_rate(0~1 비율)를 정수 % Series로 변환한다.
    0~1 범위를 벗어나거나 40%를 초과하면 즉시 오류로 처리한다.
    """
    values = product_df["max_discount_rate"]

    out_of_range_mask = (values < 0) | (values > 1)
    if out_of_range_mask.any():
        bad = product_df.loc[out_of_range_mask, ["product_id", "max_discount_rate"]]
        raise ValueError(
            "max_discount_rate는 0~1 사이의 비율(예: 0.4 = 40%)로 기록되어 있어야 합니다. "
            "0~1 범위를 벗어난 값이 있습니다 (형식이 바뀌었는지, 데이터 오류인지 먼저 "
            f"확인해주세요):\n{bad.to_string(index=False)}"
        )

    pct = values * 100
    pct_int = pct.round().astype(int)

    if (pct_int > 40).any():
        bad = product_df.loc[pct_int > 40, ["product_id", "max_discount_rate"]]
        raise ValueError(
            f"max_discount_rate가 프로젝트 할인 상한 40%를 초과합니다:\n{bad.to_string(index=False)}"
        )
    if (pct_int < 0).any():
        bad = product_df.loc[pct_int < 0, "product_id"].tolist()
        raise ValueError(f"max_discount_rate가 음수로 계산되었습니다: {bad}")

    return pct_int


def load_product_data(path: str) -> pd.DataFrame:
    """
    product.csv(최종 확정본)를 읽고, inventory 생성/검증에 필요한
    필수 컬럼 존재 여부와 값의 유효성을 확인한다.
    문제가 있으면 경고만 출력하지 않고 즉시 오류를 발생시켜 실행을 중단한다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"product.csv를 찾을 수 없습니다: {path}\n"
            f"PRODUCT_CSV_PATH 를 실제 product.csv 위치로 수정해주세요."
        )

    product_df = pd.read_csv(path, encoding="utf-8-sig")

    if len(product_df) == 0:
        raise ValueError(f"product.csv에 데이터 행이 하나도 없습니다: {path}")

    required_cols = [
        "product_id", "product_name", "category", "subcategory",
        "sales_type", "unit", "standard_weight_kg", "shelf_life_days",
        "base_cost", "base_price", "max_discount_rate", "markdown_eligible",
        "freshness_decay_type", "baseline_waste_rate",
    ]
    missing = [c for c in required_cols if c not in product_df.columns]
    if missing:
        raise ValueError(
            f"product.csv에 다음 필수 컬럼이 없습니다: {missing}\n"
            f"실제 컬럼 목록: {list(product_df.columns)}"
        )

    for col in NUMERIC_PRODUCT_COLS:
        product_df[col] = _coerce_numeric_column(product_df, col, file_label="product.csv")
        non_finite_mask = product_df[col].notna() & ~np.isfinite(product_df[col])
        if non_finite_mask.any():
            bad = product_df.loc[non_finite_mask, ["product_id", col]]
            raise ValueError(
                f"product.csv의 '{col}' 컬럼에 inf/-inf 등 유한하지 않은 값이 있습니다:\n"
                f"{bad.to_string(index=False)}"
            )

    null_cols = [c for c in required_cols if product_df[c].isnull().any()]
    if null_cols:
        raise ValueError(f"product.csv 필수 컬럼에 결측치가 있습니다: {null_cols}")

    product_df["product_id"] = product_df["product_id"].astype(str).str.strip()
    empty_pid_mask = product_df["product_id"] == ""
    if empty_pid_mask.any():
        bad_rows = [i + 2 for i in product_df.index[empty_pid_mask].tolist()]
        raise ValueError(f"product.csv에 공백만 있거나 빈 product_id가 있습니다 (CSV 행 번호: {bad_rows})")

    dup_ids = product_df.loc[product_df["product_id"].duplicated(), "product_id"].tolist()
    if dup_ids:
        raise ValueError(f"product.csv product_id 중복 발견: {dup_ids}")

    unknown_categories = set(product_df["category"].unique()) - VALID_CATEGORIES
    if unknown_categories:
        raise ValueError(
            f"product.csv에 프로젝트 확정 카테고리({sorted(VALID_CATEGORIES)})에 "
            f"없는 카테고리가 있습니다: {unknown_categories}. "
            f"제외/추가/범위 확장 여부를 사용자에게 먼저 확인해야 합니다."
        )

    unknown_sales_types = set(product_df["sales_type"].unique()) - ALLOWED_SALES_TYPES
    if unknown_sales_types:
        raise ValueError(
            f"product.csv에 처리할 수 없는 sales_type이 있습니다: {unknown_sales_types} "
            f"(허용값: {ALLOWED_SALES_TYPES}). 오타이든 새로운 정책이든 임의로 fixed_price로 "
            f"보정하지 않고 오류로 처리합니다."
        )

    unknown_decay = set(product_df["freshness_decay_type"].unique()) - set(DECAY_EXPONENT.keys())
    if unknown_decay:
        raise ValueError(
            f"product.csv에 처리할 수 없는 freshness_decay_type이 있습니다: {unknown_decay} "
            f"(허용값: {list(DECAY_EXPONENT.keys())})"
        )

    is_integer_valued = product_df["shelf_life_days"] == product_df["shelf_life_days"].astype(int)
    if not is_integer_valued.all():
        bad = product_df.loc[~is_integer_valued, ["product_id", "shelf_life_days"]]
        raise ValueError(
            f"shelf_life_days가 정수가 아닌 상품이 있습니다 (예: 3.7). "
            f"임의로 자르지 않고 오류로 처리합니다:\n{bad.to_string(index=False)}"
        )
    product_df["shelf_life_days"] = product_df["shelf_life_days"].astype(int)

    if (product_df["shelf_life_days"] <= 0).any():
        bad = product_df.loc[product_df["shelf_life_days"] <= 0, "product_id"].tolist()
        raise ValueError(f"shelf_life_days가 0 이하인 상품이 있습니다: {bad}")

    for money_col in ("base_cost", "base_price"):
        is_won_integer = product_df[money_col] == product_df[money_col].astype(int)
        if not is_won_integer.all():
            bad = product_df.loc[~is_won_integer, ["product_id", money_col]]
            raise ValueError(
                f"{money_col}는 원 단위 정수여야 합니다 (소수점 값 불가, 예: 3999.8). "
                f"정수가 아닌 값이 있습니다:\n{bad.to_string(index=False)}"
            )
        product_df[money_col] = product_df[money_col].astype(int)

    if (product_df["base_cost"] < 0).any():
        bad = product_df.loc[product_df["base_cost"] < 0, "product_id"].tolist()
        raise ValueError(f"base_cost가 음수인 상품이 있습니다: {bad}")

    if (product_df["base_price"] <= 0).any():
        bad = product_df.loc[product_df["base_price"] <= 0, "product_id"].tolist()
        raise ValueError(f"base_price가 0 이하인 상품이 있습니다: {bad}")

    if (product_df["base_price"] < 10).any():
        bad = product_df.loc[product_df["base_price"] < 10, "product_id"].tolist()
        raise ValueError(
            f"base_price가 10원 미만인 비정상 데이터가 있습니다: {bad}. "
            f"discount_price를 10원 단위로 반올림할 수 없습니다."
        )

    invalid_margin_mask = product_df["base_cost"] >= product_df["base_price"]
    if invalid_margin_mask.any():
        bad = product_df.loc[invalid_margin_mask, ["product_id", "base_cost", "base_price"]]
        raise ValueError(
            f"base_cost가 base_price보다 크거나 같은 상품이 있습니다. "
            f"현재 프로젝트 기준 원가 >= 판매가는 비정상 데이터입니다:\n{bad.to_string(index=False)}"
        )

    bad_weight = product_df.loc[
        product_df["standard_weight_kg"].isnull() | (product_df["standard_weight_kg"] <= 0),
        "product_id"
    ].tolist()
    if bad_weight:
        raise ValueError(
            f"standard_weight_kg가 결측이거나 0 이하인 상품이 있습니다: {bad_weight}"
        )

    if not product_df["baseline_waste_rate"].between(0, 1).all():
        bad = product_df.loc[
            ~product_df["baseline_waste_rate"].between(0, 1), ["product_id", "baseline_waste_rate"]
        ]
        raise ValueError(
            f"baseline_waste_rate는 0~1 사이의 비율이어야 합니다. "
            f"범위를 벗어난 값이 있습니다:\n{bad.to_string(index=False)}"
        )

    product_df["max_discount_pct"] = resolve_max_discount_pct_column(product_df)

    # [v6 신규] 유통기한 당일 강제 마감할인(EXPIRY_DAY_MIN_DISCOUNT_PCT) 요구사항을
    # 만족하려면 모든 상품의 max_discount_pct가 0보다 커야 한다. 0이면 마감할인
    # 자체를 적용할 수 없어 "유통기한 당일 NORMAL 금지" 규칙과 정면으로 충돌한다.
    if (product_df["max_discount_pct"] <= 0).any():
        bad = product_df.loc[product_df["max_discount_pct"] <= 0, "product_id"].tolist()
        raise ValueError(
            f"max_discount_rate(max_discount_pct)가 0인 상품이 있습니다: {bad}\n"
            f"이 프로젝트 규칙상 유통기한 당일(days_to_expiry=0)에는 재고가 남아 있으면 "
            f"반드시 최소 마감할인을 적용해야 하므로, 할인율 상한이 0인 상품은 이 규칙과 "
            f"충돌합니다. product.csv 값을 다시 확인하거나 처리 방침을 먼저 확인해주세요."
        )

    print(f"[product.csv 로드 완료] shape={product_df.shape}")
    print(f"카테고리 목록: {sorted(product_df['category'].unique().tolist())}")
    print(f"sales_type 목록: {sorted(product_df['sales_type'].unique().tolist())}")

    return product_df


def load_store_data(path: str) -> pd.DataFrame:
    """
    store.csv(확정본)를 읽고 store_id / open_hour / close_hour 등
    inventory 생성에 필요한 컬럼과 값의 유효성을 확인한다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"store.csv를 찾을 수 없습니다: {path}\n"
            f"STORE_CSV_PATH 를 실제 store.csv 위치로 수정해주세요."
        )

    store_df = pd.read_csv(path, encoding="utf-8-sig")

    if len(store_df) == 0:
        raise ValueError(f"store.csv에 데이터 행이 하나도 없습니다: {path}")

    required_cols = ["store_id", "open_hour", "close_hour"]
    missing = [c for c in required_cols if c not in store_df.columns]
    if missing:
        raise ValueError(
            f"store.csv에 다음 필수 컬럼이 없습니다: {missing}\n"
            f"실제 컬럼 목록: {list(store_df.columns)}"
        )

    if store_df["store_id"].isnull().any():
        raise ValueError("store.csv의 store_id에 결측치가 있습니다.")

    store_df["store_id"] = store_df["store_id"].astype(str).str.strip()
    empty_sid_mask = store_df["store_id"] == ""
    if empty_sid_mask.any():
        bad_rows = [i + 2 for i in store_df.index[empty_sid_mask].tolist()]
        raise ValueError(f"store.csv에 공백만 있거나 빈 store_id가 있습니다 (CSV 행 번호: {bad_rows})")

    dup_stores = store_df.loc[store_df["store_id"].duplicated(), "store_id"].tolist()
    if dup_stores:
        raise ValueError(f"store.csv store_id 중복 발견: {dup_stores}")

    store_df["open_hour"] = _coerce_numeric_column(store_df, "open_hour", file_label="store.csv")
    store_df["close_hour"] = _coerce_numeric_column(store_df, "close_hour", file_label="store.csv")

    if store_df["open_hour"].isnull().any() or store_df["close_hour"].isnull().any():
        raise ValueError("store.csv의 open_hour/close_hour에 결측치가 있습니다.")

    invalid_hours_mask = store_df["open_hour"] >= store_df["close_hour"]
    if invalid_hours_mask.any():
        bad = store_df.loc[invalid_hours_mask, ["store_id", "open_hour", "close_hour"]]
        raise ValueError(
            f"open_hour가 close_hour보다 크거나 같은 매장이 있습니다(영업시간 오류):\n"
            f"{bad.to_string(index=False)}"
        )

    print(f"[store.csv 로드 완료] shape={store_df.shape}")
    print(f"store_id 목록: {sorted(store_df['store_id'].unique().tolist())}")

    return store_df


def load_calendar_data(path: str) -> pd.DataFrame:
    """
    calendar.csv(날짜 마스터)를 읽고 START_DATE~END_DATE 1년치가 하루도 빠짐없이,
    중복 없이 존재하는지 확인한다. validate_inventory()의 FK 검증
    ("current_date가 calendar.csv에 모두 존재")에도 사용한다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"calendar.csv를 찾을 수 없습니다: {path}\n"
            f"CALENDAR_CSV_PATH 를 실제 calendar.csv 위치로 수정해주세요."
        )

    calendar_df = pd.read_csv(path, encoding="utf-8-sig")

    if len(calendar_df) == 0:
        raise ValueError(f"calendar.csv에 데이터 행이 하나도 없습니다: {path}")

    if "date" not in calendar_df.columns:
        raise ValueError(
            f"calendar.csv에 date 컬럼이 없습니다. 실제 컬럼 목록: {list(calendar_df.columns)}"
        )

    if calendar_df["date"].isnull().any():
        raise ValueError("calendar.csv의 date 컬럼에 결측치가 있습니다.")

    try:
        calendar_df["date"] = pd.to_datetime(calendar_df["date"], errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(f"calendar.csv의 date 컬럼을 날짜로 해석할 수 없습니다: {e}")

    dup_mask = calendar_df["date"].duplicated()
    if dup_mask.any():
        bad = sorted(calendar_df.loc[dup_mask, "date"].dt.strftime("%Y-%m-%d").unique().tolist())
        raise ValueError(f"calendar.csv date 중복 발견: {bad}")

    expected_dates = pd.date_range(START_DATE, END_DATE, freq="D")
    in_range_dates = calendar_df.loc[
        (calendar_df["date"] >= START_DATE) & (calendar_df["date"] <= END_DATE), "date"
    ]
    actual_in_range = pd.DatetimeIndex(sorted(in_range_dates.unique()))
    missing_dates = expected_dates.difference(actual_in_range)
    if len(missing_dates) > 0:
        raise ValueError(
            f"calendar.csv에 {START_DATE.date()}~{END_DATE.date()} 구간 날짜가 누락되어 "
            f"있습니다 (최대 10개 예시): "
            f"{[d.strftime('%Y-%m-%d') for d in missing_dates[:10]]}"
        )
    if len(actual_in_range) != len(expected_dates):
        raise ValueError(
            f"calendar.csv의 {START_DATE.date()}~{END_DATE.date()} 구간 날짜 수가 "
            f"{len(expected_dates)}개가 아닙니다 (실제 {len(actual_in_range)}개)."
        )

    print(
        f"[calendar.csv 로드 완료] shape={calendar_df.shape}, "
        f"날짜범위 {calendar_df['date'].min().date()}~{calendar_df['date'].max().date()}"
    )
    return calendar_df


def load_store_calendar_data(path: str, store_df: pd.DataFrame, calendar_df: pd.DataFrame) -> pd.DataFrame:
    """
    store_calendar.csv(점포별 영업/의무휴업 캘린더)를 읽는다.
    inventory 생성 시 "의무휴업일(is_mandatory_closed=1)에는 판매/감모/입고를
    모두 0으로 강제"하는 규칙의 유일한 근거 데이터이므로, store_id+date 키
    정합성과 is_mandatory_closed 값의 유효성을 특히 엄격하게 검증한다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"store_calendar.csv를 찾을 수 없습니다: {path}\n"
            f"STORE_CALENDAR_CSV_PATH 를 실제 store_calendar.csv 위치로 수정해주세요."
        )

    sc_df = pd.read_csv(path, encoding="utf-8-sig")

    if len(sc_df) == 0:
        raise ValueError(f"store_calendar.csv에 데이터 행이 하나도 없습니다: {path}")

    required_cols = ["store_id", "date", "is_mandatory_closed"]
    missing = [c for c in required_cols if c not in sc_df.columns]
    if missing:
        raise ValueError(
            f"store_calendar.csv에 다음 필수 컬럼이 없습니다: {missing}\n"
            f"실제 컬럼 목록: {list(sc_df.columns)}"
        )

    if sc_df[required_cols].isnull().any().any():
        null_cols = [c for c in required_cols if sc_df[c].isnull().any()]
        raise ValueError(f"store_calendar.csv의 다음 필수 컬럼에 결측치가 있습니다: {null_cols}")

    sc_df["store_id"] = sc_df["store_id"].astype(str).str.strip()
    try:
        sc_df["date"] = pd.to_datetime(sc_df["date"], errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(f"store_calendar.csv의 date 컬럼을 날짜로 해석할 수 없습니다: {e}")

    dup_mask = sc_df.duplicated(subset=["store_id", "date"])
    if dup_mask.any():
        bad = sc_df.loc[dup_mask, ["store_id", "date"]].copy()
        bad["date"] = bad["date"].dt.strftime("%Y-%m-%d")
        raise ValueError(
            f"store_calendar.csv에 (store_id, date) 조합 중복이 있습니다:\n{bad.to_string(index=False)}"
        )

    store_ids_master = set(store_df["store_id"])
    unknown_store_mask = ~sc_df["store_id"].isin(store_ids_master)
    if unknown_store_mask.any():
        bad = sorted(sc_df.loc[unknown_store_mask, "store_id"].unique().tolist())
        raise ValueError(f"store_calendar.csv에 store.csv에 없는 store_id가 있습니다: {bad}")

    calendar_dates_master = set(calendar_df["date"])
    unknown_date_mask = ~sc_df["date"].isin(calendar_dates_master)
    if unknown_date_mask.any():
        bad = sorted(sc_df.loc[unknown_date_mask, "date"].dt.strftime("%Y-%m-%d").unique().tolist())[:10]
        raise ValueError(
            f"store_calendar.csv에 calendar.csv에 없는 date가 있습니다(최대 10개 예시): {bad}"
        )

    raw_flag = sc_df["is_mandatory_closed"]
    is_numeric_like = pd.to_numeric(raw_flag, errors="coerce")
    invalid_flag_mask = ~is_numeric_like.isin([0, 1])
    if invalid_flag_mask.any():
        bad = sorted(raw_flag.loc[invalid_flag_mask].unique().tolist(), key=str)
        raise ValueError(
            f"store_calendar.csv의 is_mandatory_closed에 0/1 이외의 값이 있습니다: {bad}"
        )
    sc_df["is_mandatory_closed"] = is_numeric_like.astype(int)

    expected_days = len(pd.date_range(START_DATE, END_DATE, freq="D"))
    in_range_mask = (sc_df["date"] >= START_DATE) & (sc_df["date"] <= END_DATE)
    days_per_store = sc_df.loc[in_range_mask].groupby("store_id")["date"].nunique()
    stores_missing_days = set(store_ids_master) - set(days_per_store.index)
    incomplete_stores = days_per_store[days_per_store != expected_days]
    if stores_missing_days or len(incomplete_stores) > 0:
        detail = incomplete_stores.to_string()
        raise ValueError(
            f"store_calendar.csv에 {START_DATE.date()}~{END_DATE.date()} 1년치"
            f"({expected_days}일)가 모두 존재하지 않는 매장이 있습니다.\n"
            f"날짜 수가 다른 매장:\n{detail}\n"
            f"1년치가 아예 없는 매장: {sorted(stores_missing_days)}"
        )

    n_closed = int(sc_df["is_mandatory_closed"].sum())
    print(f"[store_calendar.csv 로드 완료] shape={sc_df.shape}, 의무휴업일(행) 수={n_closed}")
    return sc_df


# =========================================================
# 2. 값 정규화 / 공용 계산 함수
#    (생성 단계와 검증 단계가 반드시 이 함수들을 그대로 재사용한다)
# =========================================================
def normalize_markdown_eligible(raw_value, product_id: str) -> bool:
    """
    markdown_eligible 값을 True/False로 안전하게 정규화한다.
    """
    if pd.isna(raw_value):
        raise ValueError(f"{product_id}: markdown_eligible 값이 결측입니다.")

    if isinstance(raw_value, (bool, np.bool_)):
        return bool(raw_value)

    s = str(raw_value).strip().lower()
    if s in MARKDOWN_TRUE_VALUES:
        return True
    if s in MARKDOWN_FALSE_VALUES:
        return False

    raise ValueError(
        f"{product_id}: markdown_eligible 값을 해석할 수 없습니다: {raw_value!r} "
        f"(허용값 - 가능: {sorted(MARKDOWN_TRUE_VALUES)}, 불가능: {sorted(MARKDOWN_FALSE_VALUES)})"
    )


def calculate_freshness_score(days_to_expiry, shelf_life_days: int, decay_type: str) -> float:
    """
    freshness_score 계산 공용 함수 (생성 단계와 검증 단계가 반드시 동일한 함수를 사용한다).

    [v6 수정 - 문제3 해결]
    이전 공식 (days_to_expiry+1)/shelf_life_days 는 shelf_life_days=1인 상품의
    유통기한 당일(days_to_expiry=0)에도 비율이 1.0이 되어 freshness_score=1.0
    (제조일과 동일)이 되는 오류가 있었다.

    v6 공식은 분모에도 +1을 더해 (days_to_expiry+1)/(shelf_life_days+1)을 쓴다.
      - 제조일(days_to_expiry=shelf_life_days): 비율 = (shelf_life_days+1)/(shelf_life_days+1) = 1.0
      - 유통기한 당일(days_to_expiry=0): 비율 = 1/(shelf_life_days+1) < 1.0 (shelf_life_days>=1이면 항상 1보다 작음)
      - 분모(shelf_life_days+1)는 shelf_life_days>=1(사전 검증됨)이므로 항상 2 이상 -> 0으로 나누기 불가능
    days_to_expiry < 0(유통기한 초과)이면 freshness_score = 0.0.
    동일한 로트에 대해 매일 days_to_expiry가 정확히 1씩 감소하므로, 이 함수를
    그대로 재호출하면 freshness_score는 절대 증가하지 않는다(수학적으로 단조
    비증가 함수).
    """
    if decay_type not in DECAY_EXPONENT:
        raise ValueError(f"처리할 수 없는 freshness_decay_type입니다: {decay_type}")
    if shelf_life_days <= 0:
        raise ValueError(f"shelf_life_days가 0 이하입니다: {shelf_life_days}")

    if days_to_expiry < 0:
        return 0.0

    decay_exp = DECAY_EXPONENT[decay_type]
    remaining_ratio = (days_to_expiry + 1) / (shelf_life_days + 1)
    remaining_ratio = float(np.clip(remaining_ratio, 0.0, 1.0))
    freshness_score = remaining_ratio ** decay_exp
    freshness_score = float(np.clip(freshness_score, 0.0, 1.0))
    return round(freshness_score, 4)


def calculate_discount_price(unit_price, discount_rate: int):
    """
    discount_price 계산 공용 함수 (생성 단계와 검증 단계가 반드시 동일한 함수를 사용한다).

    - discount_rate == 0 이면 반올림 없이 unit_price 그대로 반환한다.
    - discount_rate > 0 인 경우에만 10원 단위로 반올림한다.
    - 반올림 결과 discount_price가 unit_price 이상이 되면 unit_price - 10원으로
      보정하고, 그마저 0 이하이면 할인을 취소(discount_rate=0)한다.

    반환값: (discount_price, applied_discount_rate) 튜플.
    """
    if discount_rate < 0:
        raise ValueError(f"discount_rate가 음수입니다: {discount_rate}")

    if discount_rate == 0:
        return unit_price, 0

    raw_discount_price = unit_price * (1 - discount_rate / 100)
    discount_price = int(round(raw_discount_price / 10) * 10)

    if discount_price >= unit_price:
        if unit_price - 10 > 0:
            discount_price = unit_price - 10
        else:
            discount_price = unit_price
            discount_rate = 0

    return discount_price, discount_rate


def compute_target_discount_rate(freshness_score: float, max_discount_pct: int) -> int:
    """
    신선도(freshness_score)로부터 "그날 시점에서 정당화되는 목표 할인율"을
    계산하는 공용 함수 (마감할인 강제 적용 이전의, 신선도 기반 통상 할인율).

    [가정]
    - freshness_score >= 0.6 : 아직 신선하므로 목표 할인율 0
    - 0.3 <= freshness_score < 0.6 : 완만하게 할인 (남은 손실분의 60%만 반영)
    - freshness_score < 0.3 : 적극적으로 할인 (남은 손실분을 그대로 반영)
    - 항상 0 ~ max_discount_pct(상품별 상한, 프로젝트 상한 40% 이내) 범위로 clip한다.
    """
    if freshness_score >= 0.6:
        target = 0.0
    elif freshness_score >= 0.3:
        target = (1 - freshness_score) * max_discount_pct * 0.6
    else:
        target = (1 - freshness_score) * max_discount_pct
    return int(np.clip(round(target), 0, max_discount_pct))


def compute_disposal_candidate(current_stock_qty: int, freshness_score: float, days_to_expiry: int) -> int:
    """
    disposal_candidate 계산 공용 함수 (생성 단계와 검증 단계가 반드시 동일한 함수를 사용한다).

    [v6 수정 - 문제2 해결] current_stock_qty=0인 행(SOLD_OUT/EXPIRED)은 이미
    재고가 없거나 이미 폐기가 끝났으므로 "폐기 후보"일 수 없다 -> 항상 0.
    재고가 남아 있고(current_stock_qty>0) freshness_score가 임계값 미만이거나
    유통기한이 당일 이하(days_to_expiry<=0)인 경우에만 1이다.
    """
    if current_stock_qty <= 0:
        return 0
    if freshness_score < FRESHNESS_DISPOSAL_THRESHOLD or days_to_expiry <= 0:
        return 1
    return 0


def compute_waste_reason(daily_waste_qty: int, is_expired_writeoff: bool) -> str:
    """
    waste_reason 계산 공용 함수 (생성 단계와 검증 단계가 반드시 동일한 함수를 사용한다).
    daily_waste_qty<=0이면 NONE, 유통기한 경과로 인한 당일 폐기(EXPIRED)면 EXPIRED,
    그 외 감모(baseline_waste_rate 기반 자연손실)면 SHRINKAGE.
    """
    if daily_waste_qty <= 0:
        return WASTE_REASON_NONE
    if is_expired_writeoff:
        return WASTE_REASON_EXPIRED
    return WASTE_REASON_SHRINKAGE


def build_product_lookup(product_df: pd.DataFrame) -> dict:
    """
    product_df의 각 행을 product_id 기준 dict로 미리 변환하여
    루프 안에서 반복 조회/검증하지 않도록 준비한다.
    """
    if "max_discount_pct" not in product_df.columns:
        raise ValueError(
            "product_df에 max_discount_pct 컬럼이 없습니다. "
            "load_product_data()를 통해 로드된 product_df를 사용해주세요."
        )

    lookup = {}
    for _, row in product_df.iterrows():
        pid = row["product_id"]
        lookup[pid] = {
            "category": row["category"],
            "sales_type": row["sales_type"],
            "shelf_life_days": int(row["shelf_life_days"]),
            "standard_weight_kg": float(row["standard_weight_kg"]),
            "base_cost": row["base_cost"],
            "base_price": row["base_price"],
            "freshness_decay_type": row["freshness_decay_type"],
            "markdown_eligible": normalize_markdown_eligible(row["markdown_eligible"], pid),
            "max_discount_pct": int(row["max_discount_pct"]),
            "baseline_waste_rate": float(row["baseline_waste_rate"]),
        }
    return lookup


def build_mandatory_closed_lookup(store_calendar_df: pd.DataFrame) -> set:
    """
    store_calendar.csv에서 is_mandatory_closed==1인 (store_id, date) 조합만 뽑아
    {(store_id, "YYYY-MM-DD"), ...} 형태의 set으로 만든다. 날짜 순회 루프 안에서
    매 반복마다 "이 매장, 이 날짜가 의무휴업일인가?"를 O(1)로 조회하기 위한 용도이다.
    """
    closed = store_calendar_df.loc[store_calendar_df["is_mandatory_closed"] == 1]
    return set(zip(closed["store_id"].astype(str), closed["date"].dt.strftime("%Y-%m-%d")))


# =========================================================
# 3. inventory 데이터 생성 (로트가 이어지는 1년치 시뮬레이션)
# =========================================================
def generate_inventory_data(
    product_df: pd.DataFrame,
    store_df: pd.DataFrame,
    store_calendar_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    product.csv / store.csv / store_calendar.csv를 마스터로 하여, 점포x상품별로
    "로트가 실제로 이어지는" 1년치(START_DATE~END_DATE) 재고 이력을 시뮬레이션한다.

    하루 처리 순서 (점포x상품 조합별로 매일 반복):
      1) 신규 입고(재입고) 판단 - 의무휴업일에는 발생시키지 않는다.
      2) 유통기한 초과 로트 처리 - 의무휴업일이 아니면 그날 즉시 전량 폐기
         (daily_waste_qty 기록, current_stock_qty=0, EXPIRED). 의무휴업일이면
         폐기를 미루고 로트를 그대로 이월한다(재고를 줄이지 않는다).
      3) FEFO 판매 배분 - 의무휴업일에는 판매수량을 0으로 강제한다.
      4) 감모(자연손실) 반영 - 의무휴업일에는 0으로 강제한다.
      5) 당일 종료 스냅샷 기록(상태/할인/disposal_candidate/waste_reason을
         이 단계 한 곳에서만 최종 계산) + 다음날 이월 목록 구성.

    각 로트는 입고 시점에 lot_id를 한 번만 발급받고, 판매/감모로 완전히
    소진(SOLD_OUT)되거나 유통기한 경과로 당일 폐기(EXPIRED)될 때까지 같은
    lot_id로 매일 한 행씩 기록된다. (current_date, store_id, product_id,
    lot_id) 조합이 고유하다.
    """
    _reset_module_state()

    product_lookup = build_product_lookup(product_df)
    store_ids = store_df["store_id"].dropna().unique().tolist()
    mandatory_closed_set = build_mandatory_closed_lookup(store_calendar_df)

    # ---- 카테고리 설정값 사전 검증 (조용히 기본값 사용 금지) ----
    for _pid, _meta in product_lookup.items():
        if _meta["category"] not in LOT_COUNT_RANGE:
            raise ValueError(
                f"LOT_COUNT_RANGE에 정의되지 않은 카테고리입니다: {_meta['category']} "
                f"(product_id={_pid})"
            )
        if _meta["category"] not in STOCK_QTY_RANGE:
            raise ValueError(
                f"STOCK_QTY_RANGE에 정의되지 않은 카테고리입니다: {_meta['category']} "
                f"(product_id={_pid})"
            )
        if _meta["freshness_decay_type"] not in DECAY_EXPONENT:
            raise ValueError(
                f"DECAY_EXPONENT에 정의되지 않은 freshness_decay_type입니다: "
                f"{_meta['freshness_decay_type']} (product_id={_pid})"
            )
        if _meta["shelf_life_days"] <= 0:
            raise ValueError(f"{_pid}: shelf_life_days가 0 이하입니다.")

    # ---- ID 채번용 카운터 (클로저에서 nonlocal로 증가시킨다) ----
    lot_counter = 1
    inv_counter = 1

    def next_lot_id():
        nonlocal lot_counter
        lot_id = f"LOT{lot_counter:07d}"
        lot_counter += 1
        return lot_id

    def next_inv_id():
        nonlocal inv_counter
        inv_id = f"INV{inv_counter:07d}"
        inv_counter += 1
        return inv_id

    def make_weight(meta):
        # ---------- weight_kg (로트 생성 시 단 1회만 생성) ----------
        # [의미] "판매 단위(포장/개) 1개당 중량". lot 전체 중량이나 잔여재고
        # 총중량이 아니다 (모듈 docstring [weight_kg 컬럼의 의미] 참고).
        if meta["sales_type"] == "fixed_price":
            return meta["standard_weight_kg"]
        # weight_based: [가정] std = mean*0.15(최소 0.05), 범위는 기준중량의 60~140%
        mean_weight = meta["standard_weight_kg"]
        std_weight = max(mean_weight * 0.15, 0.05)
        lower = max(0.05, mean_weight * 0.6)
        upper = mean_weight * 1.4
        w = np.random.normal(loc=mean_weight, scale=std_weight)
        return round(float(np.clip(w, lower, upper)), 2)

    def make_new_lot(store_id, product_id, meta, manufacture_date, expiry_date, stock_qty):
        return {
            "lot_id": next_lot_id(),
            "store_id": store_id,
            "product_id": product_id,
            "manufacture_date": manufacture_date,
            "expiry_date": expiry_date,
            "unit_cost": meta["base_cost"],
            "unit_price": meta["base_price"],
            "weight_kg": make_weight(meta),
            "current_stock_qty": stock_qty,
            "inbound_qty": stock_qty,       # 이 LOT 최초 생성일의 입고수량 (이후 절대 바뀌지 않음)
            "_first_day_recorded": False,   # 이 LOT의 첫 행이 아직 기록되지 않았는가
            "last_discount": 0,
            "_daily_sold_qty": 0,           # 그날 판매수량 (매일 step3에서 갱신)
            "_daily_waste_qty": 0,          # 그날 감모수량 (매일 step4에서 갱신)
        }

    def pop_inbound_qty(lot):
        """이 LOT의 오늘 행에 기록할 inbound_qty를 반환하고, 최초 기록 여부 플래그를 갱신한다."""
        if lot["_first_day_recorded"]:
            return 0
        lot["_first_day_recorded"] = True
        return lot["inbound_qty"]

    # =====================================================
    # 초기재고 생성 (2025-01-01 기준, 전년도 이월 재고 가정)
    # =====================================================
    # [가정] 초기재고는 전년도에서 이어진 재고이므로 제조일/입고일이
    # START_DATE 이전일 수 있다. 다만 "시작부터 지나치게 많은 만료 재고"를
    # 만들지 않기 위해 age를 0~shelf_life_days 범위로만 제한한다
    # (즉 초기 시점에는 days_to_expiry가 항상 0 이상 -> 만료 재고 없음).
    active_lots = {}
    for store_id in store_ids:
        for product_id, meta in product_lookup.items():
            category = meta["category"]
            shelf_life_days = meta["shelf_life_days"]
            lot_low, lot_high = LOT_COUNT_RANGE[category]
            stock_low, stock_high = STOCK_QTY_RANGE[category]

            n_initial_lots = int(np.random.randint(lot_low, lot_high + 1))
            lots = []
            for _ in range(n_initial_lots):
                age_days = int(np.random.randint(0, shelf_life_days + 1))
                manufacture_date = START_DATE - timedelta(days=age_days)
                expiry_date = manufacture_date + timedelta(days=shelf_life_days)
                stock_qty = int(np.random.randint(stock_low, stock_high + 1))
                lots.append(
                    make_new_lot(store_id, product_id, meta, manufacture_date, expiry_date, stock_qty)
                )
                _GENERATION_STATS["initial_seed_qty"] += stock_qty
            active_lots[(store_id, product_id)] = lots

    rows = []

    # =====================================================
    # 날짜별 시뮬레이션
    # =====================================================
    for current_date in pd.date_range(START_DATE, END_DATE, freq="D"):
        current_date_str = current_date.strftime("%Y-%m-%d")
        for store_id in store_ids:
            for product_id, meta in product_lookup.items():
                category = meta["category"]
                shelf_life_days = meta["shelf_life_days"]
                decay_type = meta["freshness_decay_type"]
                markdown_ok = meta["markdown_eligible"]
                max_discount_pct = meta["max_discount_pct"]
                baseline_waste_rate = meta["baseline_waste_rate"]
                stock_low, stock_high = STOCK_QTY_RANGE[category]

                state = active_lots[(store_id, product_id)]
                is_mandatory_closed_today = (store_id, current_date_str) in mandatory_closed_set

                # ---------- 1) 신규 입고(재입고) 판단 ----------
                # [v6] 의무휴업일에는 입고 자체를 발생시키지 않는다 (재고가 실제로
                # 0인 채로 그날 행이 없을 수 있음 - 이는 정상이다).
                total_stock_before = sum(l["current_stock_qty"] for l in state)
                n_active = len(state)

                if is_mandatory_closed_today:
                    do_restock = False
                elif n_active == 0:
                    # [설계 원칙/가정] 매대가 완전히 비는 날을 만들지 않는다는
                    # 정책을 가정하므로, 영업일에 활성 로트가 하나도 없으면
                    # 반드시 그날 재입고한다.
                    do_restock = True
                elif n_active >= MAX_ACTIVE_LOTS_PER_COMBO:
                    do_restock = False
                else:
                    # [가정] 유통기한이 짧을수록, 재고가 부족할수록 자주 입고된다.
                    base_prob = min(0.9, RESTOCK_BASE_K / shelf_life_days)
                    if total_stock_before < stock_low:
                        restock_prob = min(1.0, base_prob * RESTOCK_LOW_STOCK_MULTIPLIER)
                    elif total_stock_before >= stock_high:
                        restock_prob = base_prob * RESTOCK_AMPLE_STOCK_MULTIPLIER
                    else:
                        restock_prob = base_prob
                    do_restock = bool(np.random.random() < restock_prob)

                if do_restock and n_active < MAX_ACTIVE_LOTS_PER_COMBO:
                    # [가정] 신규 입고는 하루에 1개 로트(트럭 1회 배송)로 본다.
                    max_age = min(RESTOCK_MAX_AGE_DAYS, max(shelf_life_days - 1, 0))
                    age_days = int(np.random.randint(0, max_age + 1))
                    manufacture_date = current_date - timedelta(days=age_days)
                    expiry_date = manufacture_date + timedelta(days=shelf_life_days)
                    stock_qty = int(np.random.randint(stock_low, stock_high + 1))
                    new_lot = make_new_lot(store_id, product_id, meta, manufacture_date, expiry_date, stock_qty)
                    state.append(new_lot)
                    _GENERATION_STATS["restock_qty"] += stock_qty

                # ---------- 2) 유통기한 초과 로트 처리 (당일 즉시 폐기, 의무휴업일 예외) ----------
                remaining_lots = []
                for lot in state:
                    days_to_expiry = (lot["expiry_date"] - current_date).days
                    if days_to_expiry < 0 and not is_mandatory_closed_today:
                        # [v6] 유통기한 경과 재고는 그날 즉시 전량 폐기한다.
                        # daily_waste_qty에 전량 기록하고 current_stock_qty는 0으로
                        # 만든다 (재고인지 폐기수량인지 혼동되지 않도록 분리, 문제1 해결).
                        writeoff_qty = lot["current_stock_qty"]
                        inbound_for_row = pop_inbound_qty(lot)
                        rows.append({
                            "inventory_id": next_inv_id(),
                            "store_id": store_id,
                            "product_id": product_id,
                            "lot_id": lot["lot_id"],
                            "current_date": current_date_str,
                            "manufacture_date": lot["manufacture_date"].strftime("%Y-%m-%d"),
                            "expiry_date": lot["expiry_date"].strftime("%Y-%m-%d"),
                            "days_to_expiry": days_to_expiry,
                            "inbound_qty": inbound_for_row,
                            "daily_sold_qty": 0,
                            "daily_waste_qty": writeoff_qty,
                            "current_stock_qty": 0,
                            "reserved_qty": 0,
                            "available_qty": 0,
                            "freshness_score": 0.0,
                            "unit_cost": lot["unit_cost"],
                            "unit_price": lot["unit_price"],
                            "discount_rate": 0,
                            "discount_price": lot["unit_price"],
                            "disposal_candidate": 0,
                            "inventory_status": STATUS_EXPIRED,
                            "waste_reason": compute_waste_reason(writeoff_qty, is_expired_writeoff=True),
                            "weight_kg": lot["weight_kg"],
                        })
                        _GENERATION_STATS["total_waste_qty_expired"] += writeoff_qty
                        # 폐기된 로트는 다음 날 이월되지 않는다 (재등장 금지).
                    else:
                        if days_to_expiry < 0 and is_mandatory_closed_today:
                            # [v6] 의무휴업일에는 폐기 처리를 미룬다. 로트는 계속
                            # 이월되고, days_to_expiry/freshness_score만 날짜 기준으로
                            # 갱신된다. 실제 폐기(전량 write-off)는 다음 영업일에 일어난다.
                            _GENERATION_STATS["mandatory_closed_expiry_deferred_events"] += 1
                        remaining_lots.append(lot)

                # ---------- 3) FEFO 판매 배분 (유통기한이 빠른 로트부터) ----------
                remaining_lots.sort(key=lambda l: (l["expiry_date"], l["manufacture_date"], l["lot_id"]))
                total_available_before = sum(l["current_stock_qty"] for l in remaining_lots)
                representative_discount = remaining_lots[0]["last_discount"] if remaining_lots else 0

                if is_mandatory_closed_today:
                    # [규칙] 의무휴업일에는 수요 자체를 생성하지 않는다 (판매수량=0 강제).
                    demand_qty = 0
                elif total_available_before > 0:
                    lo_frac, hi_frac = DAILY_DEMAND_FRACTION_RANGE
                    base_fraction = np.random.uniform(lo_frac, hi_frac)  # [가정] 일일 판매 비율
                    discount_boost = (representative_discount / 100.0) * DAILY_DEMAND_DISCOUNT_BOOST
                    demand_fraction = min(1.0, base_fraction + discount_boost)
                    demand_qty = int(round(total_available_before * demand_fraction))
                    demand_qty = min(demand_qty, total_available_before)
                else:
                    demand_qty = 0

                if is_mandatory_closed_today and total_available_before > 0:
                    _GENERATION_STATS["mandatory_closed_skip_events"] += 1

                remaining_demand = demand_qty
                for lot in remaining_lots:
                    stock_before = lot["current_stock_qty"]
                    sell_qty = min(remaining_demand, stock_before)
                    remaining_demand -= sell_qty
                    stock_after_sale = stock_before - sell_qty

                    # ---- FEFO 검증용 내부 로그 (CSV로 저장되지 않음) ----
                    # 판매되지 않은(sell_qty=0) lot도 반드시 기록해야, validate_inventory()에서
                    # "그날 존재했던 모든 lot"을 대상으로 FEFO 위반을 검사할 수 있다.
                    _FIFO_SALE_LOG.append({
                        "current_date": current_date_str,
                        "store_id": store_id,
                        "product_id": product_id,
                        "lot_id": lot["lot_id"],
                        "expiry_date": lot["expiry_date"].strftime("%Y-%m-%d"),
                        "manufacture_date": lot["manufacture_date"].strftime("%Y-%m-%d"),
                        "stock_before_sale": stock_before,
                        "sold_qty": sell_qty,
                        "stock_after_sale": stock_after_sale,
                    })
                    _GENERATION_STATS["total_sold_qty"] += sell_qty

                    # ---------- 4) 감모(자연손실) 반영 (baseline_waste_rate 실사용) ----------
                    if is_mandatory_closed_today:
                        # [규칙] 의무휴업일은 판매뿐 아니라 자연감모(waste)도 발생시키지
                        # 않는다. 그래야 재고 스냅샷 상 그날의 재고 변화가 정확히 0이 된다.
                        waste_qty = 0
                    elif stock_after_sale > 0:
                        lo_mult, hi_mult = DAILY_WASTE_RATE_MULTIPLIER_RANGE
                        daily_loss_rate = baseline_waste_rate * np.random.uniform(lo_mult, hi_mult)
                        waste_qty = int(round(stock_after_sale * daily_loss_rate))
                        waste_qty = min(waste_qty, stock_after_sale)
                    else:
                        waste_qty = 0

                    _GENERATION_STATS["total_waste_qty_shrinkage"] += waste_qty
                    lot["current_stock_qty"] = stock_after_sale - waste_qty
                    lot["_daily_sold_qty"] = sell_qty
                    lot["_daily_waste_qty"] = waste_qty

                # ---------- 5) 당일 종료 스냅샷 생성 + 다음날 이월 목록 구성 ----------
                # 상태(inventory_status)/할인/disposal_candidate/waste_reason은
                # 모두 이 블록 한 곳에서만 최종적으로 계산한다 (서로 덮어쓰지 않음).
                next_state = []
                for lot in remaining_lots:
                    days_to_expiry = (lot["expiry_date"] - current_date).days
                    # days_to_expiry는 보통 >=0 (2단계에서 필터링됨). 단, 의무휴업일에
                    # 폐기가 유예된 로트는 days_to_expiry<0일 수 있다(그 경우도
                    # calculate_freshness_score가 0.0을 반환하므로 안전하다).
                    freshness_score = calculate_freshness_score(days_to_expiry, shelf_life_days, decay_type)
                    stock = lot["current_stock_qty"]
                    sold_qty_today = lot["_daily_sold_qty"]
                    waste_qty_today = lot["_daily_waste_qty"]
                    inbound_for_row = pop_inbound_qty(lot)

                    if stock <= 0:
                        # 판매/감모로 완전히 소진된 로트: SOLD_OUT으로 마지막 1회 기록 후 제거
                        discount_rate_final = 0
                        discount_price = lot["unit_price"]
                        inventory_status = STATUS_SOLD_OUT
                    else:
                        target_discount = (
                            compute_target_discount_rate(freshness_score, max_discount_pct)
                            if markdown_ok else 0
                        )
                        if days_to_expiry == 0:
                            # [v6, 문제4 해결] 유통기한 당일에는 markdown_eligible 여부와
                            # 무관하게 최소 마감할인을 강제하여 NORMAL로 남지 않게 한다.
                            target_discount = max(target_discount, EXPIRY_DAY_MIN_DISCOUNT_PCT)
                            target_discount = min(target_discount, max_discount_pct)
                        # [안전장치] 목표 할인율과 전날 할인율 중 큰 값을 취해,
                        # 특별한 사유(소진) 없이 할인율이 내려가지 않도록 한다.
                        candidate_rate = max(lot["last_discount"], target_discount)
                        candidate_rate = int(np.clip(candidate_rate, 0, max_discount_pct))

                        discount_price, discount_rate_final = calculate_discount_price(
                            lot["unit_price"], candidate_rate
                        )
                        lot["last_discount"] = discount_rate_final

                        # [v6] 상태는 discount_rate_final 하나로부터만 결정한다
                        # (재고>0 & discount>0 -> DISCOUNT, 재고>0 & discount=0 -> NORMAL).
                        # days_to_expiry=0이면 위에서 이미 discount_rate_final>0이
                        # 보장되므로 NORMAL이 나올 수 없다.
                        inventory_status = STATUS_DISCOUNT if discount_rate_final > 0 else STATUS_NORMAL

                    disposal_candidate = compute_disposal_candidate(stock, freshness_score, days_to_expiry)
                    waste_reason = compute_waste_reason(waste_qty_today, is_expired_writeoff=False)
                    reserved_qty = 0  # [설계결정] 이 프로젝트에서는 예약재고 기능을 사용하지
                    # 않으므로 reserved_qty는 항상 0으로 고정한다. 그 결과 available_qty는
                    # current_stock_qty와 항상 같다(모순 여지 자체를 제거).
                    available_qty = stock

                    rows.append({
                        "inventory_id": next_inv_id(),
                        "store_id": store_id,
                        "product_id": product_id,
                        "lot_id": lot["lot_id"],
                        "current_date": current_date_str,
                        "manufacture_date": lot["manufacture_date"].strftime("%Y-%m-%d"),
                        "expiry_date": lot["expiry_date"].strftime("%Y-%m-%d"),
                        "days_to_expiry": days_to_expiry,
                        "inbound_qty": inbound_for_row,
                        "daily_sold_qty": sold_qty_today,
                        "daily_waste_qty": waste_qty_today,
                        "current_stock_qty": stock,
                        "reserved_qty": reserved_qty,
                        "available_qty": available_qty,
                        "freshness_score": freshness_score,
                        "unit_cost": lot["unit_cost"],
                        "unit_price": lot["unit_price"],
                        "discount_rate": discount_rate_final,
                        "discount_price": discount_price,
                        "disposal_candidate": disposal_candidate,
                        "inventory_status": inventory_status,
                        "waste_reason": waste_reason,
                        "weight_kg": lot["weight_kg"],
                    })

                    if stock > 0:
                        next_state.append(lot)
                    # stock <= 0 (SOLD_OUT)인 로트는 다음날 이월하지 않는다 (재등장 금지).

                active_lots[(store_id, product_id)] = next_state

    if not rows:
        raise ValueError("생성된 inventory 행이 없습니다. product.csv / store.csv 내용을 확인해주세요.")

    # ---- ID 7자리 한도 사후 검증 (동적 시뮬레이션이라 사전 정확 계산이 불가능하므로
    #      실제로 발급된 개수를 기준으로 검증한다). 임의로 ID 형식을 바꾸지 않는다. ----
    total_inv_issued = inv_counter - 1
    total_lot_issued = lot_counter - 1
    if total_inv_issued > 9_999_999:
        raise ValueError(
            f"생성된 inventory 행 수({total_inv_issued})가 INV ID 7자리 형식(^INV\\d{{7}}$, "
            f"최대 9,999,999)을 초과합니다. ID 형식은 임의로 변경하지 않으므로 "
            f"점포/상품 수, 시뮬레이션 기간, 재입고 빈도를 먼저 검토해주세요."
        )
    if total_lot_issued > 9_999_999:
        raise ValueError(
            f"생성된 lot 수({total_lot_issued})가 LOT ID 7자리 형식(^LOT\\d{{7}}$, "
            f"최대 9,999,999)을 초과합니다."
        )

    inventory_df = pd.DataFrame(rows)
    inventory_df = inventory_df[COLUMN_ORDER]

    print(
        f"[inventory 생성 완료] 총 {len(inventory_df)}행 생성 "
        f"(발급된 lot 수: {total_lot_issued}, inventory_id 수: {total_inv_issued}, "
        f"의무휴업으로 판매/감모를 건너뛴 조합-일수: {_GENERATION_STATS['mandatory_closed_skip_events']}, "
        f"의무휴업으로 폐기가 유예된 조합-일수: {_GENERATION_STATS['mandatory_closed_expiry_deferred_events']})"
    )
    return inventory_df


# =========================================================
# 4. 검증
# =========================================================
def validate_inventory(
    inventory_df: pd.DataFrame,
    product_df: pd.DataFrame,
    store_df: pd.DataFrame,
    calendar_df: pd.DataFrame,
    store_calendar_df: pd.DataFrame,
) -> bool:
    """
    inventory_df(1년치 로트 이력)에 대한 전 항목 검증을 수행하고
    [PASS]/[FAIL](: 오류 건수)/[WARN]으로 출력한다.
    [FAIL] 항목이 하나라도 있으면 False를 반환한다 (검증 실패 시 저장하지 않음).
    [WARN]은 랜덤 생성 특성상 우연히 발생/미발생할 수 있는 항목에만 사용하며
    all_passed에는 영향을 주지 않는다.

    lot_id는 여러 날짜에 걸쳐 반복 등장하는 것이 정상이므로 "lot_id 전체 고유"는
    검증하지 않는다. 대신 (current_date, store_id, product_id, lot_id) 조합의
    고유성과, 동일 lot_id가 시간이 지나도 store_id/product_id/제조일/유통기한을
    그대로 유지하는지를 검증한다. lot 단위 시계열 연산(날짜 연속성, 재고 단조성,
    LOT 흐름식 등)은 LOT_KEYS(store_id+product_id+lot_id) 조합으로 그룹화하여,
    lot_id가 매장/상품 간에 우연히 섞이는 경우까지 방어한다.
    """
    global _VALIDATION_STATS
    _VALIDATION_STATS = {}

    print("\n" + "=" * 70)
    print("inventory.csv 검증 시작 (v6: 판매/폐기 수량 분리 + 상태/신선도/할인 규칙 정합성)")
    print("=" * 70)

    all_passed = True

    def check(name: str, condition: bool, fail_count=None):
        nonlocal all_passed
        ok = bool(condition)
        if not ok:
            all_passed = False
            if fail_count is not None:
                print(f"[FAIL] {name}: {fail_count}건")
            else:
                print(f"[FAIL] {name}")
        else:
            print(f"[PASS] {name}")

    def check_warn(name: str, condition: bool):
        status = "PASS" if bool(condition) else "WARN"
        print(f"[{status}] {name}")

    # ---- product / store / calendar / store_calendar 참조 데이터 준비 ----
    product_meta = build_product_lookup(product_df)
    store_ids_master = set(store_df["store_id"].dropna().unique())
    product_ids_master = set(product_df["product_id"])
    calendar_date_strs = set(calendar_df["date"].dt.strftime("%Y-%m-%d"))
    store_calendar_key_strs = set(
        store_calendar_df["store_id"].astype(str) + "|" + store_calendar_df["date"].dt.strftime("%Y-%m-%d")
    )

    merged = inventory_df.merge(
        product_df[[
            "product_id", "category", "shelf_life_days", "sales_type",
            "standard_weight_kg", "base_cost", "base_price", "freshness_decay_type",
        ]],
        on="product_id", how="left", validate="many_to_one",
    )

    # =====================================================
    # [데이터 규모 출력]
    # =====================================================
    print(f"\n전체 shape: {inventory_df.shape}")
    print(f"점포 수: {inventory_df['store_id'].nunique()}")
    print(f"상품 수: {inventory_df['product_id'].nunique()}")
    print(f"고유 lot_id 수: {inventory_df['lot_id'].nunique()}  (참고: lot_id는 여러 날짜에 반복 등장하는 것이 정상)")
    print("\n상태별 행 수:")
    print(inventory_df["inventory_status"].value_counts())
    print("\nwaste_reason별 행 수:")
    print(inventory_df["waste_reason"].value_counts())
    print("\ndtype:")
    print(inventory_df.dtypes)

    print("\n--- 세부 검증 ---")

    # =====================================================
    # [기본]
    # =====================================================
    check("필수 컬럼 존재(스키마 순서 포함)", list(inventory_df.columns) == COLUMN_ORDER)
    n_null = int(inventory_df.isnull().sum().sum())
    check("결측값 0", n_null == 0, fail_count=n_null)
    n_dup_rows = int(inventory_df.duplicated().sum())
    check("전체 행 중복 0", n_dup_rows == 0, fail_count=n_dup_rows)
    n_dup_invid = int(inventory_df["inventory_id"].duplicated().sum())
    check("inventory_id 중복 0", n_dup_invid == 0, fail_count=n_dup_invid)
    n_dup_lotdate = int(inventory_df.duplicated(subset=["lot_id", "current_date"]).sum())
    check("lot_id + current_date 중복 0", n_dup_lotdate == 0, fail_count=n_dup_lotdate)
    n_dup_fullkey = int(inventory_df.duplicated(subset=["store_id", "product_id", "lot_id", "current_date"]).sum())
    check(
        "(store_id+product_id+lot_id+current_date) 기본키 중복 0 (lot_id 전역유일 가정의 상위 검증)",
        n_dup_fullkey == 0, fail_count=n_dup_fullkey
    )

    manufacture_dt = pd.to_datetime(inventory_df["manufacture_date"], errors="coerce")
    expiry_dt = pd.to_datetime(inventory_df["expiry_date"], errors="coerce")
    current_dt = pd.to_datetime(inventory_df["current_date"], errors="coerce")
    n_date_parse_fail = int(manufacture_dt.isnull().sum() + expiry_dt.isnull().sum() + current_dt.isnull().sum())
    check("날짜 파싱 오류 0", n_date_parse_fail == 0, fail_count=n_date_parse_fail)

    expected_dates_index = pd.date_range(START_DATE, END_DATE, freq="D")
    actual_dates_index = pd.DatetimeIndex(sorted(current_dt.dropna().unique()))
    missing_dates_index = expected_dates_index.difference(actual_dates_index)
    extra_dates_index = actual_dates_index.difference(expected_dates_index)
    check(
        f"날짜 범위 {START_DATE.date()}~{END_DATE.date()} 정확히 일치(누락/초과 없음)",
        len(missing_dates_index) == 0 and len(extra_dates_index) == 0
        and (current_dt.min() >= START_DATE) and (current_dt.max() <= END_DATE)
    )

    qty_cols = [
        "inbound_qty", "daily_sold_qty", "daily_waste_qty",
        "current_stock_qty", "reserved_qty", "available_qty",
        "unit_cost", "unit_price", "discount_rate", "discount_price", "disposal_candidate",
    ]
    neg_total = 0
    for c in qty_cols:
        neg_total += int((inventory_df[c] < 0).sum())
    check("음수 수량/금액 컬럼 0", neg_total == 0, fail_count=neg_total)

    dtype_bad = 0
    for c in qty_cols:
        vals = inventory_df[c].astype(float)
        dtype_bad += int((~np.isclose(vals, np.round(vals))).sum())
    check("수량/금액 컬럼 정수 여부(소수 섞임 없음)", dtype_bad == 0, fail_count=dtype_bad)

    n_disc_range_bad = int((~inventory_df["discount_rate"].between(0, 40)).sum())
    check("할인율(discount_rate) 0~40 범위", n_disc_range_bad == 0, fail_count=n_disc_range_bad)

    calc_results = [
        calculate_discount_price(up, int(dr))
        for up, dr in zip(inventory_df["unit_price"], inventory_df["discount_rate"])
    ]
    expected_discount_price = pd.Series([r[0] for r in calc_results], index=inventory_df.index)
    expected_discount_rate_after_calc = pd.Series([r[1] for r in calc_results], index=inventory_df.index)
    n_price_mismatch = int((expected_discount_price != inventory_df["discount_price"]).sum())
    check("가격 계산 일치 (calculate_discount_price 재계산값과 동일)", n_price_mismatch == 0, fail_count=n_price_mismatch)
    n_rate_unstable = int((expected_discount_rate_after_calc != inventory_df["discount_rate"]).sum())
    check("discount_rate가 가격 계산 보정 후에도 안정적", n_rate_unstable == 0, fail_count=n_rate_unstable)

    n_price_gt_unit = int((inventory_df["discount_price"] > inventory_df["unit_price"]).sum())
    check("discount_price <= unit_price", n_price_gt_unit == 0, fail_count=n_price_gt_unit)

    # =====================================================
    # 외래키
    # =====================================================
    n_bad_pid = int((~inventory_df["product_id"].isin(product_ids_master)).sum())
    check("모든 product_id가 product.csv에 존재", n_bad_pid == 0, fail_count=n_bad_pid)
    n_bad_sid = int((~inventory_df["store_id"].astype(str).isin(store_ids_master)).sum())
    check("모든 store_id가 store.csv에 존재", n_bad_sid == 0, fail_count=n_bad_sid)
    n_bad_cdate = int((~inventory_df["current_date"].isin(calendar_date_strs)).sum())
    check("모든 current_date가 calendar.csv에 존재", n_bad_cdate == 0, fail_count=n_bad_cdate)
    inv_store_date_keys = inventory_df["store_id"].astype(str) + "|" + inventory_df["current_date"]
    n_bad_sckey = int((~inv_store_date_keys.isin(store_calendar_key_strs)).sum())
    check("모든 (store_id, current_date) 조합이 store_calendar.csv에 존재", n_bad_sckey == 0, fail_count=n_bad_sckey)

    check("inventory_id 형식(^INV\\d{7}$) 일치", inventory_df["inventory_id"].str.match(INVENTORY_ID_PATTERN).all())
    check("lot_id 형식(^LOT\\d{7}$) 일치", inventory_df["lot_id"].str.match(LOT_ID_PATTERN).all())

    # ---- 동일 lot_id는 항상 같은 store_id/product_id/제조일/유통기한 유지 ----
    lot_nunique_store = inventory_df.groupby("lot_id")["store_id"].nunique()
    lot_nunique_product = inventory_df.groupby("lot_id")["product_id"].nunique()
    lot_nunique_mfg = inventory_df.groupby("lot_id")["manufacture_date"].nunique()
    lot_nunique_exp = inventory_df.groupby("lot_id")["expiry_date"].nunique()
    check("동일 LOT의 store_id 변경 0", int((lot_nunique_store != 1).sum()) == 0, fail_count=int((lot_nunique_store != 1).sum()))
    check("동일 LOT의 product_id 변경 0", int((lot_nunique_product != 1).sum()) == 0, fail_count=int((lot_nunique_product != 1).sum()))
    check("동일 LOT의 manufacture_date 변경 0", int((lot_nunique_mfg != 1).sum()) == 0, fail_count=int((lot_nunique_mfg != 1).sum()))
    check("동일 LOT의 expiry_date 변경 0", int((lot_nunique_exp != 1).sum()) == 0, fail_count=int((lot_nunique_exp != 1).sum()))

    # =====================================================
    # 유통기한 / days_to_expiry
    # =====================================================
    check("current_date가 manufacture_date보다 이르지 않음(판매일이 입고일보다 빠를 수 없음)", (current_dt >= manufacture_dt).all())
    recompute_expiry = manufacture_dt + pd.to_timedelta(merged["shelf_life_days"], unit="D")
    check("expiry_date = manufacture_date + shelf_life_days 일치", (recompute_expiry == expiry_dt).all())
    recompute_days = (expiry_dt - current_dt).dt.days
    n_days_mismatch = int((recompute_days != inventory_df["days_to_expiry"]).sum())
    check("days_to_expiry = expiry_date - current_date 정확히 일치", n_days_mismatch == 0, fail_count=n_days_mismatch)

    # ---- LOT_KEYS(store_id+product_id+lot_id) 기준 정렬 (이후 모든 시계열 검증의 기반) ----
    sorted_df = inventory_df.copy()
    sorted_df["_current_dt"] = current_dt.values
    sorted_df = sorted_df.sort_values(LOT_KEYS + ["_current_dt"]).reset_index(drop=True)
    grp = sorted_df.groupby(LOT_KEYS, sort=False)

    lot_span = sorted_df.groupby(LOT_KEYS)["_current_dt"].agg(["min", "max", "count"])
    lot_span["_expected_count"] = (lot_span["max"] - lot_span["min"]).dt.days + 1
    span_ok = (lot_span["_expected_count"] == lot_span["count"])
    n_span_bad = int((~span_ok).sum())
    if n_span_bad > 0:
        bad_lots = lot_span.index[~span_ok].tolist()[:10]
        print(f"\n[날짜 연속성/재등장 위반 LOT 예시(최대 10개, store_id/product_id/lot_id)] {bad_lots}")
    check(
        "LOT 날짜 중간 누락 0 (동시에 소진·폐기 LOT 재등장 0도 함께 검증)",
        n_span_bad == 0, fail_count=n_span_bad
    )
    _VALIDATION_STATS["missing_date_lot_count"] = n_span_bad

    # =====================================================
    # 수량 관계
    # =====================================================
    check("current_stock_qty >= 0", (inventory_df["current_stock_qty"] >= 0).all())
    check("available_qty >= 0", (inventory_df["available_qty"] >= 0).all())
    check("reserved_qty >= 0", (inventory_df["reserved_qty"] >= 0).all())
    n_sum_bad = int((inventory_df["current_stock_qty"] != inventory_df["available_qty"] + inventory_df["reserved_qty"]).sum())
    check("current_stock_qty = available_qty + reserved_qty", n_sum_bad == 0, fail_count=n_sum_bad)

    n_zero_stock_avail_bad = int(
        ((inventory_df["current_stock_qty"] == 0) & (inventory_df["available_qty"] > 0)).sum()
    )
    check("current_stock_qty=0인데 available_qty>0인 행 0", n_zero_stock_avail_bad == 0, fail_count=n_zero_stock_avail_bad)

    n_zero_stock_disp_bad = int(
        ((inventory_df["current_stock_qty"] == 0) & (inventory_df["disposal_candidate"] == 1)).sum()
    )
    check("current_stock_qty=0인데 disposal_candidate=1인 행 0", n_zero_stock_disp_bad == 0, fail_count=n_zero_stock_disp_bad)

    n_sold_neg = int((inventory_df["daily_sold_qty"] < 0).sum())
    n_waste_neg = int((inventory_df["daily_waste_qty"] < 0).sum())
    check("daily_sold_qty 음수 0", n_sold_neg == 0, fail_count=n_sold_neg)
    check("daily_waste_qty 음수 0", n_waste_neg == 0, fail_count=n_waste_neg)

    # ---- LOT 흐름식: current = prev(같은 LOT, 없으면 0) + inbound - sold - waste ----
    sorted_df["_prev_stock"] = grp["current_stock_qty"].shift(1).fillna(0)
    flow_lhs = sorted_df["_prev_stock"] + sorted_df["inbound_qty"] - sorted_df["daily_sold_qty"] - sorted_df["daily_waste_qty"]
    flow_mismatch_mask = (flow_lhs.round(6) != sorted_df["current_stock_qty"].astype(float).round(6))
    n_flow_bad = int(flow_mismatch_mask.sum())
    if n_flow_bad > 0:
        bad_examples = sorted_df.loc[flow_mismatch_mask, LOT_KEYS + ["current_date"]].head(10).values.tolist()
        print(f"\n[LOT 흐름식 불일치 예시(최대 10개)] {bad_examples}")
    check(
        "LOT 흐름식 일치 (current_stock_qty = 전날재고 + inbound_qty - daily_sold_qty - daily_waste_qty)",
        n_flow_bad == 0, fail_count=n_flow_bad
    )

    n_pool_exceed = int(
        ((sorted_df["daily_sold_qty"] + sorted_df["daily_waste_qty"]) > (sorted_df["_prev_stock"] + sorted_df["inbound_qty"])).sum()
    )
    check(
        "daily_sold_qty + daily_waste_qty가 그날 보유 가능했던 수량(전날재고+inbound_qty)을 초과하지 않음",
        n_pool_exceed == 0, fail_count=n_pool_exceed
    )

    # ---- inbound_qty: LOT 최초일에만 >0, 이후에는 항상 0 ----
    is_first_row = ~grp.cumcount().astype(bool)  # 그룹 내 첫 번째 행이면 True
    n_first_zero_inbound = int(((is_first_row) & (sorted_df["inbound_qty"] <= 0)).sum())
    check("신규 LOT 최초일 inbound_qty > 0", n_first_zero_inbound == 0, fail_count=n_first_zero_inbound)
    n_nonfirst_nonzero_inbound = int(((~is_first_row) & (sorted_df["inbound_qty"] != 0)).sum())
    check("LOT 최초일 이후 inbound_qty = 0", n_nonfirst_nonzero_inbound == 0, fail_count=n_nonfirst_nonzero_inbound)

    # ---- LOT 재고 역증가 0 ----
    stock_diff = grp["current_stock_qty"].diff()
    stock_diff_vals = stock_diff.dropna()
    n_stock_increase = int((stock_diff_vals > 0).sum())
    check("LOT 재고 역증가(시간이 지나며 증가) 0", n_stock_increase == 0, fail_count=n_stock_increase)
    _VALIDATION_STATS["stock_increase_violation_count"] = n_stock_increase

    # =====================================================
    # 상태
    # =====================================================
    check("허용 상태값만 존재", inventory_df["inventory_status"].isin(VALID_STATUSES).all())
    check("허용 waste_reason 값만 존재", inventory_df["waste_reason"].isin(VALID_WASTE_REASONS).all())

    sold_out_mask = inventory_df["inventory_status"] == STATUS_SOLD_OUT
    expired_mask = inventory_df["inventory_status"] == STATUS_EXPIRED
    discount_mask = inventory_df["inventory_status"] == STATUS_DISCOUNT
    normal_mask = inventory_df["inventory_status"] == STATUS_NORMAL

    n_so_stock_bad = int((inventory_df.loc[sold_out_mask, "current_stock_qty"] > 0).sum())
    check("SOLD_OUT인데 current_stock_qty>0인 행 0", n_so_stock_bad == 0, fail_count=n_so_stock_bad)
    n_so_disp_bad = int((inventory_df.loc[sold_out_mask, "disposal_candidate"] == 1).sum())
    check("SOLD_OUT인데 disposal_candidate=1인 행 0", n_so_disp_bad == 0, fail_count=n_so_disp_bad)

    n_exp_stock_bad = int((inventory_df.loc[expired_mask, "current_stock_qty"] > 0).sum())
    check("EXPIRED인데 current_stock_qty>0인 행 0", n_exp_stock_bad == 0, fail_count=n_exp_stock_bad)
    n_exp_waste_bad = int((inventory_df.loc[expired_mask, "daily_waste_qty"] <= 0).sum())
    check("EXPIRED인데 daily_waste_qty<=0인 행 0", n_exp_waste_bad == 0, fail_count=n_exp_waste_bad)
    n_exp_reason_bad = int((inventory_df.loc[expired_mask, "waste_reason"] != WASTE_REASON_EXPIRED).sum())
    check("EXPIRED인데 waste_reason != EXPIRED인 행 0", n_exp_reason_bad == 0, fail_count=n_exp_reason_bad)
    n_exp_freshness_bad = int((inventory_df.loc[expired_mask, "freshness_score"] != 0.0).sum())
    check("EXPIRED인데 freshness_score != 0.0인 행 0", n_exp_freshness_bad == 0, fail_count=n_exp_freshness_bad)

    n_disc_rate0_bad = int((inventory_df.loc[discount_mask, "discount_rate"] == 0).sum())
    check("DISCOUNT인데 discount_rate=0인 행 0", n_disc_rate0_bad == 0, fail_count=n_disc_rate0_bad)
    n_normal_rate_bad = int((inventory_df.loc[normal_mask, "discount_rate"] > 0).sum())
    check("NORMAL인데 discount_rate>0인 행 0", n_normal_rate_bad == 0, fail_count=n_normal_rate_bad)

    n_zero_day_normal = int(((inventory_df["days_to_expiry"] == 0) & (inventory_df["inventory_status"] == STATUS_NORMAL)).sum())
    check("days_to_expiry=0인데 NORMAL인 행 0", n_zero_day_normal == 0, fail_count=n_zero_day_normal)

    n_neg_day_sold = int(((inventory_df["days_to_expiry"] < 0) & (inventory_df["daily_sold_qty"] > 0)).sum())
    check("days_to_expiry<0인데 판매량(daily_sold_qty)이 발생한 행 0", n_neg_day_sold == 0, fail_count=n_neg_day_sold)

    # ---- 할인 불가(markdown_eligible=False) 상품: 아직 유통기한이 남아있는(days_to_expiry>0)
    #      동안에는 discount_rate=0이어야 한다. days_to_expiry<=0인 구간(유통기한 당일의
    #      강제 마감할인, 그리고 의무휴업으로 폐기가 유예되어 그 다음날 이후까지 이어지는
    #      한도 내의 "유예 구간")은 예외이다 - 한 번 강제된 마감할인은 "할인율은 내려가지
    #      않는다"는 안전장치에 의해 유예 구간 동안 그대로 유지되는 것이 정상 동작이다. ----
    markdown_map = {pid: meta["markdown_eligible"] for pid, meta in product_meta.items()}
    markdown_series = inventory_df["product_id"].map(markdown_map)
    not_eligible_mask = ~markdown_series
    not_eligible_normal_day_mask = not_eligible_mask & (inventory_df["days_to_expiry"] > 0)
    n_not_eligible_bad = int((inventory_df.loc[not_eligible_normal_day_mask, "discount_rate"] != 0).sum())
    check(
        "할인 불가(markdown_eligible=False) 상품은 유통기한이 남아있는 동안(days_to_expiry>0) discount_rate=0",
        n_not_eligible_bad == 0, fail_count=n_not_eligible_bad
    )
    not_eligible_expiry_day_mask = not_eligible_mask & (inventory_df["days_to_expiry"] == 0) & (inventory_df["current_stock_qty"] > 0)
    if not_eligible_expiry_day_mask.any():
        n_forced_bad = int((inventory_df.loc[not_eligible_expiry_day_mask, "discount_rate"] <= 0).sum())
        check("할인 불가 상품도 유통기한 당일에는 마감할인이 강제 적용됨(discount_rate>0)", n_forced_bad == 0, fail_count=n_forced_bad)

    max_disc_map = {pid: meta["max_discount_pct"] for pid, meta in product_meta.items()}
    max_disc_series = inventory_df["product_id"].map(max_disc_map)
    n_exceed_max = int((inventory_df["discount_rate"] > max_disc_series).sum())
    check("discount_rate가 상품별 max_discount_rate 이하", n_exceed_max == 0, fail_count=n_exceed_max)

    # ---- 동일 LOT의 DISCOUNT/NORMAL 구간에서 discount_rate는 비감소 ----
    nd_mask_sorted = sorted_df["inventory_status"].isin([STATUS_NORMAL, STATUS_DISCOUNT])
    disc_diff = sorted_df.loc[nd_mask_sorted].groupby(LOT_KEYS)["discount_rate"].diff()
    disc_diff_vals = disc_diff.dropna()
    n_disc_decrease = int((disc_diff_vals < 0).sum())
    check("동일 LOT의 NORMAL/DISCOUNT 구간에서 discount_rate가 비감소", n_disc_decrease == 0, fail_count=n_disc_decrease)

    # =====================================================
    # 신선도
    # =====================================================
    n_fresh_range_bad = int((~inventory_df["freshness_score"].between(0, 1)).sum())
    check("freshness_score 0~1 범위", n_fresh_range_bad == 0, fail_count=n_fresh_range_bad)

    expected_freshness = [
        calculate_freshness_score(int(days), int(sld), decay)
        for days, sld, decay in zip(
            merged["days_to_expiry"], merged["shelf_life_days"], merged["freshness_decay_type"]
        )
    ]
    expected_freshness = pd.Series(expected_freshness, index=merged.index)
    n_fresh_mismatch = int((np.abs(expected_freshness - inventory_df["freshness_score"]) > 0.0001).sum())
    check("freshness_score가 재계산값과 허용오차(0.0001) 이내로 일치", n_fresh_mismatch == 0, fail_count=n_fresh_mismatch)

    fresh_diff = grp["freshness_score"].diff()
    fresh_diff_vals = fresh_diff.dropna()
    n_fresh_increase = int((fresh_diff_vals > 1e-9).sum())
    check("동일 LOT의 freshness_score가 날짜가 지나도 증가하지 않음", n_fresh_increase == 0, fail_count=n_fresh_increase)

    n_zero_day_full_fresh = int(((inventory_df["days_to_expiry"] == 0) & (inventory_df["freshness_score"] >= 1.0)).sum())
    check("days_to_expiry=0인데 freshness_score=1.0인 행 0", n_zero_day_full_fresh == 0, fail_count=n_zero_day_full_fresh)

    n_neg_day_fresh_bad = int(((inventory_df["days_to_expiry"] < 0) & (inventory_df["freshness_score"] != 0.0)).sum())
    check("days_to_expiry<0인데 freshness_score != 0인 행 0", n_neg_day_fresh_bad == 0, fail_count=n_neg_day_fresh_bad)

    shelf1_mask = (merged["shelf_life_days"] == 1) & (inventory_df["days_to_expiry"] == 0)
    if shelf1_mask.any():
        n_shelf1_bad = int((inventory_df.loc[shelf1_mask, "freshness_score"] >= 1.0).sum())
        check("shelf_life_days=1 상품의 유통기한 당일 freshness_score < 1.0", n_shelf1_bad == 0, fail_count=n_shelf1_bad)
    else:
        check_warn("shelf_life_days=1 상품의 유통기한 당일 데이터가 존재함(검증 대상 있음)", False)

    # =====================================================
    # weight_based / sales_type 재검증
    # =====================================================
    unknown_sales_types_in_inv = set(merged["sales_type"].dropna().unique()) - ALLOWED_SALES_TYPES
    check(f"inventory에 연결된 sales_type이 허용값({sorted(ALLOWED_SALES_TYPES)})만 존재", len(unknown_sales_types_in_inv) == 0)
    check("모든 weight_kg > 0", (inventory_df["weight_kg"] > 0).all())

    fixed_mask = merged["sales_type"] == "fixed_price"
    n_fixed_bad = int((merged.loc[fixed_mask, "weight_kg"] != merged.loc[fixed_mask, "standard_weight_kg"]).sum()) if fixed_mask.any() else 0
    check("fixed_price 상품 weight_kg = standard_weight_kg 일치", n_fixed_bad == 0, fail_count=n_fixed_bad)

    weight_based_mask = merged["sales_type"] == "weight_based"
    if weight_based_mask.any():
        wb = merged.loc[weight_based_mask]
        lower_bound = (wb["standard_weight_kg"] * 0.6).clip(lower=0.05)
        upper_bound = wb["standard_weight_kg"] * 1.4
        eps = 1e-9
        n_wb_bad = int((~((wb["weight_kg"] >= lower_bound - eps) & (wb["weight_kg"] <= upper_bound + eps))).sum())
        check("weight_based 상품 weight_kg가 기준중량의 60~140% 범위 내", n_wb_bad == 0, fail_count=n_wb_bad)

    # =====================================================
    # 의무휴업일 검증 (v6: daily_sold_qty/daily_waste_qty 컬럼을 직접 사용)
    # =====================================================
    sc_join = store_calendar_df[["store_id", "date", "is_mandatory_closed"]].copy()
    sc_join["store_id"] = sc_join["store_id"].astype(str)
    sc_join["current_date"] = sc_join["date"].dt.strftime("%Y-%m-%d")
    sc_join = sc_join[["store_id", "current_date", "is_mandatory_closed"]]

    inv_with_closed = inventory_df.merge(sc_join, on=["store_id", "current_date"], how="left", validate="many_to_one")
    check("모든 행에 store_calendar.csv의 is_mandatory_closed 매핑이 존재", inv_with_closed["is_mandatory_closed"].notna().all())
    closed_rows_mask = inv_with_closed["is_mandatory_closed"] == 1

    mandatory_sold_sum = int(inv_with_closed.loc[closed_rows_mask, "daily_sold_qty"].sum())
    mandatory_waste_sum = int(inv_with_closed.loc[closed_rows_mask, "daily_waste_qty"].sum())
    mandatory_sale_event_count = int((closed_rows_mask & (inv_with_closed["daily_sold_qty"] > 0)).sum())
    mandatory_waste_event_count = int((closed_rows_mask & (inv_with_closed["daily_waste_qty"] > 0)).sum())

    check("의무휴업일 daily_sold_qty 합계 0", mandatory_sold_sum == 0, fail_count=mandatory_sold_sum)
    check("의무휴업일 daily_waste_qty 합계 0", mandatory_waste_sum == 0, fail_count=mandatory_waste_sum)
    check("의무휴업일 판매 발생(행) 0", mandatory_sale_event_count == 0, fail_count=mandatory_sale_event_count)
    check("의무휴업일 감모 발생(행) 0", mandatory_waste_event_count == 0, fail_count=mandatory_waste_event_count)

    # ---- 기존 LOT 재고 감소 0 (의무휴업일 current_stock_qty가 전날과 동일해야 함) ----
    sorted_with_closed = sorted_df.merge(sc_join, on=["store_id", "current_date"], how="left", validate="many_to_one")
    closed_sorted_mask = sorted_with_closed["is_mandatory_closed"] == 1
    # 그룹(LOT)의 두 번째 행부터(=전날 값이 실제로 존재하는 행만) 비교 대상으로 삼는다.
    has_prev_mask = grp.cumcount().gt(0).values
    stock_unchanged_check_mask = closed_sorted_mask & has_prev_mask
    n_closed_stock_change = int(
        (sorted_with_closed.loc[stock_unchanged_check_mask, "current_stock_qty"]
         != sorted_with_closed.loc[stock_unchanged_check_mask, "_prev_stock"]).sum()
    )
    check("의무휴업일 기존 LOT 재고 감소 0 (전날 재고와 동일)", n_closed_stock_change == 0, fail_count=n_closed_stock_change)

    _VALIDATION_STATS["mandatory_closed_sold_qty_sum"] = mandatory_sold_sum
    _VALIDATION_STATS["mandatory_closed_waste_qty_sum"] = mandatory_waste_sum

    cat_map = product_df.set_index("product_id")["category"]
    inv_with_closed["_category"] = inv_with_closed["product_id"].map(cat_map)
    _VALIDATION_STATS["category_sold_qty"] = inv_with_closed.groupby("_category")["daily_sold_qty"].sum()
    _VALIDATION_STATS["category_waste_qty"] = inv_with_closed.groupby("_category")["daily_waste_qty"].sum()

    # =====================================================
    # FEFO(First Expired, First Out) 판매 순서 검증 (내부 _FIFO_SALE_LOG 사용)
    # =====================================================
    if len(_FIFO_SALE_LOG) > 0:
        fifo_df = pd.DataFrame(_FIFO_SALE_LOG)
        fifo_df = fifo_df.sort_values(
            ["current_date", "store_id", "product_id", "expiry_date", "manufacture_date", "lot_id"]
        )
        grp_keys = ["current_date", "store_id", "product_id"]
        fifo_df["_leftover"] = (fifo_df["stock_after_sale"] > 0).astype(int)
        cum_leftover_inclusive = fifo_df.groupby(grp_keys)["_leftover"].cumsum()
        fifo_df["_prior_leftover_count"] = cum_leftover_inclusive - fifo_df["_leftover"]

        violation_mask = (fifo_df["sold_qty"] > 0) & (fifo_df["_prior_leftover_count"] > 0)
        violation_count = int(violation_mask.sum())
        if violation_count > 0:
            violation_examples = (
                fifo_df.loc[violation_mask, ["current_date", "store_id", "product_id", "lot_id"]]
                .head(10)
                .values.tolist()
            )
            print(f"\n[FEFO 위반 예시(최대 10개, date/store/product/lot_id)] {violation_examples}")
        check("FEFO 판매 순서(유통기한이 빠른 로트부터 소진) 위반 0", violation_count == 0, fail_count=violation_count)

        # 교차검증: _FIFO_SALE_LOG의 lot별 총 판매량이 CSV의 daily_sold_qty 합계와 일치하는지
        fifo_total_sold = int(fifo_df["sold_qty"].sum())
        csv_total_sold = int(inventory_df["daily_sold_qty"].sum())
        check(
            "내부 시뮬레이션 판매 로그 합계와 CSV daily_sold_qty 합계 일치(교차검증)",
            fifo_total_sold == csv_total_sold
        )
    else:
        violation_count = -1
        check("FEFO 판매 순서(유통기한이 빠른 로트부터 소진) 위반 0", False)
    _VALIDATION_STATS["fefo_violation_count"] = violation_count

    # =====================================================
    # 데이터 다양성 및 현실성 (WARN - 절대조건 아님)
    # =====================================================
    check_warn("discount_rate 다양성(모두 동일값 아님)", inventory_df["discount_rate"].nunique() > 1)
    first_date_per_lot = grp["_current_dt"].min()
    check_warn("시뮬레이션 기간 중 신규 입고(재입고) 로트가 발생함", int((first_date_per_lot > START_DATE).sum()) > 0)
    check_warn("SOLD_OUT 상태가 실제로 생성됨", sold_out_mask.any())
    check_warn("EXPIRED 상태가 실제로 생성됨", expired_mask.any())
    check_warn("DISCOUNT 상태가 실제로 생성됨", discount_mask.any())
    check_warn("의무휴업일이 실제로 1건 이상 존재함(검증 자체가 무의미해지지 않도록)", closed_rows_mask.any())

    # 참고 정보: 의무휴업일 폐기 유예로 인해 days_to_expiry<0인데도 아직 EXPIRED가
    # 아닌(NORMAL/DISCOUNT) 상태로 남아있는 행 수(정상적인 1일 한정 유예 상태).
    limbo_mask = (inventory_df["days_to_expiry"] < 0) & (inventory_df["inventory_status"].isin([STATUS_NORMAL, STATUS_DISCOUNT]))
    print(f"\n[참고] 의무휴업일로 폐기가 유예되어 days_to_expiry<0인데 NORMAL/DISCOUNT로 표시된 행 수: {int(limbo_mask.sum())} "
          f"(다음 영업일에 EXPIRED로 정리됨. 오류 아님)")

    print("\n" + "=" * 70)
    if all_passed:
        print("inventory.csv 검증 통과")
    else:
        print("inventory.csv 검증 실패 - 위 [FAIL] 항목을 확인해주세요.")
    print("=" * 70)

    return all_passed


# =========================================================
# 5. 요약 통계 출력 (검증 통과 후에만 호출)
# =========================================================
def print_summary_statistics(
    inventory_df: pd.DataFrame,
    store_df: pd.DataFrame,
    store_calendar_df: pd.DataFrame,
    saved_path: str,
) -> None:
    """
    validate_inventory()가 True를 반환한 뒤에만 호출되는 최종 요약 통계 출력 함수.
    총 판매수량/총 폐기수량은 반드시 daily_sold_qty/daily_waste_qty 컬럼 합계로
    계산한다("전날 재고-오늘 재고" 방식은 절대 사용하지 않는다).
    """
    print("\n" + "=" * 70)
    print("[최종 요약 통계]")
    print("=" * 70)

    sc_join = store_calendar_df[["store_id", "date", "is_mandatory_closed"]].copy()
    sc_join["store_id"] = sc_join["store_id"].astype(str)
    sc_join["current_date"] = sc_join["date"].dt.strftime("%Y-%m-%d")
    sc_join = sc_join[["store_id", "current_date", "is_mandatory_closed"]]
    inv_with_closed = inventory_df.merge(sc_join, on=["store_id", "current_date"], how="left", validate="many_to_one")
    closed_mask = inv_with_closed["is_mandatory_closed"] == 1

    print(f"shape: {inventory_df.shape}")
    print(f"기간: {inventory_df['current_date'].min()} ~ {inventory_df['current_date'].max()}")
    print(f"점포 수: {inventory_df['store_id'].nunique()}")
    print(f"상품 수: {inventory_df['product_id'].nunique()}")
    print(f"LOT 수(고유 lot_id): {inventory_df['lot_id'].nunique():,}")

    print(f"\n[중요] 아래 판매수량/폐기수량은 반드시 daily_sold_qty / daily_waste_qty 컬럼")
    print(f"합계이며, '전날 current_stock_qty - 오늘 current_stock_qty'로 계산한 값이 아닙니다.")
    print(f"(그 방식은 판매량에 감모/폐기량이 섞여 들어가므로 receipts.csv 등에서 절대 사용하지 마세요.)")
    print(f"총 입고수량(inbound_qty 합계): {int(inventory_df['inbound_qty'].sum()):,}")
    print(f"총 판매수량(daily_sold_qty 합계): {int(inventory_df['daily_sold_qty'].sum()):,}")
    print(f"총 폐기·감모수량(daily_waste_qty 합계): {int(inventory_df['daily_waste_qty'].sum()):,}")
    print(f"  - 이 중 유통기한 경과 폐기(waste_reason=EXPIRED): "
          f"{int(inventory_df.loc[inventory_df['waste_reason'] == WASTE_REASON_EXPIRED, 'daily_waste_qty'].sum()):,}")
    print(f"  - 이 중 자연감모(waste_reason=SHRINKAGE): "
          f"{int(inventory_df.loc[inventory_df['waste_reason'] == WASTE_REASON_SHRINKAGE, 'daily_waste_qty'].sum()):,}")

    print("\n상태별 행 수:")
    print(inventory_df["inventory_status"].value_counts())

    print(f"\n의무휴업일 수(점포x날짜 조합, store_calendar.csv 기준): {int(store_calendar_df['is_mandatory_closed'].sum()):,}")
    print(f"의무휴업일 판매수량(반드시 0): {int(inv_with_closed.loc[closed_mask, 'daily_sold_qty'].sum()):,}")
    print(f"의무휴업일 폐기수량(반드시 0): {int(inv_with_closed.loc[closed_mask, 'daily_waste_qty'].sum()):,}")

    print(f"\n저장 경로: {saved_path}")
    print("=" * 70)


# =========================================================
# 6. 저장
# =========================================================
def save_csv(df: pd.DataFrame, save_dir: str, filename: str) -> str:
    """
    utf-8-sig, index=False 로 CSV 저장 (기존 방식과 동일).
    저장 폴더 생성 실패, 쓰기 실패 등은 원인을 알 수 있는 메시지와 함께 즉시 오류로 처리한다.
    이 함수는 validate_inventory()가 True를 반환했을 때만 main()에서 호출되어야 한다.
    반환값: 실제로 저장된 파일의 전체 경로.
    """
    if df is None or len(df) == 0:
        raise ValueError("저장할 inventory 데이터가 비어 있습니다. CSV를 저장하지 않습니다.")

    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        raise OSError(f"저장 폴더를 생성할 수 없습니다: {save_dir}\n원인: {e}")

    full_path = os.path.join(save_dir, filename)
    try:
        df.to_csv(full_path, index=False, encoding="utf-8-sig")
    except OSError as e:
        raise OSError(f"CSV 저장에 실패했습니다: {full_path}\n원인: {e}")

    print(f"\n[저장 완료] {full_path}")
    return full_path


# =========================================================
# 7. main
# =========================================================
def _mount_google_drive_if_needed():
    """
    Google Colab 환경에서만 Google Drive를 마운트한다.
    이미(예: 다른 노트북 셀에서) 마운트되어 있으면 재마운트를 시도하지 않는다
    (중복 마운트로 인한 에러 방지). Colab이 아닌 환경(로컬 테스트 등)에서는
    조용히 건너뛴다.
    """
    try:
        from google.colab import drive  # type: ignore
    except ImportError:
        print("[안내] Google Colab 환경이 아닙니다(google.colab 모듈 없음). Drive 마운트를 건너뜁니다.")
        return

    if os.path.ismount("/content/drive"):
        print("[Google Drive] 이미 마운트되어 있습니다. 재마운트를 건너뜁니다.")
        return

    drive.mount("/content/drive")


def main():
    _mount_google_drive_if_needed()

    # ---- Random Seed 고정 (프로젝트 원칙, 재현성 보장) ----
    np.random.seed(RANDOM_SEED)

    # 1) 마스터 데이터 로드 + 사전 검증 (product.csv, store.csv, calendar.csv, store_calendar.csv)
    #    문제가 있으면 각 load_*() 함수 내부에서 어떤 파일의 어떤 문제인지 명확한
    #    오류 메시지와 함께 즉시 예외를 발생시켜 실행이 중단된다.
    product_df = load_product_data(PRODUCT_CSV_PATH)
    store_df = load_store_data(STORE_CSV_PATH)
    calendar_df = load_calendar_data(CALENDAR_CSV_PATH)
    store_calendar_df = load_store_calendar_data(STORE_CALENDAR_CSV_PATH, store_df, calendar_df)

    # 2) inventory 생성 (로트가 이어지는 1년치 시뮬레이션)
    inventory_df = generate_inventory_data(product_df, store_df, store_calendar_df)

    # 3) 검증
    passed = validate_inventory(inventory_df, product_df, store_df, calendar_df, store_calendar_df)

    # 4) 검증 통과 시에만 저장. 실패 시 저장하지 않고 sys.exit(1)로 종료한다.
    if not passed:
        print("\n" + "=" * 70)
        print("[검증 실패]")
        print("inventory.csv를 최종 저장하지 않았습니다.")
        print("FAIL 항목을 수정한 후 다시 실행하세요.")
        print("=" * 70)
        sys.exit(1)

    saved_path = save_csv(inventory_df, SAVE_DIR, OUTPUT_FILENAME)

    print("\n" + "=" * 70)
    print("[검증 통과]")
    print(f"inventory.csv 최종 저장 완료: {saved_path}")
    print("=" * 70)

    print_summary_statistics(inventory_df, store_df, store_calendar_df, saved_path)

    return inventory_df


if __name__ == "__main__":
    inventory_df = main()


# =========================================================
# 8. Colab 실행 예시 (참고용 주석 - 자동 실행되지 않음)
# =========================================================
#
# --- 실행 ---
# !python "/content/drive/MyDrive/빅프로젝트_데이터 최종/code/07_generate_inventory_data.py"
#
# --- 생성 결과 확인 ---
# import pandas as pd
#
# inventory_path = "/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터/inventory.csv"
# inventory_df = pd.read_csv(inventory_path, encoding="utf-8-sig")
#
# print(inventory_df.shape)
# display(inventory_df.head())
# print(inventory_df.dtypes)
# print(inventory_df["inventory_status"].value_counts(dropna=False))
# print(inventory_df.isnull().sum())
#
# --- receipts.csv를 만들 때는 반드시 daily_sold_qty만 사용 ---
# total_sales_qty = inventory_df["daily_sold_qty"].sum()      # 올바른 방법
# total_waste_qty = inventory_df["daily_waste_qty"].sum()     # 폐기/감모 집계
# # (금지) 전날 current_stock_qty - 오늘 current_stock_qty 로 판매량을 계산하지 말 것
#
# --- 로트 이력 확인 예시 (특정 lot_id 하나의 전체 일별 기록) ---
# sample_lot_id = inventory_df["lot_id"].iloc[0]
# print(inventory_df[inventory_df["lot_id"] == sample_lot_id]
#       .sort_values("current_date")
#       [["current_date", "inbound_qty", "daily_sold_qty", "daily_waste_qty",
#         "current_stock_qty", "discount_rate", "inventory_status", "freshness_score"]])
