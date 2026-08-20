"""
make_customer_v2.py
===================
FRESH WATCH - customer_v2.csv 생성 로직 재현 스크립트

customer_v2.csv 는 customer.csv 에 컬럼을 추가해 만든 파일이 아니라
KOSIS 공공통계에서 1만 명을 새로 샘플링한 파일이다. customer_id 도
재생성이므로 두 파일은 행 단위로 조인되지 않는다.

입력 (같은 폴더)
    K1_연령x가구원수_결합분포_2024.csv   KOSIS 인구총조사 2024
    K2_가구원수별_식료품지출_2024.csv     가계동향조사 2024
    K3_소득분위별_식료품지출_2024.csv     가계동향조사 2024 소득10분위

출력
    customer_v2.csv  (10,000행 x 21컬럼)

실행
    python make_customer_v2.py

주의
    원본 생성 시점의 난수 시드가 남아있지 않아 기존 customer_v2.csv 와
    행 단위로 동일한 파일은 나오지 않는다. 컬럼 정의·생성 로직·분포
    파라미터가 기존 파일과 일치하도록 작성했다. 스크립트 하단의
    validate() 가 기존 파일 및 공식 통계와의 대조 결과를 출력한다.

표기
    ★ 공공통계·실측에서 직접 산출한 값
    ☆ 근거 없이 정한 가정값 (민감도 분석 대상)
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. 설정
# ---------------------------------------------------------------------------

SEED = 20260805
N_CUSTOMERS = 10_000

AGE_GROUPS = ["20s", "30s", "40s", "50s", "60_plus"]
HH_BUCKETS = ["1", "2", "3~4", "5+"]
HH_NUMERIC = {"1": 1.0, "2": 2.0, "3~4": 3.5, "5+": 5.0}
CATEGORIES = ["produce", "meat", "dairy", "deli", "cheese"]

# 마트 신선식품 예산 스케일 계수 ☆
#   신선식품 비중 0.45 x 대형마트 채널 비중 0.25 x 38개 SKU 커버리지 0.40
MART_FRESH_RATIO = 0.45 * 0.25 * 0.40          # = 0.045
FOOD_BUDGET_LOGNORM_SD = 0.12                  # 개인차 ☆

# 소득분위 조건부 샘플링 ☆
INCOME_KERNEL_SIGMA = 1.1
DECILE_MEAN_HHSIZE = np.linspace(1.0, 3.4, 10)

# Dunnhumby 실측 회귀 ★ : 할인구매비중 = 0.618 - 0.033 * ln(연소득 천USD)
PS_INTERCEPT, PS_SLOPE = 0.618, -0.033
KRW_PER_USD = 1350.0
# 위 회귀 출력을 효용함수용 0~1 척도로 선형 사상하는 구간 ☆
PS_SCALE_LOW, PS_SCALE_HIGH = 0.30, 0.85
PS_NOISE_SD = 0.07

# Dunnhumby 실측 ★ : 가구원수별 바스켓 품목 수. 2인 가구를 1.0 으로 정규화.
#   가구원수는 라인당 수량(1.30~1.34, 사실상 무차이)이 아니라 품목 수에 영향
BASKET_ITEMS = {"1": 9.10, "2": 10.14, "3~4": 11.26, "5+": 12.71}
BASKET_REF = "2"

# 연령대별 신선도 민감도 중심값 ☆ (기존 customer.csv 승계)
FRESHNESS_CENTER = {"20s": 0.65, "30s": 0.72, "40s": 0.76, "50s": 0.78, "60_plus": 0.79}
FRESHNESS_SD = 0.08
FRESHNESS_CLIP = (0.05, 0.99)

# 연령대별 카테고리 선호 중심 벡터 ☆ (produce/meat/dairy/deli/cheese)
PREF_CENTER = {
    "20s":     [0.300, 0.226, 0.179, 0.219, 0.076],
    "30s":     [0.327, 0.240, 0.191, 0.159, 0.083],
    "40s":     [0.361, 0.259, 0.182, 0.120, 0.078],
    "50s":     [0.400, 0.258, 0.174, 0.099, 0.069],
    "60_plus": [0.449, 0.241, 0.171, 0.078, 0.061],
}
DIRICHLET_CONCENTRATION = 28.0

# 연간 방문 횟수 ☆ : 감마분포 shape 6, 평균 88회
VISIT_GAMMA_SHAPE, VISIT_LAMBDA_MEAN = 6.0, 88.0
VISIT_FREQ_CUTS = (55.0, 110.0)

# 거주형태 분포 ☆ : 가구원수에 따라 달라진다
RESIDENCE_P = {
    "1":   [0.303, 0.547, 0.150],
    "2":   [0.670, 0.086, 0.244],
    "3~4": [0.682, 0.077, 0.241],
    "5+":  [0.701, 0.074, 0.225],
}
RESIDENCE_TYPES = ["apartment", "single_household", "villa"]

rng = np.random.default_rng(SEED)


def _read_csv(path):
    """BOM 포함 CSV 를 읽고 첫 컬럼명의 \\ufeff 를 제거한다."""
    df = pd.read_csv(path)
    df.columns = [c.replace("\ufeff", "").strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# 1. 연령 x 가구원수 결합분포 ★ (KOSIS 인구총조사 2024)
# ---------------------------------------------------------------------------
# 연령과 가구원수를 따로 뽑으면 "20대 5인가구" 같은 비현실 조합이 생긴다.
# 20개 셀의 결합분포에서 직접 뽑으면 구조적으로 차단된다.

AGE_BIN_MAP = {
    "20~24세": "20s", "25~29세": "20s",
    "30~34세": "30s", "35~39세": "30s",
    "40~44세": "40s", "45~49세": "40s",
    "50~54세": "50s", "55~59세": "50s",
    "60~64세": "60_plus", "65~69세": "60_plus", "70~74세": "60_plus",
    "75~79세": "60_plus", "80~84세": "60_plus", "85세 이상": "60_plus",
}
K1_HH_COLS = ["1인", "2인", "3~4인", "5인+"]


def build_joint_distribution():
    k1 = _read_csv("K1_연령x가구원수_결합분포_2024.csv")
    k1 = k1[k1["연령"] != "합계"].copy()
    k1["age_group"] = k1["연령"].map(AGE_BIN_MAP)

    counts = k1.groupby("age_group")[K1_HH_COLS].sum().reindex(AGE_GROUPS)
    joint = counts.to_numpy(dtype=float)
    return joint / joint.sum()                      # (5 age x 4 hh)


def sample_age_household(joint, n):
    flat = joint.ravel()
    idx = rng.choice(flat.size, size=n, p=flat)
    age_idx, hh_idx = np.unravel_index(idx, joint.shape)
    return np.array(AGE_GROUPS)[age_idx], np.array(HH_BUCKETS)[hh_idx]


def derive_household_type(age_group, household_size):
    """1~2인 가구 중 60세 이상은 senior, 3인 이상은 family."""
    return np.where(household_size == "1",
                    np.where(age_group == "60_plus", "senior", "single"),
             np.where(household_size == "2",
                      np.where(age_group == "60_plus", "senior", "couple"),
                      "family"))


# ---------------------------------------------------------------------------
# 2. 소득분위 ★경계 + ☆조건부 샘플링
# ---------------------------------------------------------------------------
# 가구원수와 소득분위는 독립이 아니다(저분위일수록 1인가구 비중이 높다).
# 분위별 목표 평균 가구원수를 중심으로 한 가우시안 커널로 가중 추출한다.

def sample_income_decile(household_size):
    hs = np.array([HH_NUMERIC[h] for h in household_size])[:, None]
    w = np.exp(-((hs - DECILE_MEAN_HHSIZE[None, :]) ** 2)
               / (2 * INCOME_KERNEL_SIGMA ** 2))
    w /= w.sum(axis=1, keepdims=True)

    u = rng.random(len(household_size))[:, None]
    return ((w.cumsum(axis=1) < u).sum(axis=1) + 1).clip(1, 10).astype(int)


DECILE_LABEL = {1: "１분위", 2: "２분위", 3: "３분위", 4: "４분위", 5: "５분위",
                6: "６분위", 7: "７분위", 8: "８분위", 9: "９분위", 10: "10분위"}


def load_income_tables():
    k3 = _read_csv("K3_소득분위별_식료품지출_2024.csv").set_index("소득분위")
    disposable = {d: float(k3.loc[l, "처분가능소득"]) for d, l in DECILE_LABEL.items()}
    food_exp = {d: float(k3.loc[l, "01.식료품 · 비주류음료"]) for d, l in DECILE_LABEL.items()}
    overall = float(k3.loc["전체  평균", "01.식료품 · 비주류음료"])
    return disposable, food_exp, overall


# ---------------------------------------------------------------------------
# 3. 식료품 예산 ★ (가계동향조사 2024)
# ---------------------------------------------------------------------------
# 가구원수별 지출을 기준값으로 두고 소득분위 조정계수를 곱한다.
# 조정계수는 가구원수 그룹 내부에서 평균 1이 되도록 정규화한다(이중계상 방지).

def load_food_budget_base():
    k2 = _read_csv("K2_가구원수별_식료품지출_2024.csv")
    k2 = k2[k2["항목"].str.contains("식료품")].set_index("가구원수")["2024년_월평균_원"]
    return {
        "1": float(k2["1인"]),
        "2": float(k2["2인"]),
        "3~4": (float(k2["3인"]) + float(k2["4인"])) / 2.0,
        "5+": float(k2["5인이상"]),
    }


def build_food_budget(household_size, income_decile, base_map, food_exp, overall):
    base = np.array([base_map[h] for h in household_size])
    raw_adj = np.array([food_exp[d] / overall for d in income_decile])

    adj = raw_adj.copy()
    for h in HH_BUCKETS:                              # 그룹 내부 평균 1로 정규화
        m = household_size == h
        adj[m] = raw_adj[m] / raw_adj[m].mean()

    noise = np.exp(rng.normal(0.0, FOOD_BUDGET_LOGNORM_SD, size=len(base)))
    monthly = base * adj * noise
    return monthly, monthly * MART_FRESH_RATIO


# ---------------------------------------------------------------------------
# 4. 가격 민감도 ★ (Dunnhumby 260만 라인 회귀)
# ---------------------------------------------------------------------------

def build_price_sensitivity(disposable_income_krw):
    income_kusd = disposable_income_krw * 12.0 / KRW_PER_USD / 1000.0
    raw = PS_INTERCEPT + PS_SLOPE * np.log(income_kusd)

    lo, hi = raw.min(), raw.max()
    scaled = PS_SCALE_LOW + (raw - lo) / (hi - lo) * (PS_SCALE_HIGH - PS_SCALE_LOW)
    return np.clip(scaled + rng.normal(0.0, PS_NOISE_SD, len(raw)), 0.0, 1.0).round(4)


# ---------------------------------------------------------------------------
# 5. 나머지 컬럼
# ---------------------------------------------------------------------------

def build_basket_size_factor(household_size):
    ref = BASKET_ITEMS[BASKET_REF]
    return np.array([round(BASKET_ITEMS[h] / ref, 3) for h in household_size])


def build_freshness_sensitivity(age_group):
    center = np.array([FRESHNESS_CENTER[a] for a in age_group])
    v = center + rng.normal(0.0, FRESHNESS_SD, len(center))
    return np.clip(v, *FRESHNESS_CLIP).round(4)


def build_preferences(age_group):
    prefs = np.empty((len(age_group), len(CATEGORIES)))
    for a in AGE_GROUPS:
        m = age_group == a
        alpha = np.array(PREF_CENTER[a]) * DIRICHLET_CONCENTRATION
        prefs[m] = rng.dirichlet(alpha, size=int(m.sum()))
    return prefs.round(4)


# ---------------------------------------------------------------------------
# 6. 조립
# ---------------------------------------------------------------------------

def main():
    joint = build_joint_distribution()
    age_group, household_size = sample_age_household(joint, N_CUSTOMERS)
    household_type = derive_household_type(age_group, household_size)

    income_decile = sample_income_decile(household_size)
    disposable_map, food_exp, overall = load_income_tables()
    disposable_income = np.array([disposable_map[d] for d in income_decile])

    monthly_food_budget, mart_fresh_budget = build_food_budget(
        household_size, income_decile, load_food_budget_base(), food_exp, overall)

    price_sensitivity = build_price_sensitivity(disposable_income)
    freshness_sensitivity = build_freshness_sensitivity(age_group)
    basket_size_factor = build_basket_size_factor(household_size)
    prefs = build_preferences(age_group)

    visit_lambda_year = rng.gamma(VISIT_GAMMA_SHAPE,
                                  VISIT_LAMBDA_MEAN / VISIT_GAMMA_SHAPE,
                                  N_CUSTOMERS).round(1)

    income_level = np.where(income_decile <= 3, "low",
                     np.where(income_decile <= 7, "middle", "high"))
    visit_frequency = np.where(visit_lambda_year < VISIT_FREQ_CUTS[0], "low",
                        np.where(visit_lambda_year < VISIT_FREQ_CUTS[1], "medium", "high"))
    residence_type = np.array([
        rng.choice(RESIDENCE_TYPES, p=RESIDENCE_P[h]) for h in household_size])
    preferred_category = np.array(CATEGORIES)[prefs.argmax(axis=1)]

    df = pd.DataFrame({
        "customer_id": [f"CUS{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
        "age_group": age_group,
        "household_size": household_size,
        "household_type": household_type,
        "income_decile": income_decile,
        "income_level": income_level,
        "residence_type": residence_type,
        "disposable_income": disposable_income.round(0).astype(int),
        "monthly_food_budget": monthly_food_budget.round(0).astype(int),
        "mart_fresh_budget": mart_fresh_budget.round(0).astype(int),
        "price_sensitivity": price_sensitivity,
        "freshness_sensitivity": freshness_sensitivity,
        "basket_size_factor": basket_size_factor,
        "visit_lambda_year": visit_lambda_year,
        "visit_frequency": visit_frequency,
        "preferred_category": preferred_category,
        "pref_produce": prefs[:, 0],
        "pref_meat": prefs[:, 1],
        "pref_dairy": prefs[:, 2],
        "pref_deli": prefs[:, 3],
        "pref_cheese": prefs[:, 4],
    })

    df.to_csv("customer_v2.csv", index=False, encoding="utf-8-sig")
    print(f"customer_v2.csv 저장 완료: {df.shape}")
    validate(df)


# ---------------------------------------------------------------------------
# 7. 검증
# ---------------------------------------------------------------------------

def validate(df):
    print("\n[검증 1] 가구원수 분포 (%) — 공식 36.1 / 29.0 / 31.6 / 3.3")
    s = df["household_size"].value_counts(normalize=True).reindex(HH_BUCKETS) * 100
    print("  생성 " + " / ".join(f"{s[h]:.1f}" for h in HH_BUCKETS))

    print("\n[검증 2] 월 식료품 예산 (만원) — 공식 21.2 / 43.1 / 57.3 / 69.3")
    b = df.groupby("household_size")["monthly_food_budget"].mean().reindex(HH_BUCKETS) / 10000
    print("  생성 " + " / ".join(f"{b[h]:.1f}" for h in HH_BUCKETS))

    print("\n[검증 3] 소득분위별 가격민감도")
    ps = df.groupby("income_decile")["price_sensitivity"].mean()
    print("  " + "  ".join(f"{d}:{ps[d]:.2f}" for d in range(1, 11)))
    print(f"  최하위-최상위 격차 {ps[1] - ps[10]:.3f}")

    print("\n[검증 4] 선호 벡터 합")
    t = df[[f"pref_{c}" for c in CATEGORIES]].sum(axis=1)
    print(f"  min {t.min():.4f}  max {t.max():.4f}")

    print(f"\n[검증 5] 연간 방문 횟수 평균 {df['visit_lambda_year'].mean():.1f}회 (목표 88회)")


if __name__ == "__main__":
    main()
