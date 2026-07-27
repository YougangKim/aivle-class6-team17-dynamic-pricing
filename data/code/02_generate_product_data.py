"""
06_generate_product_data.py

KT AIVLE School 빅프로젝트
「AI 신선식품 수요예측 및 다이나믹 프라이싱 플랫폼」

목적:
    product.csv (상품 마스터) 생성
    - 이후 inventory.csv, transactions.csv, 모델 입력 데이터의 기준 마스터로 사용됨

대상 카테고리 (5개, 수산물 제외):
    produce(과채), dairy(유제품), meat(육류), cheese(치즈), deli(델리)

가격/마진 값은 프로젝트 정책(할인 상한 40%, 마진율 0.15~0.25 범위 등)에 맞춰
사람이 설계한 규칙(synthetic_rule) 기반으로 생성한 값이며, 실제 롯데마트 SKU를
그대로 복제한 값이 아닙니다.

폐기율(baseline_waste_rate) 역시 롯데마트에서 직접 실측한 값이 아니라,
외부 통계 자료를 참고하여 프로젝트에서 확정 적용한 값입니다. (외부 통계 기반 적용값)
"""

import os
import re
import random
from itertools import zip_longest

import numpy as np
import pandas as pd

# ────────────────────────────────
# 0. 기본 설정
# ────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# ⚠️ 실제 구글 드라이브 폴더명은 "빅프로젝트_데이터 최종" (언더바 + 공백 혼용)이므로
#    아래 경로 문자열을 임의로 변경하지 않는다.
SAVE_DIR = "/content/drive/MyDrive/빅프로젝트_데이터 최종/2_생성데이터/"
OUTPUT_FILENAME = "product.csv"

ALLOWED_CATEGORIES = ["produce", "dairy", "meat", "cheese", "deli"]
ALLOWED_SALES_TYPES = ["fixed_price", "weight_based"]
ALLOWED_UNITS = ["piece", "pack", "bag", "bottle", "kg"]
ALLOWED_DECAY_TYPES = ["slow", "medium", "fast"]

# 카테고리별 기준 폐기율 (외부 통계 기반 프로젝트 확정 적용값)
BASELINE_WASTE_RATE = {
    "produce": 0.056,
    "dairy": 0.003,
    "meat": 0.017,
    "cheese": 0.006,
    "deli": 0.016,
}

# max_discount_rate = 0.40 은 "수익이 보장되는 할인율"이 아니라
# 프로젝트 정책상 허용되는 "최대 할인 상한"이다.
# 정상 마진율이 0.15~0.25 수준이므로 40% 할인 시 원가 이하 판매가 될 수 있으나,
# 폐기 임박 상품의 경우 할인 판매 손실이 폐기 손실보다 작을 수 있어
# 향후 가격 최적화 모델에서 "할인 판매 손실 vs 예상 폐기 손실"을 비교해
# 실제 적용 할인율(0~40% 정수)을 결정하게 된다. 이 상수 값(0.40) 자체는 변경하지 않는다.
MAX_DISCOUNT_RATE = 0.40
MARKDOWN_ELIGIBLE_DEFAULT = 1
PRICE_SOURCE = "synthetic_rule"

# 마진율 허용 범위 (전체 공통 검증 기준)
MARGIN_RATE_MIN = 0.15
MARGIN_RATE_MAX = 0.25

# 프로젝트에서 확정된 전체 상품 수 및 카테고리별 상품 수
EXPECTED_PRODUCT_COUNT = 38
EXPECTED_CATEGORY_COUNTS = {
    "produce": 12,
    "dairy": 6,
    "meat": 8,
    "cheese": 5,
    "deli": 7,
}

# product_id 형식: "P" + 숫자 3자리 (예: P001, P038)
PRODUCT_ID_PATTERN = re.compile(r"^P\d{3}$")


