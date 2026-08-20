"""
KT AIVLE School 빅프로젝트
AI 신선식품 수요 예측 및 다이나믹 프라이싱 플랫폼
5단계 - 합성데이터 생성 : STORE 관련 CSV 4종

생성 파일
1) store.csv
2) store_visitor_profile.csv
3) calendar.csv
4) store_calendar.csv

실행 환경 : Google Colab

※ 참고
영업시간(10~22, 10~23)과 의무휴업 규칙(요일/주차)은 실제 롯데마트 운영 특성을 참고하여
프로젝트에서 설정한 "합성 데이터 가정값"입니다. 원본 프로젝트 데이터.pdf에 명시된 실측값이 아닙니다.
"""

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

# =========================================================
# 0. 공통 설정
# =========================================================

SEED = 42
np.random.seed(SEED)
# 이번 STORE 4종 CSV는 전부 확정값/규칙 기반 계산이라 실제 난수 샘플링은 없습니다.
# 이후 단계(customer, transactions 등)에서 랜덤 샘플링이 들어갈 때를 대비해 seed만 고정해둡니다.

SAVE_DIR = "/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터/"


def ensure_save_dir(path: str = SAVE_DIR) -> str:
    """저장 폴더가 없으면 생성합니다."""
    os.makedirs(path, exist_ok=True)
    return path


def save_csv(df: pd.DataFrame, filename: str, path: str = SAVE_DIR) -> str:
    """DataFrame을 utf-8-sig 인코딩으로 저장하고 결과를 출력합니다."""
    ensure_save_dir(path)
    full_path = os.path.join(path, filename)
    df.to_csv(full_path, index=False, encoding="utf-8-sig")
    print(f"[저장 완료] {full_path}  (shape={df.shape})")
    return full_path


def show_result(df: pd.DataFrame, name: str, n: int = 3) -> None:
    """생성 결과 상위 n행과 shape을 출력합니다."""
    print(f"\n=== {name} 상위 {n}행 ===")
    print(df.head(n))
    print(f"=== {name} shape === {df.shape}")


# =========================================================
# 1. store.csv
# =========================================================

def build_store_df() -> pd.DataFrame:
    """
    매장 3곳의 고정 속성 테이블.
    모든 값은 확정된 프로젝트 가정값이며, 하드코딩된 3행으로 구성합니다.
    """
    data = {
        "store_id": ["S01", "S02", "S03"],
        "store_name": ["가상주거형점", "가상오피스형점", "가상복합형점"],
        "area_type": ["residential", "office", "mixed"],
        "resident_pop": [25000, 8000, 16000],
        "floating_idx": [0.85, 1.40, 1.10],
        "open_hour": [10, 10, 10],
        "close_hour": [23, 22, 23],
        "closure_weekday": ["SUN", "WED", "SUN"],
        "closure_week_1": [2, 2, 2],
        "closure_week_2": [4, 4, 4],
        "order_error_sigma": [0.12, 0.15, 0.18],
    }
    df = pd.DataFrame(data)

    df = df.astype({
        "resident_pop": "int64",
        "floating_idx": "float64",
        "open_hour": "int64",
        "close_hour": "int64",
        "closure_week_1": "int64",
        "closure_week_2": "int64",
        "order_error_sigma": "float64",
    })
    return df


def validate_store(df: pd.DataFrame) -> bool:
    print("\n[검증] store.csv")
    errors = []

    # PK 중복
    dup = df["store_id"].duplicated().sum()
    print(f" - store_id 중복: {dup}건")
    if dup > 0:
        errors.append("store_id 중복 존재")

    # 영업시간 범위 (0<=open<24, open<close<=24)
    bad_hours = df[~(
        (df["open_hour"] >= 0) & (df["open_hour"] < 24) &
        (df["close_hour"] > df["open_hour"]) & (df["close_hour"] <= 24)
    )]
    print(f" - 영업시간 값 이상 매장 수: {len(bad_hours)}건")
    if len(bad_hours) > 0:
        errors.append("영업시간 범위 이상")

    # 휴무요일 / 휴무주차 값 유효성
    valid_weekdays = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    bad_wd = df[~df["closure_weekday"].isin(valid_weekdays)]
    bad_week = df[
        ~df["closure_week_1"].isin([1, 2, 3, 4, 5]) |
        ~df["closure_week_2"].isin([1, 2, 3, 4, 5])
    ]
    print(f" - 휴무요일 값 이상: {len(bad_wd)}건 / 휴무주차 값 이상: {len(bad_week)}건")
    if len(bad_wd) > 0 or len(bad_week) > 0:
        errors.append("휴무 규칙 값 이상")

    ok = len(errors) == 0
    print(" => store.csv 검증 " + ("통과" if ok else f"실패: {errors}"))
    return ok


