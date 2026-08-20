# -*- coding: utf-8 -*-
"""
08_generate_visitor_data.py

[프로젝트] AI 신선식품 수요예측 및 다이나믹 프라이싱 플랫폼 (KT AIVLE School 빅프로젝트)
[단계]     5단계 - 합성데이터 생성 (visitor.csv)
[목적]     매장·날짜·시간대·고객 특성에 따라 방문 기록(visitor.csv)을 생성한다.
           이후 receipt.csv, transaction.csv 생성의 기준 데이터가 된다.

이 스크립트는 Google Colab에서 그대로 실행 가능한 완성형 코드이다.

절대 하지 않는 것
- customer.csv / store.csv / calendar.csv / store_calendar.csv /
  store_visitor_profile.csv / inventory.csv 의 내용·구조 변경
- inventory 재고 차감
- product 배정 (구매 상품 결정)
- receipt / transaction 생성
- 의무휴업일 방문 생성
- seafood 카테고리 사용
"""

from __future__ import annotations

import os
import sys
import random
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------
# Google Colab 환경에서 Google Drive 마운트 (Colab이 아닌 환경에서는 무시된다)
# ------------------------------------------------------------------------------------
try:
    from google.colab import drive  # type: ignore

    if not os.path.ismount("/content/drive"):
        drive.mount("/content/drive")
except ImportError:
    # Colab이 아닌 로컬/서버 환경에서는 무시하고 진행한다.
    pass


# ======================================================================================
# 0. 경로 및 CONFIG (합성 데이터 생성을 위한 명시적 가정값)
# ======================================================================================

BASE_DIR = "/content/drive/MyDrive/빅프로젝트_데이터 최종"
INPUT_DIR = BASE_DIR + "/2_생성데이터"
OUTPUT_DIR = BASE_DIR + "/2_생성데이터"

INPUT_FILES = {
    "store": "store.csv",
    "calendar": "calendar.csv",
    "store_calendar": "store_calendar.csv",
    "store_visitor_profile": "store_visitor_profile.csv",
    "customer": "customer.csv",
    "inventory": "inventory.csv",
}

OUTPUT_FILE_NAME = "visitor.csv"

# 재현성을 위한 랜덤 시드 고정
RANDOM_SEED = 42

# 대상 상품 카테고리 (참고용. visitor.csv 생성에는 직접 사용하지 않는다)
TARGET_CATEGORIES = ["produce", "dairy", "meat", "cheese", "deli"]

# ---- [가정] 고객 visit_frequency별 주당 평균 방문 횟수 ------------------------------
# 근거: [가정] (프로젝트 합성데이터 생성을 위한 명시적 가정값)
WEEKLY_VISIT_RATE: Dict[str, float] = {
    "low": 0.5,
    "medium": 1.2,
    "high": 2.2,
}

# ---- [가정] day_type별 방문 날짜 기본 가중치 ----------------------------------------
DAY_TYPE_WEIGHT: Dict[str, float] = {
    "weekday": 1.00,
    "weekend": 1.15,
    "holiday": 1.10,
}

# ---- [가정] residence_type별 area_type 선호 가중치 ----------------------------------
RESIDENCE_AREA_WEIGHT: Dict[str, Dict[str, float]] = {
    "apartment": {"residential": 1.50, "mixed": 1.20, "office": 0.70},
    "single_household": {"residential": 1.10, "mixed": 1.40, "office": 1.00},
    "townhouse": {"residential": 1.50, "mixed": 1.10, "office": 0.60},
    "villa": {"residential": 1.50, "mixed": 1.10, "office": 0.60},
}

# 검증 허용 오차
VISITOR_RATIO_TOLERANCE = 1e-6

# visitor_id 형식
VISITOR_ID_PREFIX = "VIS"
VISITOR_ID_DIGITS = 8

# 최종 출력 컬럼 순서
OUTPUT_COLUMNS = [
    "visitor_id",
    "customer_id",
    "store_id",
    "visit_date",
    "visit_time",
    "time_slot",
    "day_type",
    "visit_sequence",
]

# 필수 입력 컬럼 정의 (실제 CSV 컬럼명과 다르면 여기서 즉시 오류가 발생한다)
REQUIRED_COLUMNS = {
    "store": ["store_id", "area_type", "floating_idx"],
    "calendar": ["date", "day_type", "event_index", "season_index"],
    "store_calendar": ["store_id", "date", "is_open", "open_hour", "close_hour"],
    "store_visitor_profile": [
        "area_type",
        "day_type",
        "close_hour",
        "time_slot",
        "start_hour",
        "end_hour",
        "visitor_ratio",
    ],
    "customer": ["customer_id", "residence_type", "visit_frequency"],
    "inventory": ["current_date", "store_id"],
}


# ======================================================================================
# 1. 입력 데이터 로드
# ======================================================================================

def load_input_data(input_dir: str) -> Dict[str, pd.DataFrame]:
    """등록된 6개의 입력 CSV 파일을 읽어 DataFrame 딕셔너리로 반환한다.

    Args:
        input_dir: store.csv, calendar.csv 등이 저장된 폴더 경로.

    Returns:
        파일 키(store, calendar, store_calendar, store_visitor_profile,
        customer, inventory)를 key로, 로드한 DataFrame을 value로 갖는 딕셔너리.

    Raises:
        FileNotFoundError: 입력 파일이 폴더에 존재하지 않는 경우.
    """
    data: Dict[str, pd.DataFrame] = {}
    for key, file_name in INPUT_FILES.items():
        file_path = os.path.join(input_dir, file_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"[입력 파일 누락] '{file_name}' 파일을 찾을 수 없습니다. "
                f"경로를 확인하세요: {file_path}"
            )
        data[key] = pd.read_csv(file_path)
        print(f"[로드 완료] {file_name}  shape={data[key].shape}")
    return data


# ======================================================================================
# 2. 입력 데이터 검증
# ======================================================================================