# ────────────────────────────────
# 1. 저장 폴더 확인 및 생성
# ────────────────────────────────
def ensure_save_dir():
    """
    SAVE_DIR 경로가 없으면 새로 생성합니다.
    (구글 드라이브 마운트 경로 기준)
    """
    os.makedirs(SAVE_DIR, exist_ok=True)
    print(f"[확인] 저장 폴더 준비 완료: {SAVE_DIR}")


# ────────────────────────────────
# 2. product 데이터 생성
# ────────────────────────────────
def generate_product_data():
    """
    product.csv에 들어갈 38개 상품 데이터를 생성합니다.

    각 상품은 다음 정보를 가지고 있습니다.
    - 기본 정보: product_id, product_name, category, subcategory
    - 판매 방식: sales_type, unit, standard_weight_kg
    - 신선도/유통기한: shelf_life_days, freshness_decay_type
    - 가격: base_cost, base_price (margin_rate는 이 두 값으로 코드에서 재계산)
    - 정책값: max_discount_rate, markdown_eligible, esl_applicable
    - 폐기 기준값: baseline_waste_rate (카테고리 공통값, 외부 통계 기반 적용값)
    - price_source: 값 생성 방식 표시 ("synthetic_rule" 고정)

    [base_cost / base_price 단위 의미 — sales_type에 따라 다름]
        - sales_type == "fixed_price" (개/팩/봉/병 단위 정가 판매)
            · base_cost  : 1개·1팩·1봉·1병 등 "판매단위당" 기준 원가
            · base_price : 1개·1팩·1봉·1병 등 "판매단위당" 기준 판매가격
        - sales_type == "weight_based" (무게 × kg당 단가로 판매)
            · base_cost  : "kg당" 기준 원가
            · base_price : "kg당" 기준 판매단가
        즉 두 컬럼 모두 컬럼명은 동일하지만, sales_type에 따라
        "판매단위 1개당 금액"인지 "1kg당 금액"인지가 달라진다.

    [standard_weight_kg 의미]
        - sales_type == "fixed_price"
            · 해당 판매단위(1개/1팩/1봉/1병 등)의 "대표 중량"(kg)
        - sales_type == "weight_based"
            · base_cost/base_price가 이미 "kg당 단가"이므로
              standard_weight_kg은 항상 기준값 1.0으로 고정한다.
            · weight_based 상품의 실제 낱개 포장 무게(예: 실제 저울에 올린 고기 무게)는
              여기서 만들지 않고, 이후 inventory.csv 생성 단계에서
              개별 재고/포장 단위로 별도 생성할 예정이다.

    가격/원가는 실제 특정 브랜드 SKU를 복제한 값이 아니라,
    프로젝트 마진율 규칙(카테고리별 0.15~0.25 범위)에 맞춰
    설계자가 직접 부여한 대표 가상 가격입니다. [가정]

    반환:
        product_id, product_name, category, subcategory, sales_type, unit,
        standard_weight_kg, shelf_life_days, base_cost, base_price,
        margin_rate, max_discount_rate, markdown_eligible, esl_applicable,
        freshness_decay_type, baseline_waste_rate, price_source
        컬럼을 가진 pandas.DataFrame (38행)
    """

    # (product_name, category, subcategory, sales_type, unit,
    #  standard_weight_kg, shelf_life_days, base_cost, base_price,
    #  freshness_decay_type)
    raw_products = [
        # ── produce (과채) : 12개, 전량 fixed_price ──────────────
        ("사과", "produce", "apple", "fixed_price", "bag", 1.5, 10, 5200, 6500, "medium"),
        ("바나나", "produce", "banana", "fixed_price", "bag", 1.2, 5, 3200, 4000, "medium"),
        ("딸기", "produce", "strawberry", "fixed_price", "pack", 0.5, 3, 5600, 7000, "fast"),
        ("포도", "produce", "grape", "fixed_price", "pack", 1.0, 7, 6400, 8000, "medium"),
        ("토마토", "produce", "tomato", "fixed_price", "pack", 1.0, 7, 3600, 4500, "medium"),
        ("상추", "produce", "leafy_vegetable", "fixed_price", "pack", 0.3, 3, 1600, 2000, "fast"),
        ("깻잎", "produce", "leafy_vegetable", "fixed_price", "pack", 0.1, 3, 1200, 1500, "fast"),
        ("대파", "produce", "green_onion", "fixed_price", "pack", 0.5, 7, 1440, 1800, "medium"),
        ("양파", "produce", "root_vegetable", "fixed_price", "bag", 2.0, 14, 3520, 4400, "slow"),
        ("감자", "produce", "root_vegetable", "fixed_price", "bag", 2.0, 14, 4000, 5000, "slow"),
        ("버섯", "produce", "mushroom", "fixed_price", "pack", 0.3, 5, 2400, 3000, "medium"),
        ("파프리카", "produce", "paprika", "fixed_price", "pack", 0.5, 7, 3600, 4500, "medium"),

        # ── dairy (유제품) : 6개, 전량 fixed_price ───────────────
        ("흰우유", "dairy", "milk", "fixed_price", "bottle", 1.0, 10, 1800, 2200, "medium"),
        ("저지방우유", "dairy", "milk", "fixed_price", "bottle", 1.0, 10, 1900, 2300, "medium"),
        ("요구르트", "dairy", "yogurt", "fixed_price", "pack", 0.26, 14, 2800, 3400, "medium"),
        ("플레인요거트", "dairy", "yogurt", "fixed_price", "pack", 0.4, 14, 3000, 3600, "medium"),
        ("생크림", "dairy", "cream", "fixed_price", "bottle", 0.2, 10, 3200, 3900, "medium"),
        ("버터", "dairy", "butter", "fixed_price", "pack", 0.2, 30, 4500, 5500, "slow"),

        # ── meat (육류) : 8개, 대부분 weight_based ───────────────
        ("한우 등심", "meat", "beef", "weight_based", "kg", 1.0, 4, 65000, 79000, "fast"),
        ("한우 불고기", "meat", "beef", "weight_based", "kg", 1.0, 4, 52000, 63000, "fast"),
        ("돼지 삼겹살", "meat", "pork", "weight_based", "kg", 1.0, 5, 15500, 18500, "medium"),
        ("돼지 목살", "meat", "pork", "weight_based", "kg", 1.0, 5, 14000, 16800, "medium"),
        ("돼지 앞다리살", "meat", "pork", "weight_based", "kg", 1.0, 5, 10500, 12500, "medium"),
        ("닭가슴살", "meat", "chicken", "fixed_price", "pack", 0.5, 5, 4200, 5000, "medium"),
        ("닭볶음탕용", "meat", "chicken", "weight_based", "kg", 1.0, 4, 8500, 10200, "medium"),
        ("훈제오리", "meat", "duck", "fixed_price", "pack", 0.3, 14, 6800, 8200, "medium"),

        # ── cheese (치즈) : 5개, 전량 fixed_price ────────────────
        ("슬라이스치즈", "cheese", "sliced_cheese", "fixed_price", "pack", 0.4, 30, 5200, 6500, "medium"),
        ("모짜렐라치즈", "cheese", "mozzarella_cheese", "fixed_price", "pack", 0.2, 21, 4200, 5200, "medium"),
        ("체다치즈", "cheese", "cheddar_cheese", "fixed_price", "pack", 0.3, 30, 6400, 8000, "slow"),
        ("스트링치즈", "cheese", "string_cheese", "fixed_price", "pack", 0.2, 25, 3800, 4800, "medium"),
        ("리코타치즈", "cheese", "ricotta_cheese", "fixed_price", "pack", 0.2, 14, 4600, 5800, "medium"),

        # ── deli (델리) : 7개, 전량 fixed_price / fast ───────────
        ("초밥", "deli", "sushi", "fixed_price", "pack", 0.25, 1, 4800, 6000, "fast"),
        ("김밥", "deli", "gimbap", "fixed_price", "piece", 0.23, 1, 2400, 3000, "fast"),
        ("샐러드", "deli", "salad", "fixed_price", "pack", 0.2, 2, 3600, 4500, "fast"),
        ("닭강정", "deli", "fried_chicken", "fixed_price", "pack", 0.4, 2, 7200, 9000, "fast"),
        ("도시락", "deli", "lunch_box", "fixed_price", "piece", 0.45, 1, 5600, 7000, "fast"),
        ("샌드위치", "deli", "sandwich", "fixed_price", "piece", 0.2, 2, 3200, 4000, "fast"),
        ("즉석구이치킨", "deli", "roasted_chicken", "fixed_price", "piece", 0.9, 1, 8800, 11000, "fast"),
    ]

    records = []
    for idx, (name, category, subcategory, sales_type, unit, weight,
              shelf_life, cost, price, decay_type) in enumerate(raw_products, start=1):

        product_id = f"P{idx:03d}"
        esl_applicable = 1 if sales_type == "fixed_price" else 0
        margin_rate = round((price - cost) / price, 4)

        records.append({
            "product_id": product_id,
            "product_name": name,
            "category": category,
            "subcategory": subcategory,
            "sales_type": sales_type,
            "unit": unit,
            "standard_weight_kg": float(weight),
            "shelf_life_days": int(shelf_life),
            "base_cost": int(cost),
            "base_price": int(price),
            "margin_rate": margin_rate,
            "max_discount_rate": MAX_DISCOUNT_RATE,
            "markdown_eligible": MARKDOWN_ELIGIBLE_DEFAULT,
            "esl_applicable": esl_applicable,
            "freshness_decay_type": decay_type,
            "baseline_waste_rate": BASELINE_WASTE_RATE[category],
            "price_source": PRICE_SOURCE,
        })

    df = pd.DataFrame(records)

    # 컬럼 순서 고정
    column_order = [
        "product_id", "product_name", "category", "subcategory",
        "sales_type", "unit", "standard_weight_kg", "shelf_life_days",
        "base_cost", "base_price", "margin_rate", "max_discount_rate",
        "markdown_eligible", "esl_applicable", "freshness_decay_type",
        "baseline_waste_rate", "price_source",
    ]
    df = df[column_order]

    return df