# =========================================================
# 2. store_visitor_profile.csv
# =========================================================

# close_hour별 시간대 정의 (요구사항 그대로)
TIME_SLOTS_23 = [
    ("morning", 10, 12),
    ("lunch", 12, 15),
    ("afternoon", 15, 18),
    ("evening", 18, 21),
    ("closing", 21, 23),
]
TIME_SLOTS_22 = [
    ("morning", 10, 12),
    ("lunch", 12, 15),
    ("afternoon", 15, 18),
    ("evening", 18, 21),
    ("closing", 21, 22),
]

DAY_TYPES = ["weekday", "weekend", "holiday"]

# [가정] 합성 규칙 - 실측 자료 없음. 상권유형별 방문 패턴 특성을 반영한 가중치입니다.
# area_type + day_type 조합별로 5개 시간대 가중치를 정의하고, 아래 build 함수에서
# 합계가 정확히 1.0이 되도록 정규화합니다.
BASE_WEIGHTS = {
    "residential": {
        "weekday": {"morning": 0.15, "lunch": 0.15, "afternoon": 0.20, "evening": 0.35, "closing": 0.15},
        "weekend":  {"morning": 0.20, "lunch": 0.20, "afternoon": 0.25, "evening": 0.25, "closing": 0.10},
        "holiday":  {"morning": 0.18, "lunch": 0.22, "afternoon": 0.25, "evening": 0.25, "closing": 0.10},
    },
    "office": {
        "weekday": {"morning": 0.10, "lunch": 0.35, "afternoon": 0.15, "evening": 0.30, "closing": 0.10},
        "weekend":  {"morning": 0.20, "lunch": 0.25, "afternoon": 0.25, "evening": 0.20, "closing": 0.10},
        "holiday":  {"morning": 0.20, "lunch": 0.25, "afternoon": 0.25, "evening": 0.20, "closing": 0.10},
    },
    "mixed": {
        "weekday": {"morning": 0.12, "lunch": 0.20, "afternoon": 0.23, "evening": 0.30, "closing": 0.15},
        "weekend":  {"morning": 0.15, "lunch": 0.20, "afternoon": 0.25, "evening": 0.28, "closing": 0.12},
        "holiday":  {"morning": 0.15, "lunch": 0.20, "afternoon": 0.25, "evening": 0.28, "closing": 0.12},
    },
}


def build_store_visitor_profile_df(store_df: pd.DataFrame) -> pd.DataFrame:
    """
    area_type + close_hour 조합을 store.csv에서 직접 가져와서 생성합니다.
    (동일 area_type이라도 close_hour가 다른 매장이 추가될 수 있으므로
     area_type만으로 drop_duplicates 하지 않고, area_type+close_hour 조합 전체를 사용합니다.)
    """
    rows = []
    area_close_map = (
        store_df[["area_type", "close_hour"]]
        .drop_duplicates()
    )

    for _, r in area_close_map.iterrows():
        area_type = r["area_type"]
        close_hour = int(r["close_hour"])
        slots = TIME_SLOTS_23 if close_hour == 23 else TIME_SLOTS_22

        for day_type in DAY_TYPES:
            weights = BASE_WEIGHTS[area_type][day_type]
            total_w = sum(weights[s[0]] for s in slots)
            ratios = [round(weights[s[0]] / total_w, 4) for s in slots]

            # 반올림 오차 보정 : 마지막 슬롯에 잔차를 흡수시켜 합계를 정확히 1.0으로 맞춤
            diff = round(1.0 - sum(ratios), 4)
            ratios[-1] = round(ratios[-1] + diff, 4)

            for (slot_name, start_h, end_h), ratio in zip(slots, ratios):
                rows.append({
                    "area_type": area_type,
                    "day_type": day_type,
                    "close_hour": close_hour,
                    "time_slot": slot_name,
                    "start_hour": start_h,
                    "end_hour": end_h,
                    "visitor_ratio": ratio,
                    "profile_source": "synthetic_rule",
                })

    return pd.DataFrame(rows)