def validate_input_data(data: Dict[str, pd.DataFrame]) -> None:
    """입력 CSV들의 스키마와 핵심 규칙을 검증한다.

    검증 항목:
        1) 파일별 필수 컬럼 존재 여부
        2) customer.residence_type 값이 RESIDENCE_AREA_WEIGHT 정의 범위 내인지
        3) customer.visit_frequency 값이 WEEKLY_VISIT_RATE 정의 범위 내인지
        4) calendar.day_type 값이 DAY_TYPE_WEIGHT 정의 범위 내인지
        5) store.area_type 값이 RESIDENCE_AREA_WEIGHT의 area_type 목록에 포함되는지
        6) store_visitor_profile의 (area_type, day_type, close_hour) 그룹별
           visitor_ratio 합계가 1.0인지 (허용 오차 1e-6)

    Args:
        data: load_input_data()가 반환한 DataFrame 딕셔너리.

    Raises:
        ValueError: 위 검증 항목 중 하나라도 실패한 경우.
    """
    # (1) 필수 컬럼 검증
    for key, required_cols in REQUIRED_COLUMNS.items():
        df = data[key]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"[스키마 오류] '{INPUT_FILES[key]}' 파일에 필수 컬럼이 없습니다: "
                f"{missing}. 실제 컬럼: {list(df.columns)}"
            )

    customer_df = data["customer"]
    store_df = data["store"]
    calendar_df = data["calendar"]
    profile_df = data["store_visitor_profile"]

    # (2) residence_type ENUM 검증
    unknown_residence = set(customer_df["residence_type"].dropna().unique()) - set(
        RESIDENCE_AREA_WEIGHT.keys()
    )
    if unknown_residence:
        raise ValueError(
            "[ENUM 오류] customer.csv의 residence_type에 정의되지 않은 값이 있습니다: "
            f"{sorted(unknown_residence)}. "
            f"CONFIG의 RESIDENCE_AREA_WEIGHT에 정의된 값만 허용됩니다: "
            f"{sorted(RESIDENCE_AREA_WEIGHT.keys())}. "
            "새로운 residence_type을 임의로 처리하지 않고 오류를 발생시킵니다."
        )

    # (3) visit_frequency ENUM 검증
    unknown_freq = set(customer_df["visit_frequency"].dropna().unique()) - set(
        WEEKLY_VISIT_RATE.keys()
    )
    if unknown_freq:
        raise ValueError(
            "[ENUM 오류] customer.csv의 visit_frequency에 정의되지 않은 값이 있습니다: "
            f"{sorted(unknown_freq)}. "
            f"CONFIG의 WEEKLY_VISIT_RATE에 정의된 값만 허용됩니다: "
            f"{sorted(WEEKLY_VISIT_RATE.keys())}."
        )

    # (4) day_type ENUM 검증
    unknown_day_type = set(calendar_df["day_type"].dropna().unique()) - set(
        DAY_TYPE_WEIGHT.keys()
    )
    if unknown_day_type:
        raise ValueError(
            "[ENUM 오류] calendar.csv의 day_type에 정의되지 않은 값이 있습니다: "
            f"{sorted(unknown_day_type)}. "
            f"허용되는 값: {sorted(DAY_TYPE_WEIGHT.keys())}."
        )

    # (5) store.area_type이 RESIDENCE_AREA_WEIGHT 매핑에 존재하는지 검증
    allowed_area_types = set()
    for mapping in RESIDENCE_AREA_WEIGHT.values():
        allowed_area_types.update(mapping.keys())
    unknown_area_type = set(store_df["area_type"].dropna().unique()) - allowed_area_types
    if unknown_area_type:
        raise ValueError(
            "[ENUM 오류] store.csv의 area_type에 정의되지 않은 값이 있습니다: "
            f"{sorted(unknown_area_type)}. "
            f"CONFIG의 RESIDENCE_AREA_WEIGHT에서 다루는 area_type만 허용됩니다: "
            f"{sorted(allowed_area_types)}."
        )

    # (6) store_visitor_profile의 visitor_ratio 그룹 합계 검증
    group_cols = ["area_type", "day_type", "close_hour"]
    ratio_sum = profile_df.groupby(group_cols)["visitor_ratio"].sum()
    bad_groups = ratio_sum[(ratio_sum - 1.0).abs() > VISITOR_RATIO_TOLERANCE]
    if len(bad_groups) > 0:
        raise ValueError(
            "[비율 오류] store_visitor_profile.csv에서 area_type x day_type x "
            "close_hour 그룹별 visitor_ratio 합계가 1.0이 아닙니다 "
            f"(허용 오차 {VISITOR_RATIO_TOLERANCE}).\n"
            f"문제 그룹:\n{bad_groups.to_string()}"
        )

    print("[검증 완료] 입력 데이터 스키마 및 ENUM/비율 검증을 통과했습니다.")


# ======================================================================================
# 3. 시뮬레이션 기간(달력) 구성
# ======================================================================================