# ────────────────────────────────
# 3. 검증
# ────────────────────────────────
def validate_product_data(df):
    """
    product.csv가 프로젝트 규칙을 만족하는지 자동 검증합니다.

    각 검증 항목은 "위반/불일치 건수"를 계산하며, 정상이라면 모두 0이어야 합니다.
    검증 결과 딕셔너리를 반환합니다. (출력은 main()에서 담당)
    """

    required_cols = [
        "product_id", "product_name", "category", "subcategory",
        "sales_type", "unit", "standard_weight_kg", "shelf_life_days",
        "base_cost", "base_price", "margin_rate", "max_discount_rate",
        "markdown_eligible", "esl_applicable", "freshness_decay_type",
        "baseline_waste_rate", "price_source",
    ]

    results = {}

    # ── 기존 검증 ──────────────────────────────────────────────

    # product_id 중복
    results["product_id 중복 건수"] = int(df["product_id"].duplicated().sum())

    # product_name 중복
    results["product_name 중복 건수"] = int(df["product_name"].duplicated().sum())

    # category 허용값 위반
    results["category 허용값 위반 건수"] = int((~df["category"].isin(ALLOWED_CATEGORIES)).sum())

    # 수산 카테고리 / 수산 상품 포함 여부
    seafood_keywords = ["수산", "생선", "오징어", "새우", "고등어", "연어", "조기", "명태"]
    seafood_in_category = df["category"].astype(str).str.contains("수산", na=False).sum()
    seafood_in_name = df["product_name"].astype(str).apply(
        lambda x: any(k in x for k in seafood_keywords)
    ).sum()
    results["수산 카테고리/상품 포함 건수"] = int(seafood_in_category + seafood_in_name)

    # sales_type 허용값 위반
    results["sales_type 허용값 위반 건수"] = int((~df["sales_type"].isin(ALLOWED_SALES_TYPES)).sum())

    # unit 허용값 위반
    results["unit 허용값 위반 건수"] = int((~df["unit"].isin(ALLOWED_UNITS)).sum())

    # base_price <= base_cost 오류
    results["base_price<=base_cost 오류 건수"] = int((df["base_price"] <= df["base_cost"]).sum())

    # margin_rate 계산 불일치 (base_price, base_cost로부터 재계산 후 비교)
    recalculated_margin = (df["base_price"] - df["base_cost"]) / df["base_price"]
    results["margin_rate 계산 불일치 건수"] = int(
        (~np.isclose(df["margin_rate"], recalculated_margin, atol=1e-4)).sum()
    )

    # margin_rate 범위 이탈 (0.15~0.25)
    results["margin_rate 범위(0.15~0.25) 이탈 건수"] = int(
        (~df["margin_rate"].between(MARGIN_RATE_MIN, MARGIN_RATE_MAX)).sum()
    )

    # max_discount_rate가 0.40이 아닌 건수
    results["max_discount_rate!=0.40 건수"] = int((df["max_discount_rate"] != MAX_DISCOUNT_RATE).sum())

    # markdown_eligible 허용값 위반 (0 또는 1)
    results["markdown_eligible 허용값 위반 건수"] = int((~df["markdown_eligible"].isin([0, 1])).sum())

    # fixed_price인데 esl_applicable != 1
    fixed_mask = df["sales_type"] == "fixed_price"
    results["fixed_price ESL 오류 건수"] = int((fixed_mask & (df["esl_applicable"] != 1)).sum())

    # weight_based인데 esl_applicable != 0
    weight_mask = df["sales_type"] == "weight_based"
    results["weight_based ESL 오류 건수"] = int((weight_mask & (df["esl_applicable"] != 0)).sum())

    # weight_based인데 unit != kg
    results["weight_based unit 오류 건수"] = int((weight_mask & (df["unit"] != "kg")).sum())

    # weight_based인데 standard_weight_kg != 1.0
    results["weight_based 표준중량 오류 건수"] = int(
        (weight_mask & (~np.isclose(df["standard_weight_kg"], 1.0))).sum()
    )

    # baseline_waste_rate가 카테고리 기준값과 다른 건수
    expected_waste = df["category"].map(BASELINE_WASTE_RATE)
    results["baseline_waste_rate 불일치 건수"] = int(
        (~np.isclose(df["baseline_waste_rate"], expected_waste)).sum()
    )

    # shelf_life_days < 1
    results["shelf_life_days<1 건수"] = int((df["shelf_life_days"] < 1).sum())

    # 필수 컬럼 결측치
    results["필수 컬럼 결측치 건수"] = int(df[required_cols].isna().sum().sum())

    # ── 신규 검증 ──────────────────────────────────────────────

    # freshness_decay_type 허용값 위반
    results["freshness_decay_type 허용값 위반 건수"] = int(
        (~df["freshness_decay_type"].isin(ALLOWED_DECAY_TYPES)).sum()
    )

    # 전체 상품 수 (38개) 불일치
    results["전체 상품 수 불일치 건수"] = int(len(df) != EXPECTED_PRODUCT_COUNT)

    # 카테고리별 상품 수 불일치
    # (누락된 카테고리, 개수가 다른 카테고리, 예상치 못한 카테고리를 모두 포함해서 카운트)
    actual_category_counts = df["category"].value_counts().to_dict()
    all_categories = set(EXPECTED_CATEGORY_COUNTS) | set(actual_category_counts)
    category_mismatch_count = sum(
        1 for cat in all_categories
        if EXPECTED_CATEGORY_COUNTS.get(cat, 0) != actual_category_counts.get(cat, 0)
    )
    results["카테고리별 상품 수 불일치 건수"] = int(category_mismatch_count)

    # base_cost, base_price 양수 검증
    results["base_cost<=0 건수"] = int((df["base_cost"] <= 0).sum())
    results["base_price<=0 건수"] = int((df["base_price"] <= 0).sum())

    # standard_weight_kg 양수 검증
    results["standard_weight_kg<=0 건수"] = int((df["standard_weight_kg"] <= 0).sum())

    # baseline_waste_rate 범위(0~1) 검증
    results["baseline_waste_rate 범위 이탈 건수"] = int(
        (~df["baseline_waste_rate"].between(0, 1)).sum()
    )

    # price_source 고정값 검증
    results["price_source 불일치 건수"] = int((df["price_source"] != PRICE_SOURCE).sum())

    # product_id 형식 검증 (P + 숫자 3자리)
    results["product_id 형식 오류 건수"] = int(
        (~df["product_id"].astype(str).str.match(PRODUCT_ID_PATTERN)).sum()
    )

    # product_id 연속성 검증 (P001 ~ P038까지 순서대로 빠짐없이 존재하는지)
    expected_ids = [f"P{i:03d}" for i in range(1, EXPECTED_PRODUCT_COUNT + 1)]
    actual_ids = df["product_id"].astype(str).tolist()
    continuity_errors = sum(
        1 for actual_id, expected_id in zip_longest(actual_ids, expected_ids, fillvalue=None)
        if actual_id != expected_id
    )
    results["product_id 연속성 오류 건수"] = int(continuity_errors)

    all_passed = all(v == 0 for v in results.values())
    results["__all_passed__"] = all_passed

    return results