def validate_store_visitor_profile(df: pd.DataFrame) -> bool:
    print("\n[검증] store_visitor_profile.csv")
    errors = []

    # 중복 - 실제 PK는 (area_type, day_type, close_hour, time_slot)
    dup = df.duplicated(subset=["area_type", "day_type", "close_hour", "time_slot"]).sum()
    print(f" - (area_type,day_type,close_hour,time_slot) 중복: {dup}건")
    if dup > 0:
        errors.append("중복 존재")

    # visitor_ratio 합계 = 1.0
    ratio_sum = df.groupby(["area_type", "day_type", "close_hour"])["visitor_ratio"].sum()
    bad_ratio = ratio_sum[~np.isclose(ratio_sum, 1.0, atol=1e-6)]
    print(f" - visitor_ratio 합계 1.0이 아닌 조합 수: {len(bad_ratio)}건")
    if len(bad_ratio) > 0:
        print(bad_ratio)
        errors.append("visitor_ratio 합계 오류")

    # 시간대 정상 여부 (start < end)
    bad_slot = df[df["start_hour"] >= df["end_hour"]]
    print(f" - 시간대 역전(start>=end) 오류: {len(bad_slot)}건")
    if len(bad_slot) > 0:
        errors.append("시간대 값 오류")

    # 시간대 연속성 (공백/중첩 없이 open_hour~close_hour를 정확히 채우는지)
    gap_errors = 0
    for (area_type, day_type, close_hour), g in df.groupby(["area_type", "day_type", "close_hour"]):
        g = g.sort_values("start_hour")
        if g.iloc[0]["start_hour"] != 10:
            gap_errors += 1
        if g.iloc[-1]["end_hour"] != close_hour:
            gap_errors += 1
        for i in range(len(g) - 1):
            if g.iloc[i]["end_hour"] != g.iloc[i + 1]["start_hour"]:
                gap_errors += 1
    print(f" - 시간대 연속성(공백/중첩) 오류: {gap_errors}건")
    if gap_errors > 0:
        errors.append("시간대 연속성 오류")

    ok = len(errors) == 0
    print(" => store_visitor_profile.csv 검증 " + ("통과" if ok else f"실패: {errors}"))
    return ok


# =========================================================
# 3. calendar.csv
# =========================================================

# 2025년 한국 법정 공휴일 + 임시공휴일 + 대체공휴일
# 출처 : 인사혁신처 고시 · 관공서의 공휴일에 관한 규정 (kholidayz.com 정리 기준)
#        2025-06-03 임시공휴일은 정부 국무회의 발표(2025-04-08, 제21대 대통령선거일 지정) 근거
# 근로자의 날(5/1)은 "관공서의 공휴일에 관한 규정"상 공휴일 목록에 포함되지 않아 제외했습니다.
KR_HOLIDAYS_2025 = {
    "2025-01-01": "신정",
    "2025-01-27": "임시공휴일(설날)",
    "2025-01-28": "설날연휴",
    "2025-01-29": "설날",
    "2025-01-30": "설날연휴",
    "2025-03-01": "삼일절",
    "2025-03-03": "대체공휴일(삼일절)",
    "2025-05-05": "어린이날_부처님오신날",
    "2025-05-06": "대체공휴일(부처님오신날)",
    "2025-06-03": "임시공휴일(대통령선거일)",
    "2025-06-06": "현충일",
    "2025-08-15": "광복절",
    "2025-10-03": "개천절",
    "2025-10-05": "추석연휴",
    "2025-10-06": "추석",
    "2025-10-07": "추석연휴",
    "2025-10-08": "대체공휴일(추석)",
    "2025-10-09": "한글날",
    "2025-12-25": "크리스마스",
}

# ----------------------------------------------------------------
# [프로젝트 합성 데이터 규칙]
# 명절 장보기 수요를 표현하기 위해
# - 명절 D-2 : event_index = 1.15
# - 명절 D-1 : event_index = 1.20
# 으로 설정한다.
# 명절 당일은 별도 급락 계수를 적용하지 않는다.
# 복날 및 지역축제 이벤트는 근거 부족 및 검증 범위 제외로
# 현재 버전에서는 반영하지 않는다.
# ----------------------------------------------------------------
FESTIVAL_ANCHORS = {
    "설날": date(2025, 1, 29),
    "추석": date(2025, 10, 6),
}
FESTIVAL_D2_INDEX = 1.15
FESTIVAL_D1_INDEX = 1.20

WEEKDAY_LABELS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# 계절별 수요계수는 아직 확정되지 않아 전부 1.0(중립값)으로 둡니다.
# 정수형 계절 번호(1,2,3,4)로 보이면 모델링팀이 "가중치"가 아니라 "계절 코드"로
# 오인할 수 있어, 계수가 확정되기 전까지는 float 1.0으로 통일합니다.
SEASON_INDEX_MAP = {
    "spring": 1.0,
    "summer": 1.0,
    "fall": 1.0,
    "winter": 1.0,
}