def build_simulation_calendar(
    calendar_df: pd.DataFrame, inventory_df: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    """시뮬레이션 시작일/종료일을 계산하고 해당 구간의 calendar만 추출한다.

    시작일 = inventory.csv의 current_date 최솟값
    종료일 = calendar.csv의 date 최댓값

    Args:
        calendar_df: calendar.csv DataFrame (date 컬럼이 datetime으로 변환되어 있어야 함).
        inventory_df: inventory.csv DataFrame (current_date 컬럼이 datetime으로 변환되어 있어야 함).

    Returns:
        (simulation_calendar, simulation_start, simulation_end) 튜플.
        simulation_calendar는 date 오름차순으로 정렬된 DataFrame이다.

    Raises:
        ValueError: simulation_start가 simulation_end보다 늦은 경우.
    """
    simulation_start = inventory_df["current_date"].min()
    simulation_end = calendar_df["date"].max()

    if pd.isna(simulation_start) or pd.isna(simulation_end):
        raise ValueError(
            "[기간 오류] inventory.csv의 current_date 또는 calendar.csv의 date에 "
            "유효하지 않은(NaT) 값이 있어 시뮬레이션 기간을 계산할 수 없습니다."
        )

    if simulation_start > simulation_end:
        raise ValueError(
            f"[기간 오류] 시뮬레이션 시작일({simulation_start.date()})이 "
            f"종료일({simulation_end.date()})보다 늦습니다."
        )

    simulation_calendar = (
        calendar_df[
            (calendar_df["date"] >= simulation_start)
            & (calendar_df["date"] <= simulation_end)
        ]
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )

    if simulation_calendar.empty:
        raise ValueError(
            "[기간 오류] calendar.csv에서 시뮬레이션 기간"
            f"({simulation_start.date()} ~ {simulation_end.date()})에 해당하는 "
            "행을 찾을 수 없습니다."
        )

    print(
        f"[시뮬레이션 기간] {simulation_start.date()} ~ {simulation_end.date()} "
        f"({len(simulation_calendar)}일)"
    )
    return simulation_calendar, simulation_start, simulation_end


# ======================================================================================
# 4. 고객별 방문 횟수 생성 (Poisson)
# ======================================================================================

def generate_customer_visit_counts(
    customer_df: pd.DataFrame, simulation_days: int, rng: np.random.Generator
) -> pd.DataFrame:
    """customer.csv의 visit_frequency를 이용해 고객별 방문 횟수를 생성한다.

    expected_visits = weekly_visit_rate * simulation_days / 7
    visit_count ~ Poisson(expected_visits), 단 simulation_days를 초과할 수 없다.

    Args:
        customer_df: customer.csv DataFrame (customer_id, residence_type, visit_frequency 포함).
        simulation_days: 시뮬레이션 총 일수.
        rng: numpy 난수 생성기.

    Returns:
        customer_id, residence_type, visit_frequency, expected_visits, visit_count
        컬럼을 가진 DataFrame.
    """
    result = customer_df[["customer_id", "residence_type", "visit_frequency"]].copy()
    result["weekly_visit_rate"] = result["visit_frequency"].map(WEEKLY_VISIT_RATE)
    result["expected_visits"] = result["weekly_visit_rate"] * simulation_days / 7.0

    visit_counts = rng.poisson(result["expected_visits"].to_numpy())
    visit_counts = np.minimum(visit_counts, simulation_days)  # 기간 일수 초과 방지
    result["visit_count"] = visit_counts.astype(int)

    print(
        "[방문 횟수 생성] 고객 수="
        f"{len(result)}, 평균 기대 방문 횟수={result['expected_visits'].mean():.3f}, "
        f"평균 생성 방문 횟수={result['visit_count'].mean():.3f}"
    )
    return result


# ======================================================================================
# 5. 방문 날짜 선택
# ======================================================================================

def select_visit_date(
    eligible_dates: np.ndarray,
    date_weights: np.ndarray,
    visit_count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """고객 1명에 대해 중복되지 않는 방문 날짜를 가중치 기반으로 선택한다.

    Args:
        eligible_dates: 방문 가능한(가중치 > 0) 날짜 배열.
        date_weights: eligible_dates와 1:1 대응하는 정규화된 확률(합계 1.0).
        visit_count: 이 고객에게 배정된 목표 방문 횟수.
        rng: numpy 난수 생성기.

    Returns:
        선택된 날짜 배열 (중복 없음). eligible_dates가 부족하면 그 개수만큼만 반환한다.
    """
    n = min(visit_count, len(eligible_dates))
    if n <= 0:
        return np.array([], dtype=eligible_dates.dtype)
    return rng.choice(eligible_dates, size=n, replace=False, p=date_weights)


# ======================================================================================
# 6. 매장 선택
# ======================================================================================

def select_store(
    open_stores: Dict[str, Tuple[float, float]],
    store_weights_static: Dict[str, float],
    rng: np.random.Generator,
) -> Optional[str]:
    """해당 날짜에 영업 중인 매장 중 고객의 residence_type 가중치를 반영해 하나를 선택한다.

    Args:
        open_stores: {store_id: (open_hour, close_hour)} 형태의 해당 날짜 영업 매장 정보.
        store_weights_static: {store_id: residence_area_weight * floating_idx} 매장별 정적 가중치.
        rng: numpy 난수 생성기.

    Returns:
        선택된 store_id. 후보 매장이 없거나 가중치 합이 0이면 None을 반환한다.
    """
    if not open_stores:
        return None

    store_ids = list(open_stores.keys())
    weights = np.array([store_weights_static.get(s, 0.0) for s in store_ids], dtype=float)
    total = weights.sum()
    if total <= 0:
        return None

    probs = weights / total
    return rng.choice(store_ids, p=probs)


# ======================================================================================
# 7. time_slot 선택
# ======================================================================================

def select_time_slot(
    profile_lookup: Dict[Tuple[str, str, float], List[Tuple[str, float, float, float]]],
    area_type: str,
    day_type: str,
    close_hour: float,
    open_hour: float,
    rng: np.random.Generator,
) -> Optional[Tuple[str, float, float]]:
    """store_visitor_profile.csv 기준으로 time_slot을 선택한다.

    조인 키: area_type, day_type, close_hour (store_calendar 기준)
    선택 확률: visitor_ratio (단, open_hour/close_hour로 잘려 유효 구간이 없는
    time_slot은 후보에서 제외하고 나머지 확률을 재정규화한다.)

    Args:
        profile_lookup: (area_type, day_type, close_hour) -> [(time_slot, start_hour,
            end_hour, visitor_ratio), ...] 형태의 사전 계산된 조회 테이블.
        area_type: 매장의 area_type.
        day_type: 방문일의 day_type.
        close_hour: 방문일 store_calendar의 close_hour.
        open_hour: 방문일 store_calendar의 open_hour.
        rng: numpy 난수 생성기.

    Returns:
        (time_slot, effective_start, effective_end) 튜플. 유효한 time_slot이
        없으면 None을 반환한다.

    Raises:
        ValueError: area_type/day_type/close_hour 조합에 매칭되는 profile 행이
            store_visitor_profile.csv에 전혀 존재하지 않는 경우.
    """
    key = (area_type, day_type, round(float(close_hour), 2))
    candidates = profile_lookup.get(key)
    if not candidates:
        raise ValueError(
            "[time_slot 매칭 오류] store_visitor_profile.csv에 "
            f"area_type='{area_type}', day_type='{day_type}', "
            f"close_hour={close_hour} 조합이 존재하지 않습니다."
        )

    valid: List[Tuple[str, float, float, float]] = []
    for time_slot, start_hour, end_hour, visitor_ratio in candidates:
        effective_start = max(start_hour, open_hour)
        effective_end = min(end_hour, close_hour)
        if effective_start < effective_end:
            valid.append((time_slot, effective_start, effective_end, visitor_ratio))

    if not valid:
        return None

    ratios = np.array([v[3] for v in valid], dtype=float)
    ratios = ratios / ratios.sum()
    idx = rng.choice(len(valid), p=ratios)
    time_slot, effective_start, effective_end, _ = valid[idx]
    return time_slot, effective_start, effective_end


# ======================================================================================
# 8. 방문 시각 생성
# ======================================================================================

def generate_visit_time(
    effective_start: float, effective_end: float, rng: np.random.Generator
) -> str:
    """유효 구간 [effective_start, effective_end) 내에서 초 단위 방문 시각을 생성한다.

    Args:
        effective_start: 방문 가능 시작 시각(시 단위, 예: 9.0).
        effective_end: 방문 가능 종료 시각(시 단위, 배타적, 예: 21.0).
        rng: numpy 난수 생성기.

    Returns:
        "HH:MM:SS" 형식의 방문 시각 문자열. 종료 시각 정각은 포함하지 않는다.

    Raises:
        ValueError: effective_start >= effective_end 인 경우.
    """
    start_sec = int(round(effective_start * 3600))
    end_sec = int(round(effective_end * 3600))
    if start_sec >= end_sec:
        raise ValueError(
            f"[시각 생성 오류] 유효 구간이 비어 있습니다: start={effective_start}, "
            f"end={effective_end}."
        )
    chosen_sec = int(rng.integers(start_sec, end_sec))  # end_sec는 배타적
    hh = chosen_sec // 3600
    mm = (chosen_sec % 3600) // 60
    ss = chosen_sec % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


# ======================================================================================
# 9. 방문 데이터 생성 (메인 시뮬레이션 루프)
# ======================================================================================

def generate_visitor_data(
    customer_visits_df: pd.DataFrame,
    simulation_calendar: pd.DataFrame,
    store_df: pd.DataFrame,
    store_calendar_df: pd.DataFrame,
    profile_df: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """고객별 방문 횟수를 바탕으로 방문 날짜·매장·time_slot·시각을 생성한다.

    카테시안 조인 없이, 고객별로 필요한 방문 건수만큼만 샘플링하여
    list of dict에 누적한 뒤 마지막에 한 번에 DataFrame으로 변환한다
    (customer 10,000명 x 날짜 100여일 x 매장 소수 개의 전체 조합을 만들지 않는다).

    Args:
        customer_visits_df: generate_customer_visit_counts()의 결과.
        simulation_calendar: build_simulation_calendar()의 결과.
        store_df: store.csv DataFrame.
        store_calendar_df: store_calendar.csv DataFrame.
        profile_df: store_visitor_profile.csv DataFrame.
        rng: numpy 난수 생성기.

    Returns:
        visitor_id, visit_sequence를 제외한 방문 원시 레코드로 구성된 DataFrame
        (customer_id, store_id, visit_date, visit_time, time_slot, day_type).
    """
    # ---- 사전 계산 테이블 -------------------------------------------------------
    store_area_type = store_df.set_index("store_id")["area_type"].to_dict()
    store_floating_idx = store_df.set_index("store_id")["floating_idx"].to_dict()

    calendar_indexed = simulation_calendar.set_index("date")
    day_type_by_date = calendar_indexed["day_type"].to_dict()
    date_weight_base = (
        calendar_indexed["event_index"]
        * calendar_indexed["season_index"]
        * calendar_indexed["day_type"].map(DAY_TYPE_WEIGHT)
    ).to_dict()

    sim_start = simulation_calendar["date"].min()
    sim_end = simulation_calendar["date"].max()

    sc = store_calendar_df[
        (store_calendar_df["date"] >= sim_start) & (store_calendar_df["date"] <= sim_end)
    ].copy()
    sc_open = sc[
        (sc["is_open"] == 1) & sc["open_hour"].notna() & sc["close_hour"].notna()
    ]

    # date -> {store_id: (open_hour, close_hour)}
    date_open_stores: Dict[pd.Timestamp, Dict[str, Tuple[float, float]]] = {}
    for row in sc_open.itertuples(index=False):
        date_open_stores.setdefault(row.date, {})[row.store_id] = (
            float(row.open_hour),
            float(row.close_hour),
        )

    # profile_lookup: (area_type, day_type, close_hour) -> [(time_slot, start, end, ratio), ...]
    profile_lookup: Dict[Tuple[str, str, float], List[Tuple[str, float, float, float]]] = {}
    for row in profile_df.itertuples(index=False):
        key = (row.area_type, row.day_type, round(float(row.close_hour), 2))
        profile_lookup.setdefault(key, []).append(
            (row.time_slot, float(row.start_hour), float(row.end_hour), float(row.visitor_ratio))
        )

    # residence_type별 매장 정적 가중치: residence_area_weight(area_type) * floating_idx
    store_weight_static_by_residence: Dict[str, Dict[str, float]] = {}
    for residence_type, area_pref in RESIDENCE_AREA_WEIGHT.items():
        weights: Dict[str, float] = {}
        for store_id, area_type in store_area_type.items():
            weights[store_id] = area_pref.get(area_type, 0.0) * float(
                store_floating_idx[store_id]
            )
        store_weight_static_by_residence[residence_type] = weights

    all_dates = simulation_calendar["date"].tolist()

    # residence_type별 방문 가능 날짜(가중치>0)와 정규화된 확률을 미리 계산
    eligible_dates_by_residence: Dict[str, np.ndarray] = {}
    eligible_weights_by_residence: Dict[str, np.ndarray] = {}
    for residence_type in RESIDENCE_AREA_WEIGHT.keys():
        store_weights = store_weight_static_by_residence[residence_type]
        date_list = []
        weight_list = []
        for d in all_dates:
            open_stores_d = date_open_stores.get(d, {})
            if not open_stores_d:
                continue
            store_weight_sum = sum(store_weights.get(s, 0.0) for s in open_stores_d)
            w = date_weight_base.get(d, 0.0) * store_weight_sum
            if w > 0:
                date_list.append(d)
                weight_list.append(w)
        date_arr = np.array(date_list, dtype=object)
        weight_arr = np.array(weight_list, dtype=float)
        if weight_arr.sum() > 0:
            weight_arr = weight_arr / weight_arr.sum()
        eligible_dates_by_residence[residence_type] = date_arr
        eligible_weights_by_residence[residence_type] = weight_arr

    # ---- 고객별 방문 레코드 생성 -------------------------------------------------
    records: List[dict] = []
    skipped_no_eligible_date = 0
    skipped_no_store = 0
    skipped_no_time_slot = 0

    for row in customer_visits_df.itertuples(index=False):
        customer_id = row.customer_id
        residence_type = row.residence_type
        visit_count = int(row.visit_count)
        if visit_count <= 0:
            continue

        eligible_dates = eligible_dates_by_residence[residence_type]
        eligible_weights = eligible_weights_by_residence[residence_type]
        if len(eligible_dates) == 0:
            skipped_no_eligible_date += 1
            continue

        chosen_dates = select_visit_date(eligible_dates, eligible_weights, visit_count, rng)

        store_weights = store_weight_static_by_residence[residence_type]

        for visit_date in chosen_dates:
            open_stores_d = date_open_stores.get(visit_date, {})
            store_id = select_store(open_stores_d, store_weights, rng)
            if store_id is None:
                skipped_no_store += 1
                continue

            open_hour, close_hour = open_stores_d[store_id]
            area_type = store_area_type[store_id]
            day_type = day_type_by_date[visit_date]

            slot_result = select_time_slot(
                profile_lookup, area_type, day_type, close_hour, open_hour, rng
            )
            if slot_result is None:
                skipped_no_time_slot += 1
                continue

            time_slot, effective_start, effective_end = slot_result
            visit_time = generate_visit_time(effective_start, effective_end, rng)

            records.append(
                {
                    "customer_id": customer_id,
                    "store_id": store_id,
                    "visit_date": pd.Timestamp(visit_date).strftime("%Y-%m-%d"),
                    "visit_time": visit_time,
                    "time_slot": time_slot,
                    "day_type": day_type,
                }
            )

    print(
        "[생성 스킵 통계] 방문 가능 날짜 없음="
        f"{skipped_no_eligible_date}명, 매장 선택 실패={skipped_no_store}건, "
        f"time_slot 없음={skipped_no_time_slot}건"
    )

    if not records:
        raise ValueError(
            "[생성 오류] 생성된 방문 레코드가 하나도 없습니다. CONFIG 가중치 또는 "
            "입력 데이터(store_calendar, store_visitor_profile)를 확인하세요."
        )

    visitor_df = pd.DataFrame.from_records(records)
    print(f"[방문 레코드 생성 완료] 총 {len(visitor_df)}건")
    return visitor_df


# ======================================================================================
# 10. 정렬, visit_sequence, visitor_id 부여
# ======================================================================================

def assign_visit_sequence_and_id(visitor_df: pd.DataFrame) -> pd.DataFrame:
    """전체 방문 기록을 날짜·시간순으로 정렬하고 visit_sequence, visitor_id를 부여한다.

    Args:
        visitor_df: generate_visitor_data()의 결과 (customer_id, store_id, visit_date,
            visit_time, time_slot, day_type 컬럼 포함).

    Returns:
        OUTPUT_COLUMNS 순서로 정렬된 최종 visitor DataFrame.
    """
    df = visitor_df.copy()

    # 날짜/시간 순 정렬을 위한 보조 정렬키 (visit_date, visit_time은 문자열이지만
    # 형식이 YYYY-MM-DD, HH:MM:SS로 고정되어 있어 문자열 정렬 = 시간 순 정렬과 동일하다)
    df = df.sort_values(["visit_date", "visit_time"], kind="mergesort").reset_index(
        drop=True
    )

    # customer별 visit_sequence: 전체가 날짜·시간순으로 정렬되어 있으므로
    # groupby.cumcount()가 곧 고객별 시간순 방문 순서가 된다.
    df["visit_sequence"] = df.groupby("customer_id").cumcount() + 1

    # visitor_id 부여 (정렬된 순서 기준 VIS00000001 ...)
    df["visitor_id"] = [
        f"{VISITOR_ID_PREFIX}{i + 1:0{VISITOR_ID_DIGITS}d}" for i in range(len(df))
    ]

    return df[OUTPUT_COLUMNS].reset_index(drop=True)


# ======================================================================================
# 11. 최종 visitor.csv 검증
# ======================================================================================

def validate_visitor_data(
    visitor_df: pd.DataFrame,
    data: Dict[str, pd.DataFrame],
    simulation_start: pd.Timestamp,
    simulation_end: pd.Timestamp,
) -> None:
    """생성된 visitor.csv를 스키마/FK/날짜/영업여부/시간/중복/시퀀스/분포 기준으로 검증한다.

    Args:
        visitor_df: assign_visit_sequence_and_id()의 결과.
        data: load_input_data()가 반환한 원본 입력 DataFrame 딕셔너리.
        simulation_start: 시뮬레이션 시작일.
        simulation_end: 시뮬레이션 종료일.

    Raises:
        ValueError: 검증 항목 중 하나라도 실패한 경우.
    """
    customer_df = data["customer"]
    store_df = data["store"]
    calendar_df = data["calendar"]
    store_calendar_df = data["store_calendar"]
    profile_df = data["store_visitor_profile"]

    # ---- A. 스키마 --------------------------------------------------------------
    if list(visitor_df.columns) != OUTPUT_COLUMNS:
        raise ValueError(
            f"[검증 실패-스키마] 컬럼명 또는 순서가 다릅니다.\n"
            f"기대값: {OUTPUT_COLUMNS}\n실제값: {list(visitor_df.columns)}"
        )

    dup_id_count = visitor_df["visitor_id"].duplicated().sum()
    if dup_id_count > 0:
        raise ValueError(f"[검증 실패-스키마] visitor_id 중복이 {dup_id_count}건 있습니다.")

    invalid_id_mask = ~visitor_df["visitor_id"].astype(str).str.match(r"^VIS\d{8}$")
    if invalid_id_mask.any():
        raise ValueError(
            f"[검증 실패-스키마] visitor_id 형식(^VIS\\d{{8}}$)에 맞지 않는 값이 "
            f"{invalid_id_mask.sum()}건 있습니다."
        )

    if visitor_df[OUTPUT_COLUMNS].isna().any().any():
        na_counts = visitor_df[OUTPUT_COLUMNS].isna().sum()
        raise ValueError(
            f"[검증 실패-스키마] 필수 컬럼에 결측치가 있습니다.\n{na_counts[na_counts > 0]}"
        )

    str_cols = ["visitor_id", "customer_id", "store_id", "visit_date", "visit_time",
                "time_slot", "day_type"]
    for col in str_cols:
        blank_count = (visitor_df[col].astype(str).str.strip() == "").sum()
        if blank_count > 0:
            raise ValueError(f"[검증 실패-스키마] '{col}' 컬럼에 공백값이 {blank_count}건 있습니다.")

    # ---- B. FK --------------------------------------------------------------
    valid_customer_ids = set(customer_df["customer_id"])
    bad_customer = ~visitor_df["customer_id"].isin(valid_customer_ids)
    if bad_customer.any():
        raise ValueError(
            f"[검증 실패-FK] customer.csv에 존재하지 않는 customer_id가 "
            f"{bad_customer.sum()}건 있습니다."
        )

    valid_store_ids = set(store_df["store_id"])
    bad_store = ~visitor_df["store_id"].isin(valid_store_ids)
    if bad_store.any():
        raise ValueError(
            f"[검증 실패-FK] store.csv에 존재하지 않는 store_id가 {bad_store.sum()}건 있습니다."
        )

    valid_calendar_dates = set(calendar_df["date"].dt.strftime("%Y-%m-%d"))
    bad_calendar_date = ~visitor_df["visit_date"].isin(valid_calendar_dates)
    if bad_calendar_date.any():
        raise ValueError(
            f"[검증 실패-FK] calendar.csv에 존재하지 않는 visit_date가 "
            f"{bad_calendar_date.sum()}건 있습니다."
        )

    sc_key = set(
        zip(
            store_calendar_df["store_id"],
            store_calendar_df["date"].dt.strftime("%Y-%m-%d"),
        )
    )
    visitor_sc_key = list(zip(visitor_df["store_id"], visitor_df["visit_date"]))
    bad_sc_key = [k for k in visitor_sc_key if k not in sc_key]
    if bad_sc_key:
        raise ValueError(
            f"[검증 실패-FK] store_id + visit_date 조합이 store_calendar.csv에 없는 "
            f"방문이 {len(bad_sc_key)}건 있습니다. 예시: {bad_sc_key[:5]}"
        )

    # ---- C. 날짜 --------------------------------------------------------------
    visit_date_ts = pd.to_datetime(visitor_df["visit_date"])
    if (visit_date_ts < simulation_start).any():
        raise ValueError(
            f"[검증 실패-날짜] 시뮬레이션 시작일({simulation_start.date()}) 이전의 "
            "방문 데이터가 존재합니다."
        )
    if (visit_date_ts > simulation_end).any():
        raise ValueError(
            f"[검증 실패-날짜] 시뮬레이션 종료일({simulation_end.date()}) 이후의 "
            "방문 데이터가 존재합니다."
        )

    # ---- D. 영업 여부 --------------------------------------------------------------
    sc_lookup = store_calendar_df.set_index(
        [store_calendar_df["store_id"], store_calendar_df["date"].dt.strftime("%Y-%m-%d")]
    )
    sc_is_open = sc_lookup["is_open"]
    sc_open_hour = sc_lookup["open_hour"]
    sc_close_hour = sc_lookup["close_hour"]

    visitor_index = pd.MultiIndex.from_arrays(
        [visitor_df["store_id"], visitor_df["visit_date"]]
    )
    matched_is_open = sc_is_open.reindex(visitor_index)
    if (matched_is_open != 1).any():
        bad_count = (matched_is_open != 1).sum()
        raise ValueError(
            f"[검증 실패-영업여부] is_open != 1 인 날짜에 방문이 {bad_count}건 생성되었습니다 "
            "(의무휴업일 방문 포함 가능)."
        )

    matched_open_hour = sc_open_hour.reindex(visitor_index)
    matched_close_hour = sc_close_hour.reindex(visitor_index)
    if matched_open_hour.isna().any() or matched_close_hour.isna().any():
        raise ValueError(
            "[검증 실패-영업여부] open_hour 또는 close_hour가 결측인 날짜에 방문이 "
            "생성되었습니다."
        )

    # ---- E. 방문 시간 --------------------------------------------------------------
    visit_time_sec = pd.to_timedelta(visitor_df["visit_time"]).dt.total_seconds()
    open_sec = matched_open_hour.to_numpy(dtype=float) * 3600
    close_sec = matched_close_hour.to_numpy(dtype=float) * 3600
    visit_time_sec_np = visit_time_sec.to_numpy()

    if (visit_time_sec_np < open_sec).any() or (visit_time_sec_np >= close_sec).any():
        raise ValueError(
            "[검증 실패-방문시간] visit_time이 매장 영업시간(open_hour ~ close_hour 미만) "
            "범위를 벗어난 방문이 있습니다."
        )

    # ---- F. time_slot --------------------------------------------------------------
    store_area_type = store_df.set_index("store_id")["area_type"]
    visitor_area_type = visitor_df["store_id"].map(store_area_type)

    profile_check_df = visitor_df.copy()
    profile_check_df["area_type"] = visitor_area_type
    profile_check_df["close_hour_rounded"] = matched_close_hour.round(2).to_numpy()

    profile_df_rounded = profile_df.copy()
    profile_df_rounded["close_hour_rounded"] = profile_df_rounded["close_hour"].round(2)
    valid_profile_keys = set(
        zip(
            profile_df_rounded["area_type"],
            profile_df_rounded["day_type"],
            profile_df_rounded["close_hour_rounded"],
            profile_df_rounded["time_slot"],
        )
    )
    visitor_profile_keys = list(
        zip(
            profile_check_df["area_type"],
            profile_check_df["day_type"],
            profile_check_df["close_hour_rounded"],
            profile_check_df["time_slot"],
        )
    )
    bad_profile_keys = [k for k in visitor_profile_keys if k not in valid_profile_keys]
    if bad_profile_keys:
        raise ValueError(
            "[검증 실패-time_slot] area_type + day_type + close_hour + time_slot 조합이 "
            f"store_visitor_profile.csv에 없는 방문이 {len(bad_profile_keys)}건 있습니다. "
            f"예시: {bad_profile_keys[:5]}"
        )

    # start_hour / end_hour 범위 검증
    # time_slot별 start_hour/end_hour 매핑 (area_type, day_type, close_hour, time_slot) -> (start, end)
    slot_range_lookup: Dict[Tuple, Tuple[float, float]] = {}
    for row in profile_df_rounded.itertuples(index=False):
        key = (row.area_type, row.day_type, row.close_hour_rounded, row.time_slot)
        slot_range_lookup[key] = (float(row.start_hour), float(row.end_hour))

    slot_starts = []
    slot_ends = []
    for key in visitor_profile_keys:
        s, e = slot_range_lookup[key]
        slot_starts.append(s)
        slot_ends.append(e)
    slot_start_sec = np.array(slot_starts) * 3600
    slot_end_sec = np.array(slot_ends) * 3600

    # 유효 구간은 max(slot_start, open)~min(slot_end, close) 이므로 실제 방문시각은
    # slot_start 이상, slot_end 미만이어야 한다 (유효구간이 이 범위의 부분집합이므로).
    if (visit_time_sec_np < slot_start_sec).any() or (
        visit_time_sec_np >= slot_end_sec
    ).any():
        raise ValueError(
            "[검증 실패-time_slot] visit_time이 배정된 time_slot의 start_hour ~ "
            "end_hour(미만) 범위를 벗어난 방문이 있습니다."
        )

    # ---- G. 중복 --------------------------------------------------------------
    dup_customer_date = visitor_df.duplicated(subset=["customer_id", "visit_date"]).sum()
    if dup_customer_date > 0:
        raise ValueError(
            f"[검증 실패-중복] 동일 customer_id + visit_date 중복이 {dup_customer_date}건 "
            "있습니다."
        )

    dup_full_row = visitor_df.duplicated().sum()
    if dup_full_row > 0:
        raise ValueError(f"[검증 실패-중복] 완전히 동일한 방문 행이 {dup_full_row}건 있습니다.")

    # ---- H. visit_sequence --------------------------------------------------------------
    seq_by_customer = visitor_df.groupby("customer_id")["visit_sequence"]
    if (seq_by_customer.min() != 1).any():
        raise ValueError("[검증 실패-visit_sequence] 고객별 최소 visit_sequence가 1이 아닙니다.")

    def _is_consecutive(s: pd.Series) -> bool:
        sorted_vals = np.sort(s.to_numpy())
        return bool(np.array_equal(sorted_vals, np.arange(1, len(sorted_vals) + 1)))

    if not seq_by_customer.apply(_is_consecutive).all():
        raise ValueError(
            "[검증 실패-visit_sequence] 고객별 visit_sequence가 1부터 연속된 정수가 "
            "아닙니다."
        )

    check_df = visitor_df.copy()
    check_df["_dt_key"] = check_df["visit_date"] + " " + check_df["visit_time"]
    order_check = (
        check_df.sort_values(["customer_id", "visit_sequence"])
        .groupby("customer_id")["_dt_key"]
        .apply(lambda s: s.is_monotonic_increasing)
    )
    if not order_check.all():
        raise ValueError(
            "[검증 실패-visit_sequence] 고객별 날짜·시간 순서와 visit_sequence 순서가 "
            "일치하지 않는 고객이 있습니다."
        )

    print("[검증 통과] visitor.csv 스키마 / FK / 날짜 / 영업여부 / 시간 / time_slot / "
          "중복 / visit_sequence 검증을 모두 통과했습니다.")

    # ---- I. 논리 분포 및 14) visit_frequency 순서 검증 -----------------------------
    _print_distribution_and_check_order(visitor_df, customer_df, store_calendar_df)


def _print_distribution_and_check_order(
    visitor_df: pd.DataFrame, customer_df: pd.DataFrame, store_calendar_df: pd.DataFrame
) -> None:
    """논리 분포를 출력하고 visit_frequency별 평균 방문 횟수 순서(low<medium<high)를 검증한다."""
    print("\n[논리 분포 확인]")
    print(f"- 전체 행 수: {len(visitor_df)}")
    print(f"- 기간: {visitor_df['visit_date'].min()} ~ {visitor_df['visit_date'].max()}")
    print(f"- 고객 수(customer.csv 전체): {customer_df['customer_id'].nunique()}")
    print(f"- 실제 방문 고객 수: {visitor_df['customer_id'].nunique()}")

    visits_per_customer_all = (
        visitor_df.groupby("customer_id").size().reindex(customer_df["customer_id"], fill_value=0)
    )
    print(f"- 고객당 평균 방문 횟수(0건 포함): {visits_per_customer_all.mean():.4f}")

    freq_map = customer_df.set_index("customer_id")["visit_frequency"]
    visits_with_freq = pd.DataFrame(
        {"visit_count": visits_per_customer_all, "visit_frequency": freq_map}
    )
    freq_avg = visits_with_freq.groupby("visit_frequency")["visit_count"].mean()
    print("- visit_frequency별 고객당 평균 방문 횟수(0건 포함):")
    print(freq_avg.to_string())

    print("- 매장별 방문 수:")
    print(visitor_df["store_id"].value_counts().to_string())

    day_type_counts = visitor_df["day_type"].value_counts()
    day_type_ratio = (day_type_counts / len(visitor_df) * 100).round(2)
    print("- day_type별 방문 수 및 비율(%):")
    print(pd.DataFrame({"count": day_type_counts, "ratio(%)": day_type_ratio}).to_string())

    slot_counts = visitor_df["time_slot"].value_counts()
    slot_ratio = (slot_counts / len(visitor_df) * 100).round(2)
    print("- time_slot별 방문 수 및 비율(%):")
    print(pd.DataFrame({"count": slot_counts, "ratio(%)": slot_ratio}).to_string())

    daily_counts = visitor_df.groupby("visit_date").size()
    print(
        f"- 날짜별 방문 수: 최소={daily_counts.min()}, 평균={daily_counts.mean():.2f}, "
        f"최대={daily_counts.max()}"
    )

    print("- 매장 x day_type별 방문 수:")
    print(visitor_df.groupby(["store_id", "day_type"]).size().to_string())

    closed_dates = set(
        zip(
            store_calendar_df.loc[store_calendar_df["is_open"] != 1, "store_id"],
            store_calendar_df.loc[store_calendar_df["is_open"] != 1, "date"].dt.strftime(
                "%Y-%m-%d"
            ),
        )
    )
    visitor_keys = list(zip(visitor_df["store_id"], visitor_df["visit_date"]))
    closed_visit_count = sum(1 for k in visitor_keys if k in closed_dates)
    print(f"- 휴업일 방문 수: {closed_visit_count}")

    # 14. visit_frequency별 평균 방문 횟수 순서 검증 (low < medium < high)
    required_order = ["low", "medium", "high"]
    if not all(level in freq_avg.index for level in required_order):
        raise ValueError(
            "[검증 실패-분포순서] visit_frequency 평균 계산 결과에 low/medium/high 중 "
            f"일부가 없습니다. 존재하는 값: {list(freq_avg.index)}"
        )
    low_avg, medium_avg, high_avg = (
        freq_avg["low"],
        freq_avg["medium"],
        freq_avg["high"],
    )
    if not (low_avg < medium_avg < high_avg):
        raise ValueError(
            "[검증 실패-분포순서] visit_frequency별 평균 방문 횟수가 "
            f"low({low_avg:.4f}) < medium({medium_avg:.4f}) < high({high_avg:.4f}) "
            "순서를 만족하지 않습니다."
        )
    print(
        f"[검증 통과] visit_frequency 평균 방문 순서 확인: low({low_avg:.4f}) < "
        f"medium({medium_avg:.4f}) < high({high_avg:.4f})"
    )


# ======================================================================================
# 12. 결과 요약 출력
# ======================================================================================

def print_summary(
    visitor_df: pd.DataFrame,
    customer_df: pd.DataFrame,
    output_path: str,
    simulation_start: pd.Timestamp,
    simulation_end: pd.Timestamp,
) -> None:
    """최종 실행 결과 요약을 출력한다."""
    print("\n" + "=" * 80)
    print("[실행 결과 요약]")
    print("=" * 80)
    print(f"저장 완료 경로: {output_path}")
    print(f"shape: {visitor_df.shape}")
    print("head():")
    print(visitor_df.head().to_string())
    print(f"기간: {simulation_start.date()} ~ {simulation_end.date()}")
    print(f"visitor_id 중복 수: {visitor_df['visitor_id'].duplicated().sum()}")
    print(f"결측치 수: {int(visitor_df.isna().sum().sum())}")

    valid_customer_ids = set(customer_df["customer_id"])
    fk_error_count = (~visitor_df["customer_id"].isin(valid_customer_ids)).sum()
    print(f"FK 오류 수(customer_id 기준): {fk_error_count}")

    visits_per_customer_all = (
        visitor_df.groupby("customer_id").size().reindex(customer_df["customer_id"], fill_value=0)
    )
    print(f"고객당 평균 방문 횟수: {visits_per_customer_all.mean():.4f}")

    freq_map = customer_df.set_index("customer_id")["visit_frequency"]
    visits_with_freq = pd.DataFrame(
        {"visit_count": visits_per_customer_all, "visit_frequency": freq_map}
    )
    print("visit_frequency별 평균 방문 횟수:")
    print(visits_with_freq.groupby("visit_frequency")["visit_count"].mean().to_string())

    print("매장별 방문 수:")
    print(visitor_df["store_id"].value_counts().to_string())

    print("day_type별 방문 수:")
    print(visitor_df["day_type"].value_counts().to_string())

    print("time_slot별 방문 수:")
    print(visitor_df["time_slot"].value_counts().to_string())

    print("검증 최종 결과: PASS")
    print("[VALIDATION PASS] visitor.csv 생성 및 검증 완료")


# ======================================================================================
# 13. main
# ======================================================================================

def main() -> None:
    """전체 파이프라인 실행: 로드 -> 검증 -> 생성 -> 검증 -> 저장 -> 요약 출력."""
    rng = np.random.default_rng(RANDOM_SEED)
    random.seed(RANDOM_SEED)

    # 1) 입력 CSV 로드
    data = load_input_data(INPUT_DIR)

    # 날짜 컬럼 datetime 변환
    data["calendar"]["date"] = pd.to_datetime(data["calendar"]["date"])
    data["store_calendar"]["date"] = pd.to_datetime(data["store_calendar"]["date"])
    data["inventory"]["current_date"] = pd.to_datetime(data["inventory"]["current_date"])

    # 2) 스키마 및 필수 컬럼 검증
    validate_input_data(data)

    # 3)/4) 시뮬레이션 기간 계산
    simulation_calendar, simulation_start, simulation_end = build_simulation_calendar(
        data["calendar"], data["inventory"]
    )
    simulation_days = int((simulation_end - simulation_start).days) + 1

    # 5)/6) 고객별 기대/실제 방문 횟수 생성
    customer_visits_df = generate_customer_visit_counts(
        data["customer"], simulation_days, rng
    )

    # 7)~10) 방문 날짜/매장/time_slot/시각 생성
    raw_visitor_df = generate_visitor_data(
        customer_visits_df,
        simulation_calendar,
        data["store"],
        data["store_calendar"],
        data["store_visitor_profile"],
        rng,
    )

    # 11)~13) 정렬, visit_sequence, visitor_id 부여
    visitor_df = assign_visit_sequence_and_id(raw_visitor_df)

    # 14) 최종 검증
    validate_visitor_data(visitor_df, data, simulation_start, simulation_end)

    # 15) 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE_NAME)
    visitor_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    # 실행 결과 출력
    print_summary(visitor_df, data["customer"], output_path, simulation_start, simulation_end)


if __name__ == "__main__":
    main()
