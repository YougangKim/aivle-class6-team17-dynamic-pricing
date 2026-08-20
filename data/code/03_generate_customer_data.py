"""
customer.py

AI 기반 신선식품 수요예측 및 다이나믹 프라이싱 플랫폼
합성 고객 마스터 데이터(customer.csv) 생성 스크립트

이 파일은 visitor.csv / receipt.csv / transaction.csv 생성의 기준이 되는
고객 마스터 데이터를 생성한다.

Google Colab 실행 전제:
    이 스크립트는 Google Drive가 이미 마운트되어 있다고 가정한다.
    아래 코드를 이 스크립트 실행 전에 직접 실행해야 한다.

        from google.colab import drive
        drive.mount('/content/drive')

    이 파일 내부에서는 drive.mount()를 호출하거나 마운트 여부를 검사하지 않는다.

실행 방법:
    python customer.py
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd


# =========================================================
# 0. CONFIG
# =========================================================

# 생성할 고객 수 (유지보수 시 이 값만 수정하면 전체 규모가 변경됨)
NUM_CUSTOMERS: int = 10000

# 재현성을 위한 Random Seed
RANDOM_SEED: int = 42

# 저장 경로 및 파일명 (Google Drive 마운트는 사용자가 사전에 직접 수행함)
SAVE_DIR: str = "/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터/"
OUTPUT_FILENAME: str = "customer.csv"

# 최종 컬럼 순서 (고정)
COLUMN_ORDER: List[str] = [
    "customer_id",
    "age_group",
    "household_type",
    "income_level",
    "residence_type",
    "price_sensitivity",
    "freshness_sensitivity",
    "preferred_category",
    "visit_frequency",
]

# ---- ENUM 정의 ----
AGE_GROUPS: List[str] = ["20s", "30s", "40s", "50s", "60_plus"]
HOUSEHOLD_TYPES: List[str] = ["single", "couple", "family", "senior"]
INCOME_LEVELS: List[str] = ["low", "middle", "high"]
RESIDENCE_TYPES: List[str] = ["single_household", "apartment", "villa"]
CATEGORIES: List[str] = ["produce", "dairy", "meat", "cheese", "deli"]
VISIT_FREQUENCIES: List[str] = ["low", "medium", "high"]

# ---- 분포 정의 [가정] : 공공 통계자료 기반 근사치이며 정밀 실측값은 아님 ----

# age_group 전체 분포
AGE_GROUP_DIST: List[float] = [0.20, 0.25, 0.25, 0.20, 0.10]

# household_type | age_group 조건부 분포
HOUSEHOLD_BY_AGE: Dict[str, List[float]] = {
    "20s":     [0.55, 0.20, 0.20, 0.05],
    "30s":     [0.20, 0.25, 0.50, 0.05],
    "40s":     [0.10, 0.20, 0.65, 0.05],
    "50s":     [0.10, 0.35, 0.40, 0.15],
    "60_plus": [0.10, 0.30, 0.10, 0.50],
}

# income_level | age_group 조건부 분포
INCOME_BY_AGE: Dict[str, List[float]] = {
    "20s":     [0.50, 0.40, 0.10],
    "30s":     [0.25, 0.50, 0.25],
    "40s":     [0.20, 0.50, 0.30],
    "50s":     [0.20, 0.50, 0.30],
    "60_plus": [0.35, 0.50, 0.15],
}

# residence_type | household_type 조건부 분포
RESIDENCE_BY_HOUSEHOLD: Dict[str, List[float]] = {
    "single": [0.65, 0.25, 0.10],
    "couple": [0.20, 0.55, 0.25],
    "family": [0.05, 0.75, 0.20],
    "senior": [0.30, 0.40, 0.30],
}

# preferred_category | household_type 조건부 분포
# 카테고리 순서는 CATEGORIES = ["produce", "dairy", "meat", "cheese", "deli"] 순서와 일치해야 한다.
CATEGORY_BY_HOUSEHOLD: Dict[str, List[float]] = {
    "single": [0.20, 0.16, 0.17, 0.12, 0.35],
    "couple": [0.25, 0.20, 0.22, 0.15, 0.18],
    "family": [0.22, 0.25, 0.27, 0.16, 0.10],
    "senior": [0.35, 0.20, 0.18, 0.12, 0.15],
}

# visit_frequency | household_type 조건부 분포
# 값 순서는 VISIT_FREQUENCIES = ["low", "medium", "high"] 순서와 일치해야 한다.
# 의미: low = 월 1~2회 수준, medium = 월 3~5회 수준, high = 월 6~10회 수준
# (실제 방문 횟수/방문 날짜는 이 파일에서 생성하지 않으며, visitor.csv 생성 단계에서 사용한다.)
VISIT_FREQUENCY_BY_HOUSEHOLD: Dict[str, List[float]] = {
    "single": [0.25, 0.50, 0.25],
    "couple": [0.30, 0.50, 0.20],
    "family": [0.25, 0.55, 0.20],
    "senior": [0.40, 0.45, 0.15],
}

# price_sensitivity : Beta(6,5) 기반, 대부분 0.30~0.80 구간
PRICE_SENS_BETA_A: float = 6.0
PRICE_SENS_BETA_B: float = 5.0
PRICE_SENS_AGE_ADJ: Dict[str, float] = {
    "20s": 0.05, "30s": 0.00, "40s": -0.02, "50s": -0.03, "60_plus": -0.05,
}
PRICE_SENS_INCOME_ADJ: Dict[str, float] = {
    "low": 0.10, "middle": 0.00, "high": -0.10,
}

# freshness_sensitivity : Beta(8,3) 기반, 대부분 0.50~0.90 구간
FRESH_SENS_BETA_A: float = 8.0
FRESH_SENS_BETA_B: float = 3.0
FRESH_SENS_AGE_ADJ: Dict[str, float] = {
    "20s": -0.05, "30s": -0.02, "40s": 0.00, "50s": 0.03, "60_plus": 0.05,
}
FRESH_SENS_INCOME_ADJ: Dict[str, float] = {
    "low": -0.05, "middle": 0.00, "high": 0.05,
}
FRESH_SENS_HOUSEHOLD_ADJ: Dict[str, float] = {
    "single": -0.03, "couple": 0.00, "family": 0.03, "senior": 0.05,
}


# =========================================================
# 1. Helper 함수
# =========================================================

def make_customer_id(index: int) -> str:
    """
    1부터 시작하는 정수 index를 받아 CUS000001 형식의 고객 ID를 생성한다.

    Args:
        index: 1부터 시작하는 순번

    Returns:
        CUS로 시작하는 6자리 zero-padded 고객 ID 문자열
    """
    if index < 1:
        raise ValueError(f"customer index는 1 이상이어야 합니다: {index}")
    return f"CUS{index:06d}"


def validate_probability_table(
    table: Dict[str, Sequence[float]],
    name: str,
    expected_length: int,
) -> None:
    """
    확률 테이블의 각 확률 리스트에 대해 아래 항목을 모두 검증한다.

        - 확률 리스트 길이가 expected_length와 같은지
        - 모든 값이 숫자로 변환 가능한지
        - NaN이 없는지
        - 무한대(+inf/-inf)가 없는지
        - 음수 확률이 없는지
        - 확률 합이 1.0인지

    Args:
        table: {그룹명: 확률리스트} 형태의 딕셔너리
        name: 오류 메시지에 사용할 테이블 이름
        expected_length: 각 확률 리스트가 가져야 할 길이 (카테고리 개수)

    Raises:
        ValueError: 위 검증 항목 중 하나라도 위반한 경우, 어떤 테이블의
                    어떤 key가 문제인지 명시하여 예외를 발생시킨다.
    """
    for key, probs in table.items():
        # 1) 길이 검증
        if len(probs) != expected_length:
            raise ValueError(
                f"[{name}] '{key}' 항목의 확률 리스트 길이가 올바르지 않습니다. "
                f"기대 길이={expected_length}, 실제 길이={len(probs)}"
            )

        # 2) 숫자 변환 가능 여부 검증
        try:
            probs_arr = np.array([float(p) for p in probs], dtype=float)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"[{name}] '{key}' 항목에 숫자로 변환할 수 없는 값이 있습니다: {probs} ({e})"
            ) from e

        # 3) NaN 검증
        if np.isnan(probs_arr).any():
            raise ValueError(f"[{name}] '{key}' 항목에 NaN 값이 존재합니다: {probs}")

        # 4) 무한대 검증
        if np.isinf(probs_arr).any():
            raise ValueError(f"[{name}] '{key}' 항목에 무한대 값이 존재합니다: {probs}")

        # 5) 음수 확률 검증
        if (probs_arr < 0).any():
            raise ValueError(f"[{name}] '{key}' 항목에 음수 확률이 존재합니다: {probs}")

        # 6) 확률 합 검증
        total = float(probs_arr.sum())
        if not np.isclose(total, 1.0, atol=1e-6):
            raise ValueError(
                f"[{name}] '{key}' 항목의 확률 합이 1.0이 아닙니다 (합={total})."
            )


def validate_distribution_keys(
    actual_keys: Sequence[str],
    expected_keys: Sequence[str],
    name: str,
) -> None:
    """
    조건부 확률표의 key 집합이 기대하는 상위 그룹 목록과 정확히 일치하는지 검증한다.

    Args:
        actual_keys: 조건부 확률표에 실제로 정의된 key 목록 (예: dict.keys())
        expected_keys: 반드시 존재해야 하는 key 목록 (예: HOUSEHOLD_TYPES)
        name: 오류 메시지에 사용할 테이블 이름

    Raises:
        ValueError: key가 누락되었거나 불필요한 key가 추가된 경우
    """
    actual_set = set(actual_keys)
    expected_set = set(expected_keys)
    missing = expected_set - actual_set
    extra = actual_set - expected_set

    if missing or extra:
        detail_msgs = []
        if missing:
            detail_msgs.append(f"누락된 key: {sorted(missing)}")
        if extra:
            detail_msgs.append(f"허용되지 않는 추가 key: {sorted(extra)}")
        raise ValueError(
            f"[{name}] 조건부 분포의 key 집합이 올바르지 않습니다. " + " / ".join(detail_msgs)
        )


def choice_by_conditional_group(
    rng: np.random.Generator,
    group_array: np.ndarray,
    dist_map: Dict[str, Sequence[float]],
    categories: Sequence[str],
) -> np.ndarray:
    """
    상위 그룹값(group_array)에 따라 서로 다른 확률분포를 적용하여
    하위 카테고리를 조건부로 샘플링한다.

    Args:
        rng: numpy Generator 객체 (재현성을 위해 seed 고정된 것을 사용)
        group_array: 상위 그룹값 배열 (예: age_group, household_type)
        dist_map: {상위그룹값: 하위카테고리 확률리스트}
        categories: 하위 카테고리 전체 목록 (dist_map의 확률리스트와 순서 일치)

    Returns:
        group_array와 동일한 길이의 하위 카테고리 샘플링 결과 배열
    """
    result = np.empty(len(group_array), dtype=object)
    for key, probs in dist_map.items():
        mask = group_array == key
        n = int(mask.sum())
        if n > 0:
            result[mask] = rng.choice(categories, size=n, p=probs)

    if pd.isnull(result).any():
        missing_keys = set(np.unique(group_array)) - set(dist_map.keys())
        raise ValueError(
            f"조건부 분포 테이블에 정의되지 않은 그룹값이 존재합니다: {missing_keys}"
        )
    return result


def clip_and_round(values: np.ndarray, low: float = 0.0, high: float = 1.0, digits: int = 2) -> np.ndarray:
    """
    배열 값을 [low, high] 범위로 clip 하고 소수점 digits 자리로 반올림한다.

    Args:
        values: 원본 float 배열
        low: 최소 허용값
        high: 최대 허용값
        digits: 반올림 자릿수

    Returns:
        clip 및 반올림이 적용된 float 배열
    """
    clipped = np.clip(values, low, high)
    return np.round(clipped, digits)


# =========================================================
# 2. 고객 생성 함수
# =========================================================

def generate_customers(num_customers: int, seed: int) -> pd.DataFrame:
    """
    합성 고객 마스터 데이터를 생성한다.

    생성 로직:
        1. age_group을 전체 분포(AGE_GROUP_DIST)에서 샘플링
        2. household_type, income_level을 age_group에 조건부로 샘플링
        3. residence_type을 household_type에 조건부로 샘플링
        4. price_sensitivity를 Beta(6,5) 분포 + age/income 보정으로 생성
        5. freshness_sensitivity를 Beta(8,3) 분포 + age/income/household 보정으로 생성
           (price_sensitivity와 freshness_sensitivity는 서로를 직접 수식으로
            연결하지 않는다. 다만 소득 수준(income_level)에 대한 보정 방향이
            서로 반대이므로 - low income은 price_sensitivity를 높이고
            freshness_sensitivity를 낮추며, high income은 그 반대임 -
            두 값 사이에 약한 음의 상관관계가 공통요인을 통해 자연스럽게
            나타날 수 있다. 이는 의도적으로 설계된 직접 상관관계가 아니다.)
        6. preferred_category를 household_type에 조건부로 샘플링
           (CATEGORY_BY_HOUSEHOLD)
        7. visit_frequency를 household_type에 조건부로 샘플링
           (VISIT_FREQUENCY_BY_HOUSEHOLD)

    Args:
        num_customers: 생성할 고객 수
        seed: 재현성을 위한 random seed

    Returns:
        COLUMN_ORDER 순서를 따르는 고객 마스터 DataFrame
    """
    if num_customers <= 0:
        raise ValueError(f"num_customers는 1 이상이어야 합니다: {num_customers}")

    # ---- 확률 테이블 사전 검증 (길이 / 숫자 변환 / NaN / 무한대 / 음수 / 합계) ----
    validate_probability_table({"ALL": AGE_GROUP_DIST}, "AGE_GROUP_DIST", len(AGE_GROUPS))
    validate_probability_table(HOUSEHOLD_BY_AGE, "HOUSEHOLD_BY_AGE", len(HOUSEHOLD_TYPES))
    validate_probability_table(INCOME_BY_AGE, "INCOME_BY_AGE", len(INCOME_LEVELS))
    validate_probability_table(RESIDENCE_BY_HOUSEHOLD, "RESIDENCE_BY_HOUSEHOLD", len(RESIDENCE_TYPES))
    validate_probability_table(CATEGORY_BY_HOUSEHOLD, "CATEGORY_BY_HOUSEHOLD", len(CATEGORIES))
    validate_probability_table(
        VISIT_FREQUENCY_BY_HOUSEHOLD, "VISIT_FREQUENCY_BY_HOUSEHOLD", len(VISIT_FREQUENCIES)
    )

    # ---- 조건부 분포 key 집합 검증 (누락 / 추가 key 확인) ----
    validate_distribution_keys(HOUSEHOLD_BY_AGE.keys(), AGE_GROUPS, "HOUSEHOLD_BY_AGE")
    validate_distribution_keys(INCOME_BY_AGE.keys(), AGE_GROUPS, "INCOME_BY_AGE")
    validate_distribution_keys(RESIDENCE_BY_HOUSEHOLD.keys(), HOUSEHOLD_TYPES, "RESIDENCE_BY_HOUSEHOLD")
    validate_distribution_keys(CATEGORY_BY_HOUSEHOLD.keys(), HOUSEHOLD_TYPES, "CATEGORY_BY_HOUSEHOLD")
    validate_distribution_keys(
        VISIT_FREQUENCY_BY_HOUSEHOLD.keys(), HOUSEHOLD_TYPES, "VISIT_FREQUENCY_BY_HOUSEHOLD"
    )

    rng = np.random.default_rng(seed)

    # 1) customer_id : 순차 생성
    customer_id = np.array(
        [make_customer_id(i) for i in range(1, num_customers + 1)], dtype=object
    )

    # 2) age_group : 전체 분포에서 샘플링
    age_group = rng.choice(AGE_GROUPS, size=num_customers, p=AGE_GROUP_DIST)

    # 3) household_type : age_group 조건부 샘플링
    household_type = choice_by_conditional_group(
        rng, age_group, HOUSEHOLD_BY_AGE, HOUSEHOLD_TYPES
    )

    # 4) income_level : age_group 조건부 샘플링
    income_level = choice_by_conditional_group(
        rng, age_group, INCOME_BY_AGE, INCOME_LEVELS
    )

    # 5) residence_type : household_type 조건부 샘플링
    residence_type = choice_by_conditional_group(
        rng, household_type, RESIDENCE_BY_HOUSEHOLD, RESIDENCE_TYPES
    )

    # 6) price_sensitivity : Beta 분포 기반 + age/income 보정 [가정]
    price_base = rng.beta(PRICE_SENS_BETA_A, PRICE_SENS_BETA_B, size=num_customers)
    price_adj = np.array(
        [
            PRICE_SENS_AGE_ADJ[a] + PRICE_SENS_INCOME_ADJ[i]
            for a, i in zip(age_group, income_level)
        ]
    )
    price_sensitivity = clip_and_round(price_base + price_adj)

    # 7) freshness_sensitivity : Beta 분포 기반 + age/income/household 보정 [가정]
    fresh_base = rng.beta(FRESH_SENS_BETA_A, FRESH_SENS_BETA_B, size=num_customers)
    fresh_adj = np.array(
        [
            FRESH_SENS_AGE_ADJ[a]
            + FRESH_SENS_INCOME_ADJ[i]
            + FRESH_SENS_HOUSEHOLD_ADJ[h]
            for a, i, h in zip(age_group, income_level, household_type)
        ]
    )
    freshness_sensitivity = clip_and_round(fresh_base + fresh_adj)

    # 8) preferred_category : household_type 조건부 샘플링
    preferred_category = choice_by_conditional_group(
        rng,
        household_type,
        CATEGORY_BY_HOUSEHOLD,
        CATEGORIES,
    )

    # 9) visit_frequency : household_type 조건부 샘플링
    visit_frequency = choice_by_conditional_group(
        rng,
        household_type,
        VISIT_FREQUENCY_BY_HOUSEHOLD,
        VISIT_FREQUENCIES,
    )

    df = pd.DataFrame(
        {
            "customer_id": customer_id,
            "age_group": age_group,
            "household_type": household_type,
            "income_level": income_level,
            "residence_type": residence_type,
            "price_sensitivity": price_sensitivity.astype(float),
            "freshness_sensitivity": freshness_sensitivity.astype(float),
            "preferred_category": preferred_category,
            "visit_frequency": visit_frequency,
        }
    )

    # 문자열 컬럼 공백 제거
    string_columns = [
        "customer_id",
        "age_group",
        "household_type",
        "income_level",
        "residence_type",
        "preferred_category",
        "visit_frequency",
    ]
    for col in string_columns:
        df[col] = df[col].astype(str).str.strip()

    # 컬럼 순서 고정
    df = df[COLUMN_ORDER]

    return df


# =========================================================
# 3. Validation 및 결과 요약 함수
# =========================================================

def validate_customers(df: pd.DataFrame, num_customers: int) -> bool:
    """
    생성된 고객 DataFrame에 대해 전체 품질 검증을 수행한다.
    검증에 실패하면 오류 목록을 출력하고 False를 반환한다.

    검증 항목:
        - 컬럼 순서
        - 행 개수 (NUM_CUSTOMERS와 일치 여부)
        - 결측치
        - customer_id 중복
        - customer_id 형식
        - customer_id 순차성 (CUS000001부터 순서대로 생성되었는지)
        - ENUM 검사 (age_group, household_type, income_level,
          residence_type, preferred_category, visit_frequency)
        - price_sensitivity / freshness_sensitivity 범위, dtype, NaN,
          무한대, 소수점 둘째 자리 초과 여부
        - 문자열 컬럼의 빈 문자열 / 공백 전용 문자열 / 앞뒤 공백 잔존 여부

    Args:
        df: 검증 대상 DataFrame
        num_customers: 기대하는 행 개수 (NUM_CUSTOMERS)

    Returns:
        모든 검증을 통과하면 True, 하나라도 실패하면 False
    """
    errors: List[str] = []

    # ---- 컬럼 순서 검증 ----
    if list(df.columns) != COLUMN_ORDER:
        errors.append(
            f"컬럼 순서가 일치하지 않습니다.\n  기대값: {COLUMN_ORDER}\n  실제값: {list(df.columns)}"
        )

    # ---- 행 개수 검증 ----
    if len(df) != num_customers:
        errors.append(f"행 개수가 일치하지 않습니다. 기대값={num_customers}, 실제값={len(df)}")

    # ---- 결측치 검증 ----
    null_counts = df.isnull().sum()
    if null_counts.any():
        errors.append(f"결측치가 존재합니다:\n{null_counts[null_counts > 0]}")

    # ---- customer_id 중복 검증 ----
    if "customer_id" in df.columns and df["customer_id"].duplicated().any():
        dup_count = int(df["customer_id"].duplicated().sum())
        errors.append(f"customer_id 중복이 {dup_count}건 존재합니다.")

    # ---- customer_id 형식 검증 ----
    if "customer_id" in df.columns:
        id_pattern = re.compile(r"^CUS\d{6}$")
        invalid_ids = df.loc[~df["customer_id"].astype(str).str.match(id_pattern), "customer_id"]
        if len(invalid_ids) > 0:
            errors.append(
                f"customer_id 형식이 올바르지 않은 값이 {len(invalid_ids)}건 존재합니다. "
                f"예시: {invalid_ids.head(3).tolist()}"
            )

    # ---- customer_id 순차성 검증 ----
    if "customer_id" in df.columns:
        expected_ids = [make_customer_id(i) for i in range(1, num_customers + 1)]
        actual_ids = df["customer_id"].tolist()
        if actual_ids != expected_ids:
            first_expected = expected_ids[0] if expected_ids else None
            last_expected = expected_ids[-1] if expected_ids else None
            first_actual = actual_ids[0] if actual_ids else None
            last_actual = actual_ids[-1] if actual_ids else None
            errors.append(
                "customer_id가 CUS000001부터 순차적으로 생성되지 않았습니다. "
                f"(기대 첫값={first_expected}, 실제 첫값={first_actual}, "
                f"기대 마지막값={last_expected}, 실제 마지막값={last_actual})"
            )

    # ---- ENUM 검증 ----
    enum_checks = {
        "age_group": AGE_GROUPS,
        "household_type": HOUSEHOLD_TYPES,
        "income_level": INCOME_LEVELS,
        "residence_type": RESIDENCE_TYPES,
        "preferred_category": CATEGORIES,
        "visit_frequency": VISIT_FREQUENCIES,
    }
    for col, allowed_values in enum_checks.items():
        if col not in df.columns:
            errors.append(f"'{col}' 컬럼이 존재하지 않습니다.")
            continue
        invalid_mask = ~df[col].isin(allowed_values)
        if invalid_mask.any():
            invalid_values = df.loc[invalid_mask, col].unique().tolist()
            errors.append(f"'{col}' 컬럼에 허용되지 않는 값이 존재합니다: {invalid_values}")

    # ---- price_sensitivity / freshness_sensitivity 검증 ----
    for col in ["price_sensitivity", "freshness_sensitivity"]:
        if col not in df.columns:
            errors.append(f"'{col}' 컬럼이 존재하지 않습니다.")
            continue

        # dtype 검증
        if not pd.api.types.is_float_dtype(df[col]):
            errors.append(f"'{col}' 컬럼의 dtype이 float가 아닙니다. 실제 dtype={df[col].dtype}")
            continue

        col_values = df[col].to_numpy(dtype=float)

        # NaN 검증
        nan_count = int(np.isnan(col_values).sum())
        if nan_count > 0:
            errors.append(f"'{col}' 컬럼에 NaN 값이 {nan_count}건 존재합니다.")

        # 무한대 검증
        inf_count = int(np.isinf(col_values).sum())
        if inf_count > 0:
            errors.append(f"'{col}' 컬럼에 양의/음의 무한대 값이 {inf_count}건 존재합니다.")

        # 범위 검증 (0.00 ~ 1.00)
        finite_values = col_values[np.isfinite(col_values)]
        out_of_range = (finite_values < 0.0) | (finite_values > 1.0)
        if out_of_range.any():
            errors.append(
                f"'{col}' 컬럼에 0.00~1.00 범위를 벗어난 값이 {int(out_of_range.sum())}건 존재합니다."
            )

        # 소수점 둘째 자리 초과 검증
        rounded_values = np.round(finite_values, 2)
        precision_violation = ~np.isclose(finite_values, rounded_values, atol=1e-9)
        if precision_violation.any():
            errors.append(
                f"'{col}' 컬럼에 소수점 둘째 자리를 초과하는 값이 {int(precision_violation.sum())}건 존재합니다."
            )

    # ---- 문자열 공백 검증 ----
    string_columns_to_check = [
        "customer_id",
        "age_group",
        "household_type",
        "income_level",
        "residence_type",
        "preferred_category",
        "visit_frequency",
    ]
    for col in string_columns_to_check:
        if col not in df.columns:
            continue
        series = df[col].astype(str)
        stripped = series.str.strip()

        empty_mask = series == ""
        if empty_mask.any():
            errors.append(f"'{col}' 컬럼에 빈 문자열이 {int(empty_mask.sum())}건 존재합니다.")

        whitespace_only_mask = (stripped == "") & (~empty_mask)
        if whitespace_only_mask.any():
            errors.append(
                f"'{col}' 컬럼에 공백만 있는 문자열이 {int(whitespace_only_mask.sum())}건 존재합니다."
            )

        untrimmed_mask = series != stripped
        if untrimmed_mask.any():
            errors.append(
                f"'{col}' 컬럼에 앞뒤 공백이 남아 있는 값이 {int(untrimmed_mask.sum())}건 존재합니다."
            )

    # ---- 결과 출력 ----
    if errors:
        print("=" * 60)
        print("VALIDATION RESULT: FAIL")
        print("=" * 60)
        for i, err in enumerate(errors, start=1):
            print(f"[{i}] {err}")
        return False

    print("=" * 60)
    print("VALIDATION RESULT: PASS")
    print("=" * 60)
    return True


def print_generation_summary(df: pd.DataFrame) -> None:
    """
    Validation을 통과한 고객 데이터의 생성 결과를 요약 출력한다.
    전체 10,000행을 출력하지 않고 통계 요약 정보만 출력한다.

    출력 항목:
        - DataFrame shape
        - 컬럼별 dtype
        - ENUM 컬럼별 값 건수 및 비율
        - price_sensitivity 기술통계
        - freshness_sensitivity 기술통계
        - 두 민감도 컬럼 간 상관계수
        - customer_id 첫 번째 값과 마지막 값

    Args:
        df: 요약할 고객 DataFrame (Validation을 통과한 상태여야 함)
    """
    print("=" * 60)
    print("고객 데이터 생성 결과 요약")
    print("=" * 60)

    print("-" * 60)
    print("[1] DataFrame Shape")
    print(df.shape)

    print("-" * 60)
    print("[2] 컬럼별 dtype")
    print(df.dtypes)

    enum_columns = [
        "age_group",
        "household_type",
        "income_level",
        "residence_type",
        "preferred_category",
        "visit_frequency",
    ]
    print("-" * 60)
    print("[3] ENUM 컬럼별 값 건수 및 비율")
    for col in enum_columns:
        print(f"--- {col} ---")
        counts = df[col].value_counts()
        ratios = df[col].value_counts(normalize=True).round(4)
        summary = pd.DataFrame({"count": counts, "ratio": ratios})
        print(summary)

    print("-" * 60)
    print("[4] price_sensitivity 기술통계")
    print(df["price_sensitivity"].describe())

    print("-" * 60)
    print("[5] freshness_sensitivity 기술통계")
    print(df["freshness_sensitivity"].describe())

    print("-" * 60)
    print("[6] price_sensitivity와 freshness_sensitivity 간 상관계수")
    corr = df["price_sensitivity"].corr(df["freshness_sensitivity"])
    print(f"corr = {corr:.4f}")

    print("-" * 60)
    print("[7] customer_id 확인")
    print(f"첫 번째 customer_id: {df['customer_id'].iloc[0]}")
    print(f"마지막 customer_id: {df['customer_id'].iloc[-1]}")
    print("=" * 60)


# =========================================================
# 4. Save 함수
# =========================================================

def save_customers(df: pd.DataFrame, save_dir: str, filename: str) -> str:
    """
    검증을 통과한 DataFrame을 CSV 파일로 저장한다. (UTF-8-SIG 인코딩)

    이 함수는 Google Drive 마운트 여부를 검사하지 않는다.
    Google Drive는 이 스크립트 실행 전에 사용자가 직접 마운트한 상태여야 한다.

    Args:
        df: 저장할 DataFrame
        save_dir: 저장할 디렉토리 경로
        filename: 저장할 파일명

    Returns:
        저장된 파일의 전체 경로

    Raises:
        OSError: 디렉토리 생성 또는 파일 저장에 실패한 경우
    """
    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        raise OSError(f"저장 디렉토리 생성에 실패했습니다: {save_dir} ({e})") from e

    full_path = os.path.join(save_dir, filename)

    try:
        df.to_csv(full_path, index=False, encoding="utf-8-sig")
    except OSError as e:
        raise OSError(f"CSV 저장에 실패했습니다: {full_path} ({e})") from e

    return full_path


# =========================================================
# 5. main()
# =========================================================

def main() -> None:
    """
    customer.csv 생성 파이프라인 전체를 실행한다.

    1. 설정값 및 확률표 검증 (generate_customers 내부에서 수행)
    2. 고객 10,000명 생성
    3. DataFrame 전체 Validation
    4. Validation 실패 시 CSV 저장하지 않고 종료
    5. Validation 통과 시 생성 결과 요약 출력
    6. 지정된 Google Drive 경로에 customer.csv 저장
    7. 저장 경로와 총 행 수 출력
    """
    print(f"고객 데이터 생성을 시작합니다. (NUM_CUSTOMERS={NUM_CUSTOMERS}, RANDOM_SEED={RANDOM_SEED})")

    try:
        df = generate_customers(NUM_CUSTOMERS, RANDOM_SEED)
    except Exception as e:
        print(f"[ERROR] 고객 데이터 생성 중 오류가 발생했습니다: {e}")
        sys.exit(1)

    is_valid = validate_customers(df, NUM_CUSTOMERS)

    if not is_valid:
        print("[ERROR] Validation에 실패하여 CSV를 저장하지 않습니다.")
        sys.exit(1)

    print_generation_summary(df)

    try:
        saved_path = save_customers(df, SAVE_DIR, OUTPUT_FILENAME)
    except OSError as e:
        print(f"[ERROR] 파일 저장 중 오류가 발생했습니다: {e}")
        sys.exit(1)

    print(f"customer.csv 저장 완료: {saved_path}")
    print(f"총 {len(df)}행 생성됨.")


if __name__ == "__main__":
    main()