def get_season(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    elif month in (9, 10, 11):
        return "fall"
    else:
        return "winter"


def build_calendar_df(start: str = "2025-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    dates = pd.date_range(start=start, end=end, freq="D")

    # 명절 D-2/D-1 이벤트 날짜 맵 미리 계산
    event_map = {}
    for name, anchor in FESTIVAL_ANCHORS.items():
        event_map[anchor - timedelta(days=2)] = ("명절", FESTIVAL_D2_INDEX)
        event_map[anchor - timedelta(days=1)] = ("명절", FESTIVAL_D1_INDEX)

    rows = []
    for d in dates:
        d_date = d.date()
        date_str = d.strftime("%Y-%m-%d")
        weekday_idx = d.weekday()  # 0=월 ... 6=일
        day_of_week = WEEKDAY_LABELS[weekday_idx]
        is_weekend = weekday_idx in (5, 6)
        is_holiday = date_str in KR_HOLIDAYS_2025
        holiday_name = KR_HOLIDAYS_2025.get(date_str, "")

        if is_holiday:
            day_type = "holiday"
        elif is_weekend:
            day_type = "weekend"
        else:
            day_type = "weekday"

        week_of_month = (d.day - 1) // 7 + 1
        season = get_season(d.month)
        season_index = SEASON_INDEX_MAP[season]

        ev = event_map.get(d_date)
        is_event_day = ev is not None
        event_type = ev[0] if ev else ""
        event_index = ev[1] if ev else 1.0

        rows.append({
            "date": date_str,
            "year": d.year,
            "month": d.month,
            "day": d.day,
            "day_of_week": day_of_week,
            "week_of_month": week_of_month,
            "day_type": day_type,
            "is_weekend": int(is_weekend),
            "is_holiday": int(is_holiday),
            "holiday_name": holiday_name,
            "season": season,
            "season_index": season_index,
            "is_event_day": int(is_event_day),
            "event_type": event_type,
            "event_index": event_index,
        })

    df = pd.DataFrame(rows)
    df = df.astype({
        "year": "int64", "month": "int64", "day": "int64",
        "week_of_month": "int64", "is_weekend": "int64",
        "is_holiday": "int64", "season_index": "float64",
        "is_event_day": "int64", "event_index": "float64",
    })
    return df


def validate_calendar(df: pd.DataFrame) -> bool:
    print("\n[검증] calendar.csv")
    errors = []

    dup = df["date"].duplicated().sum()
    print(f" - 날짜 중복: {dup}건")
    if dup > 0:
        errors.append("날짜 중복")

    print(f" - 총 생성일수: {len(df)}일 (2025년 기대값 365일)")
    if len(df) != 365:
        errors.append("총 일수 불일치")

    holiday_count = int(df["is_holiday"].sum())
    expected = len(KR_HOLIDAYS_2025)
    print(f" - 공휴일 수: {holiday_count}건 (기대값 {expected}건)")
    if holiday_count != expected:
        errors.append("공휴일 수 불일치")

    ok = len(errors) == 0
    print(" => calendar.csv 검증 " + ("통과" if ok else f"실패: {errors}"))
    return ok


# =========================================================
# 4. store_calendar.csv
# =========================================================

# ----------------------------------------------------------------
# 프로젝트 최종 결정
# - 의무휴업 전일 : 수요 +21%
# - 의무휴업 당일 : 휴점(is_open=0)
# 단, 의무휴업 전일 +21% 효과는 calendar.csv가 아니라
# 향후 transaction 생성 단계에서 store_calendar를 참조하여 적용한다.
# 현재 STORE CSV 생성 단계에서는 휴무일 정보만 생성한다.
# ----------------------------------------------------------------

def build_store_calendar_df(calendar_df: pd.DataFrame, store_df: pd.DataFrame) -> pd.DataFrame:
    """
    calendar.csv x store.csv Cartesian Join 후, 의무휴업 조건을 적용합니다.
    조건 : calendar.day_of_week == store.closure_weekday
           AND calendar.week_of_month in (closure_week_1, closure_week_2)
    """
    cross = calendar_df[["date", "day_of_week", "week_of_month"]].merge(
        store_df[[
            "store_id", "closure_weekday", "closure_week_1", "closure_week_2",
            "open_hour", "close_hour",
        ]],
        how="cross",
    )

    is_mandatory_closed = (
        (cross["day_of_week"] == cross["closure_weekday"]) &
        (
            (cross["week_of_month"] == cross["closure_week_1"]) |
            (cross["week_of_month"] == cross["closure_week_2"])
        )
    )

    cross["is_mandatory_closed"] = is_mandatory_closed.astype(int)
    cross["is_open"] = np.where(is_mandatory_closed, 0, 1)
    cross["open_hour"] = np.where(is_mandatory_closed, np.nan, cross["open_hour"])
    cross["close_hour"] = np.where(is_mandatory_closed, np.nan, cross["close_hour"])
    cross["closure_reason"] = np.where(is_mandatory_closed, "MANDATORY", "NONE")

    result = cross[[
        "date", "store_id", "is_mandatory_closed", "is_open",
        "open_hour", "close_hour", "closure_reason",
    ]].sort_values(["store_id", "date"]).reset_index(drop=True)

    return result


def validate_store_calendar(df: pd.DataFrame, store_df: pd.DataFrame) -> bool:
    print("\n[검증] store_calendar.csv")
    errors = []

    dup = df.duplicated(subset=["date", "store_id"]).sum()
    print(f" - (date,store_id) PK 중복: {dup}건")
    if dup > 0:
        errors.append("PK 중복")

    merged = df.merge(
        store_df[["store_id", "open_hour", "close_hour"]],
        on="store_id", suffixes=("", "_store"),
    )
    open_rows = merged[merged["is_open"] == 1]
    bad_open = open_rows[
        (open_rows["open_hour"] != open_rows["open_hour_store"]) |
        (open_rows["close_hour"] != open_rows["close_hour_store"])
    ]
    print(f" - 영업일 open/close hour 불일치: {len(bad_open)}건")
    if len(bad_open) > 0:
        errors.append("영업시간 반영 오류")

    closed_rows = df[df["is_open"] == 0]
    bad_closed = closed_rows[closed_rows["open_hour"].notna() | closed_rows["close_hour"].notna()]
    print(f" - 휴무일인데 영업시간 값 존재: {len(bad_closed)}건")
    if len(bad_closed) > 0:
        errors.append("휴무일 시간값 오류")

    print(" - 매장별 의무휴업일 수 :")
    closure_count = df.groupby("store_id")["is_mandatory_closed"].sum()
    print(closure_count)
    # 매달 2번째/4번째 해당 요일은 항상 존재 -> 12개월 x 2일 = 24일이 이론적 기댓값
    bad_count = closure_count[closure_count != 24]
    if len(bad_count) > 0:
        print(f" - 기대값(24일)과 다른 매장: {dict(bad_count)}")
        errors.append("의무휴업일 수 불일치")

    ok = len(errors) == 0
    print(" => store_calendar.csv 검증 " + ("통과" if ok else f"실패: {errors}"))
    return ok


# =========================================================
# 5. 메인 실행
# =========================================================

def main():
    # Colab 환경 - 구글 드라이브 마운트
    #from google.colab import drive
    #drive.mount('/content/drive')

    ensure_save_dir()

    # 1) store.csv
    store_df = build_store_df()
    save_csv(store_df, "store.csv")
    show_result(store_df, "store.csv")
    print(store_df.dtypes)
    result_store = validate_store(store_df)

    # 2) store_visitor_profile.csv
    profile_df = build_store_visitor_profile_df(store_df)
    save_csv(profile_df, "store_visitor_profile.csv")
    show_result(profile_df, "store_visitor_profile.csv")
    result_profile = validate_store_visitor_profile(profile_df)

    # 3) calendar.csv
    calendar_df = build_calendar_df()
    save_csv(calendar_df, "calendar.csv")
    show_result(calendar_df, "calendar.csv")
    result_calendar = validate_calendar(calendar_df)

    # 4) store_calendar.csv
    store_calendar_df = build_store_calendar_df(calendar_df, store_df)
    save_csv(store_calendar_df, "store_calendar.csv")
    show_result(store_calendar_df, "store_calendar.csv")
    result_store_calendar = validate_store_calendar(store_calendar_df, store_df)

    validation_results = [
        result_store,
        result_profile,
        result_calendar,
        result_store_calendar,
    ]

    if all(validation_results):
        print("\n=== STORE 관련 CSV 4종 생성 및 검증 완료 ===")
    else:
        raise ValueError("일부 CSV 검증에 실패했습니다.")


if __name__ == "__main__":
    main()