# ────────────────────────────────
# 4. CSV 저장
# ────────────────────────────────
def save_csv(df, filename):
    """
    DataFrame을 SAVE_DIR 경로에 CSV로 저장합니다.
    - encoding="utf-8-sig" (엑셀 한글 깨짐 방지)
    - index=False
    """
    filepath = os.path.join(SAVE_DIR, filename)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"[저장 완료] {filepath}")
    return filepath


# ────────────────────────────────
# 5. main
# ────────────────────────────────
def main():
    # 1. 저장 폴더 확인 및 생성
    ensure_save_dir()

    # 2. product 데이터 생성
    df = generate_product_data()

    # 3. 검증 실행 (저장 전에 먼저 확인)
    results = validate_product_data(df)
    if not results["__all_passed__"]:
        print("\n[검증 실패] 아래 항목에서 오류가 발견되어 저장을 중단합니다.")
        for k, v in results.items():
            if k == "__all_passed__":
                continue
            if v != 0:
                print(f"  - {k}: {v}")
        raise ValueError("product.csv 검증 실패: 위 항목을 확인해주세요.")

    # 4. product.csv 저장
    save_csv(df, OUTPUT_FILENAME)

    # 5. 상위 5행 출력
    print("\n[상위 5행]")
    print(df.head(5).to_string(index=False))

    # 6. shape 출력
    print(f"\n[shape] {df.shape}")

    # 7. dtype 출력
    print("\n[dtype]")
    print(df.dtypes)

    # 8. 카테고리별 상품 수 출력
    print("\n[카테고리별 상품 수]")
    print(df["category"].value_counts().reindex(ALLOWED_CATEGORIES))

    # 9. 카테고리별 baseline_waste_rate 출력
    print("\n[카테고리별 baseline_waste_rate]")
    print(df.groupby("category")["baseline_waste_rate"].unique())

    # 10. 검증 결과 출력
    print("\n[검증 결과 상세]")
    for k, v in results.items():
        if k == "__all_passed__":
            continue
        print(f"  - {k}: {v}")

    if results["__all_passed__"]:
        print("\n=> product.csv 검증 통과")


if __name__ == "__main__":
    main()
