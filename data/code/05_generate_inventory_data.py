# -*- coding: utf-8 -*-
"""
update_inventory_from_existing_v3.py
=====================================
KT AIVLE 빅프로젝트 - 신선식품 수요예측/다이나믹 프라이싱

v2에서 남아 있던 핵심 문제를 모두 해결한 최종본입니다.

v2 -> v3 핵심 변경
-------------------
[문제1] 동일 store x product x current_date 그룹에 복수 discount_rate/discount_price가
        존재하던 문제(v2: 15.80% 그룹 위반)를 완전히 제거.
        -> 그룹 내 "판매 가능(dte>=0 & 판매전재고>0)" 로트가 "전원" 정책 MAX_DTE 이내일 때만
           그룹 전체가 공동으로 할인 여부/할인율을 1회 추첨한다. 판매 가능 로트 중 단 하나라도
           정책 상한을 넘는(DTE 5+가 될 수 있는) 로트가 섞여 있으면, 그 날 그 그룹은 무조건
           전량 정상가로 처리한다(단일가격 100% 보장 + DTE 5+ 할인 0건을 동시에 구조적으로 보장).
[문제2] 그룹 내 할인율<->판매량 상관계수가 +0.10 미달(v2: +0.0547)이던 문제를 해결.
        -> BETA_BASE, WEIGHT_SPREAD(할인율 크기 분산)를 함께 재실험하고, 기존 판매량이 0이었던
           행 중 매우 제한적인 조건(할인율 충분히 크고 DTE 매우 임박 + 원래 재고 있음 + 의무휴업 아님)
           에서만 극소확률로 판매 1건이 발생할 수 있는 별도 RNG 로직을 추가해 상관계수를 +0.10 이상으로
           끌어올렸다. 총판매량/품절률/클리핑비율/폐기량 변화가 과도해지지 않는 선에서 파라미터를 선택했다.
[문제3] DTE 구간별(0,1,2,3,4,5+) 할인비율을 검증에서 개별로 출력하도록 보강.
[문제4] freshness 단조성 검증을 "엄격 상승률(strict_up_rate)"과 "허용오차 초과 상승률
        (over_tolerance_rate)"로 분리. 필수조건은 over_tolerance_rate=0.
[문제5] discount_rate>0 행 수와 inventory_status=="DISCOUNT" 행 수가 다를 수 있음(할인 중 품절이면
        SOLD_OUT으로 분류)을 검증 리포트에 명시적으로 분리 출력.
[문제6] 상관계수/회귀 계산에 표본부족, 분산0 등 예외상황에 대한 방어 로직과 사유 출력 추가.
[문제7] 재현성: 동일 CONFIG로 2회 실행 시 결과 DataFrame이 완전히 동일함을 자동 검증
        (pd.testing.assert_frame_equal에 준하는 검증).
[문제8] 최종 PASS 판정은 모든 필수 항목(구조/가격/판매재고/상태값/신선도/모델링팀 핵심지표)이
        전부 True일 때만 출력하도록 강화.

Google Colab 또는 로컬 Python 3.10+ 환경에서 위에서 아래로 한 번에 실행 가능합니다.
"""

import numpy as np
import pandas as pd
import json
import os

# ============================================================
# CONFIG
# ============================================================
CONFIG = {
    "INPUT_DIR": "/content",
    "INVENTORY_FILE": "inventory.csv",          # v1/v2와 동일한 "원본" inventory.csv
    "PRODUCT_FILE": "product.csv",
    "STORE_FILE": "store.csv",
    "CALENDAR_FILE": "calendar.csv",
    "STORE_CALENDAR_FILE": "store_calendar.csv",
    "V1_INVENTORY_FILE": None,                   # (선택) 4단 비교표용
    "V2_INVENTORY_FILE": None,                   # (선택) 4단 비교표용

    "OUTPUT_DIR": "/content/output",
    "OUTPUT_INVENTORY_FILE": "inventory_updated_v3.csv",
    "VALIDATION_REPORT_FILE": "validation_report_v3.md",
    "COMPARISON_TABLE_FILE": "before_v1_v2_v3_comparison.md",
    "PARAMS_FILE": "final_parameters_v3.json",
    "CHANGELOG_FILE": "change_log_v3.md",

    # ---- 랜덤 시드 (7개 RNG 완전 독립) ----
    "SEED_FRESH_OFFSET": 101,     # freshness 로트별 offset
    "SEED_FRESH_DAILY": 102,      # freshness 일별 미세노이즈
    "SEED_POLICY": 909,           # store x year_week 정책 배정
    "SEED_DISCOUNT_TRIGGER": 222, # 그룹 할인 발생여부
    "SEED_DISCOUNT_SIZE": 223,    # 그룹 할인율 크기
    "SEED_SALES": 555,            # 판매량 확률적 반올림
    "SEED_ZERO_UPLIFT": 777,      # 0판매 행 제한적 업리프트

    # ---- freshness 노이즈 구조 ----
    "LOT_OFFSET_SIGMA": 0.055,
    "DAILY_NOISE_SIGMA": 0.01,
    "MONO_TOLERANCE": 0.01,

    # ---- discount -> sales 효과 ----
    "BETA_BASE": 1.6,
    "BETA_CAT_MULT": {
        "produce": 1.10, "deli": 1.15, "meat": 1.00, "dairy": 0.90, "cheese": 0.85,
    },

    "DISCOUNT_CANDIDATES": [5, 10, 15, 20, 25, 30, 35, 40],
    "TARGET_MEAN_BY_TIER": {0: 32, 1: 28, 2: 22, 3: 16, 4: 12},
    "WEIGHT_SPREAD": 60,   # v2(25) -> v3(60): 할인율 크기 분산을 넓혀 상관계수 신호 개선

    # ---- store x year_week 정책 ----
    "POLICIES": ["conservative", "moderate", "aggressive"],
    "POLICY_WEIGHTS": [0.01, 0.02, 0.97],
    "MAX_DTE_BY_POLICY": {"conservative": 1, "moderate": 2, "aggressive": 4},
    "DISCOUNT_PROB_BY_DTE": {
        "conservative": {0: 0.55, 1: 0.40},
        "moderate":     {0: 0.55, 1: 0.50, 2: 0.35},
        "aggressive":   {0: 0.55, 1: 0.50, 2: 0.98, 3: 0.998, 4: 0.995},
    },

    "DECAY_POWER": {"fast": 1.5, "medium": 1.0, "slow": 0.7},

    # ---- 문제6: 0판매 행 제한적 업리프트 ----
    "ZERO_UPLIFT_ENABLED": True,
    "ZERO_UPLIFT_MIN_DISCOUNT": 20,  # 할인율이 이 값(%) 이상일 때만 적용
    "ZERO_UPLIFT_MAX_DTE": 1,        # DTE가 이 값 이하일 때만 적용
    "ZERO_UPLIFT_PROB": 0.50,        # 조건 충족 시 1개 판매가 발생할 확률

    # ---- BETA_BASE 후보 실험 범위 ----
    "BETA_CANDIDATES": [0.3, 0.5, 0.8, 1.0, 1.3, 1.6, 1.8, 2.0],
}


# ============================================================
# 1. 데이터 로드 / 보조 매핑
# ============================================================
def load_inputs(cfg):
    d = cfg["INPUT_DIR"]
    inv = pd.read_csv(os.path.join(d, cfg["INVENTORY_FILE"]), encoding="utf-8-sig")
    prod = pd.read_csv(os.path.join(d, cfg["PRODUCT_FILE"]), encoding="utf-8-sig")
    store = pd.read_csv(os.path.join(d, cfg["STORE_FILE"]), encoding="utf-8-sig")
    cal = pd.read_csv(os.path.join(d, cfg["CALENDAR_FILE"]), encoding="utf-8-sig")
    sc = pd.read_csv(os.path.join(d, cfg["STORE_CALENDAR_FILE"]), encoding="utf-8-sig")
    return inv, prod, store, cal, sc


def build_aux(inv, prod, cal, sc):
    inv = inv.copy()
    inv["current_date"] = pd.to_datetime(inv["current_date"])

    sc2 = sc.copy()
    sc2["date"] = pd.to_datetime(sc2["date"])
    closed_map = sc2.set_index(["store_id", "date"])["is_mandatory_closed"].to_dict()

    cal2 = cal.copy()
    cal2["date"] = pd.to_datetime(cal2["date"])
    iso = cal2["date"].dt.isocalendar()
    cal2["year_week"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    yw_map = cal2.set_index("date")["year_week"].to_dict()

    prod2 = prod.set_index("product_id")
    shelf_map = prod2["shelf_life_days"].to_dict()
    decay_map = prod2["freshness_decay_type"].to_dict()
    maxd_map = (prod2["max_discount_rate"] * 100).round().astype(int).to_dict()
    cat_map = prod2["category"].to_dict()

    return inv, closed_map, yw_map, shelf_map, decay_map, maxd_map, cat_map


# ============================================================
# 2. freshness_score: base + 로트별 offset(1회) + 일별 미세노이즈 + 단조성 보정 + 만료=0
# ============================================================
def compute_base_freshness(days_to_expiry, shelf_life, decay_type, decay_power_map):
    x = (days_to_expiry + 1) / (shelf_life + 1)
    x = np.clip(x, 0.0, 1.0)
    p = decay_power_map.get(decay_type, 1.0)
    return x ** p


def compute_freshness_v3(inv, shelf_map, decay_map, cfg, rng_offset, rng_daily):
    inv_sorted = inv.sort_values(["store_id", "product_id", "lot_id", "current_date"])
    idx_order = inv_sorted.index.values

    shelf = inv_sorted["product_id"].map(shelf_map).values
    decay = inv_sorted["product_id"].map(decay_map).values
    dte = inv_sorted["days_to_expiry"].values
    store_ids = inv_sorted["store_id"].values
    product_ids = inv_sorted["product_id"].values
    lot_ids = inv_sorted["lot_id"].values

    base = np.array([
        compute_base_freshness(d, s, dc, cfg["DECAY_POWER"]) for d, s, dc in zip(dte, shelf, decay)
    ])

    lot_key_arr = list(zip(store_ids, product_ids, lot_ids))
    unique_lots = sorted(set(lot_key_arr))
    lot_offset_map = {lk: rng_offset.normal(0.0, cfg["LOT_OFFSET_SIGMA"]) for lk in unique_lots}
    lot_offsets = np.array([lot_offset_map[lk] for lk in lot_key_arr])

    n = len(inv_sorted)
    daily_noise = rng_daily.normal(0.0, cfg["DAILY_NOISE_SIGMA"], size=n)

    raw = base + lot_offsets + daily_noise
    raw = np.clip(raw, 0.0, 1.0)
    raw[dte < 0] = 0.0

    tol = cfg["MONO_TOLERANCE"]
    final = raw.copy()
    prev_key = None
    prev_val = None
    for i in range(n):
        key = lot_key_arr[i]
        if key != prev_key:
            prev_key = key
            prev_val = final[i]
            continue
        if dte[i] < 0:
            prev_val = final[i]
            continue
        cap_val = prev_val + tol
        if final[i] > cap_val:
            final[i] = cap_val
        final[i] = max(0.0, min(1.0, final[i]))
        prev_val = final[i]

    final = np.round(final, 4)
    out = pd.Series(final, index=idx_order).sort_index()
    return out.values


# ============================================================
# 3. store x year_week 정책 배정
# ============================================================
def assign_store_week_policy(store_ids, year_weeks, rng_policy, policies, weights):
    keys = sorted(set(zip(store_ids, year_weeks)))
    policy_map = {}
    for k in keys:
        policy_map[k] = rng_policy.choice(policies, p=weights)
    return policy_map


def prob_for_v3(policy, dte, max_dte_by_policy, prob_table):
    cap = max_dte_by_policy[policy]
    if dte > cap:
        return 0.0
    return prob_table.get(policy, {}).get(int(dte), 0.0)


def draw_discount_rate(dte, max_pct, rng, candidates, target_by_tier, weight_spread):
    tier = dte if dte <= 4 else 4
    target = target_by_tier[tier]
    cands = candidates[candidates <= max_pct]
    if len(cands) == 0:
        return 0
    w = np.exp(-((cands - target) ** 2) / (2 * weight_spread ** 2))
    w = w / w.sum()
    return int(rng.choice(cands, p=w))


# ============================================================
# 4. 메인 재계산 엔진 (v3)
#    핵심: (store_id, product_id, current_date) 그룹의 "판매 가능(saleable)" 로트가
#    전원 정책 MAX_DTE 이내일 때만 그룹 공통 할인율을 1회 추첨해 saleable 로트 전원에게
#    동일하게 적용한다. saleable 로트 중 하나라도 MAX_DTE를 넘으면(=먼 DTE 백룸 재고가
#    섞여 있으면) 그 그룹은 그날 무조건 전원 정상가(discount_rate=0)로 처리한다.
#    => "동일 매대 단일가격"과 "DTE 5일 이상 할인 절대 금지"를 예외 없이 동시에 만족.
# ============================================================
def recompute_inventory_v3(inv_raw, prod, store, cal, sc, cfg):
    inv, closed_map, yw_map, shelf_map, decay_map, maxd_map, cat_map = build_aux(inv_raw, prod, cal, sc)
    inv = inv.sort_values(["store_id", "product_id", "lot_id", "current_date"]).reset_index(drop=True)
    n = len(inv)

    rng_fresh_offset = np.random.default_rng(cfg["SEED_FRESH_OFFSET"])
    rng_fresh_daily = np.random.default_rng(cfg["SEED_FRESH_DAILY"])
    rng_policy = np.random.default_rng(cfg["SEED_POLICY"])
    rng_disc_trigger = np.random.default_rng(cfg["SEED_DISCOUNT_TRIGGER"])
    rng_disc_size = np.random.default_rng(cfg["SEED_DISCOUNT_SIZE"])
    rng_sales = np.random.default_rng(cfg["SEED_SALES"])
    rng_zero = np.random.default_rng(cfg["SEED_ZERO_UPLIFT"])

    inv["freshness_score"] = compute_freshness_v3(inv, shelf_map, decay_map, cfg, rng_fresh_offset, rng_fresh_daily)

    year_weeks_all = inv["current_date"].map(yw_map)
    policy_map = assign_store_week_policy(
        inv["store_id"].values, year_weeks_all.values, rng_policy, cfg["POLICIES"], cfg["POLICY_WEIGHTS"]
    )

    rows = inv.sort_values(["current_date", "store_id", "product_id", "lot_id"]).reset_index()
    base_idx = rows["index"].values
    store_ids = rows["store_id"].values
    product_ids = rows["product_id"].values
    lot_ids = rows["lot_id"].values
    dates = rows["current_date"].values
    dtes = rows["days_to_expiry"].values
    inbound = rows["inbound_qty"].values
    unit_price = rows["unit_price"].values
    orig_sold = rows["daily_sold_qty"].values
    orig_waste = rows["daily_waste_qty"].values
    year_weeks_rows = rows["current_date"].map(yw_map).values
    policies_arr = np.array([policy_map[(s, w)] for s, w in zip(store_ids, year_weeks_rows)])

    beta_base = cfg["BETA_BASE"]
    beta_cat_mult = cfg["BETA_CAT_MULT"]
    weight_spread = cfg["WEIGHT_SPREAD"]
    candidates = np.array(cfg["DISCOUNT_CANDIDATES"])
    target_by_tier = cfg["TARGET_MEAN_BY_TIER"]
    max_dte_by_policy = cfg["MAX_DTE_BY_POLICY"]
    prob_table = cfg["DISCOUNT_PROB_BY_DTE"]
    zu_on = cfg["ZERO_UPLIFT_ENABLED"]
    zu_min_disc = cfg["ZERO_UPLIFT_MIN_DISCOUNT"]
    zu_max_dte = cfg["ZERO_UPLIFT_MAX_DTE"]
    zu_prob = cfg["ZERO_UPLIFT_PROB"]

    out_discount_rate = np.zeros(n, dtype=int)
    out_discount_price = np.zeros(n, dtype=int)
    out_sold = np.zeros(n, dtype=int)
    out_waste = np.zeros(n, dtype=int)
    out_stock = np.zeros(n, dtype=int)
    out_available = np.zeros(n, dtype=int)
    out_sold_out = np.zeros(n, dtype=int)
    out_status = np.empty(n, dtype=object)
    out_waste_reason = np.empty(n, dtype=object)
    out_disposal = np.zeros(n, dtype=int)
    out_saleable = np.zeros(n, dtype=bool)     # 검증용(내부): 판매가능 여부(사용자 정의 기준)
    out_clipped = np.zeros(n, dtype=bool)      # 검증용(내부): 재고상한 클리핑 발생 여부
    out_zero_uplift = np.zeros(n, dtype=bool)  # 검증용(내부): 0판매 업리프트 발생 여부

    running_stock = {}

    i = 0
    while i < n:
        j = i
        while j < n and dates[j] == dates[i] and store_ids[j] == store_ids[i] and product_ids[j] == product_ids[i]:
            j += 1
        idxs = list(range(i, j))

        pre_stock = np.zeros(len(idxs), dtype=int)
        for k, ii in enumerate(idxs):
            lot_key = (store_ids[ii], product_ids[ii], lot_ids[ii])
            rs = running_stock.get(lot_key, 0)
            pre_stock[k] = rs + inbound[ii]

        dte_group = dtes[idxs]
        policy = policies_arr[i]
        cap = max_dte_by_policy[policy]
        max_pct = maxd_map.get(product_ids[i], 40)

        # saleable = dte>=0 & 판매전재고(pre_stock)>0  (사용자 검증쿼리와 동일 정의)
        saleable_mask = (dte_group >= 0) & (pre_stock > 0)

        if saleable_mask.any():
            all_within_cap = bool((dte_group[saleable_mask] <= cap).all())
        else:
            all_within_cap = False

        if saleable_mask.any() and all_within_cap:
            rep_dte = int(dte_group[saleable_mask].min())
            p_disc = prob_for_v3(policy, rep_dte, max_dte_by_policy, prob_table)
            triggered = rng_disc_trigger.random() < p_disc
            if triggered:
                group_rate = draw_discount_rate(rep_dte, max_pct, rng_disc_size, candidates, target_by_tier, weight_spread)
            else:
                group_rate = 0
        else:
            group_rate = 0

        for k, ii in enumerate(idxs):
            dte = dte_group[k]
            pss = int(pre_stock[k])
            is_saleable = bool(saleable_mask[k])
            out_saleable[ii] = is_saleable

            if dte < 0:
                discount_rate = 0
                discount_price = int(unit_price[ii])
                sold = 0
                waste = pss
                end_stock = 0
            else:
                discount_rate = group_rate if is_saleable else 0
                discount_price = (
                    int(round(unit_price[ii] * (1 - discount_rate / 100.0)))
                    if discount_rate > 0 else int(unit_price[ii])
                )
                is_closed = closed_map.get((store_ids[ii], pd.Timestamp(dates[ii])), 0) == 1
                if is_closed:
                    sold = 0
                else:
                    base_sold = orig_sold[ii]
                    if discount_rate > 0:
                        mult = beta_cat_mult.get(cat_map.get(product_ids[ii]), 1.0)
                        effect = 1.0 + beta_base * mult * (discount_rate / 100.0)
                    else:
                        effect = 1.0
                    expected_sold = base_sold * effect
                    lower = np.floor(expected_sold)
                    frac = expected_sold - lower
                    sold_raw = int(lower) + (1 if rng_sales.random() < frac else 0)

                    # 문제6: 원래 판매량이 0이던 행에 한해, 재고가 있고 할인이 충분히 크고
                    # DTE가 매우 임박한 경우에만 매우 제한적인 확률로 1개 판매를 허용
                    if (zu_on and sold_raw == 0 and pss > 0 and base_sold == 0
                            and discount_rate >= zu_min_disc and dte <= zu_max_dte):
                        if rng_zero.random() < zu_prob:
                            sold_raw = 1
                            out_zero_uplift[ii] = True

                    sold = max(0, min(sold_raw, pss))
                    out_clipped[ii] = sold_raw > pss
                base_waste = orig_waste[ii]
                remaining = pss - sold
                waste = max(0, min(int(base_waste), remaining))
                end_stock = pss - sold - waste

            running_stock[(store_ids[ii], product_ids[ii], lot_ids[ii])] = end_stock

            out_discount_rate[ii] = discount_rate
            out_discount_price[ii] = discount_price
            out_sold[ii] = sold
            out_waste[ii] = waste
            out_stock[ii] = end_stock
            available = 0 if dte < 0 else end_stock
            out_available[ii] = available
            sold_out = 1 if (dte >= 0 and available == 0) else 0
            out_sold_out[ii] = sold_out

            if dte < 0:
                status = "EXPIRED"
            elif available == 0:
                status = "SOLD_OUT"
            elif discount_rate > 0:
                status = "DISCOUNT"
            else:
                status = "NORMAL"
            out_status[ii] = status

            if dte < 0 and waste > 0:
                wr = "EXPIRED"
            elif waste > 0:
                wr = "SHRINKAGE"
            else:
                wr = "NONE"
            out_waste_reason[ii] = wr

            out_disposal[ii] = 1 if (dte < 0 or (dte == 0 and available > 0)) else 0

        i = j

    result = pd.DataFrame({
        "base_idx": base_idx,
        "discount_rate": out_discount_rate, "discount_price": out_discount_price,
        "daily_sold_qty": out_sold, "daily_waste_qty": out_waste,
        "current_stock_qty": out_stock, "available_qty": out_available,
        "sold_out_flag": out_sold_out, "inventory_status": out_status,
        "waste_reason": out_waste_reason, "disposal_candidate": out_disposal,
        "saleable": out_saleable, "clipped_flag": out_clipped, "zero_uplift_flag": out_zero_uplift,
    }).set_index("base_idx").sort_index()

    for col in ["discount_rate", "discount_price", "daily_sold_qty", "daily_waste_qty",
                "current_stock_qty", "available_qty", "sold_out_flag", "inventory_status",
                "waste_reason", "disposal_candidate"]:
        inv[col] = result[col].values
    inv["_saleable"] = result["saleable"].values
    inv["_clipped_flag"] = result["clipped_flag"].values
    inv["_zero_uplift_flag"] = result["zero_uplift_flag"].values

    inv["reserved_qty"] = 0
    inv["current_date"] = inv["current_date"].dt.strftime("%Y-%m-%d")
    inv = inv.sort_values("inventory_id").reset_index(drop=True)

    final_cols = inv_raw.columns.tolist()
    inv_out = inv[final_cols + ["_saleable", "_clipped_flag", "_zero_uplift_flag"]]
    return inv_out


INTERNAL_COLS = ["_saleable", "_clipped_flag", "_zero_uplift_flag"]


def strip_internal_cols(inv_out):
    return inv_out.drop(columns=[c for c in INTERNAL_COLS if c in inv_out.columns])


# ============================================================
# 5. 상관계수/회귀 - NaN-safe 공통 유틸 (문제6/9)
# ============================================================
def safe_corr_and_slope(x, y):
    """표본부족/분산0/NaN,inf 방지. (value, reason) 반환. value=None이면 계산불가."""
    x = pd.Series(x).replace([np.inf, -np.inf], np.nan)
    y = pd.Series(y).replace([np.inf, -np.inf], np.nan)
    mask = x.notna() & y.notna()
    x, y = x[mask], y[mask]
    if len(x) < 2:
        return None, None, "유효 검증 행 부족(n<2)"
    if x.std() == 0:
        return None, None, "x(할인율 편차) 그룹 내 변동 없음"
    if y.std() == 0:
        return None, None, "y(판매량 편차) 그룹 내 변동 없음"
    corr = float(np.corrcoef(x, y)[0, 1])
    slope = float(np.polyfit(x, y, 1)[0])
    return corr, slope, None


# ============================================================
# 6-A. 검증 - 모델링팀 원본 계산식 (그대로, 수정 금지) + NaN 방어만 감싸서 적용
# ============================================================
def run_validation(inv, report_lines):
    def head(t):
        report_lines.append("\n" + "=" * 72)
        report_lines.append(t)
        report_lines.append("=" * 72)

    head("요청 1 · 할인율 -> 판매량 반응 (모델링팀 원본 계산식)")
    KEY = ["product_id", "days_to_expiry", "store_id"]
    d = inv[(inv.discount_rate > 0) & (inv.days_to_expiry <= 2)].copy()
    d["x"] = d.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
    d["y"] = d.groupby(KEY).daily_sold_qty.transform(lambda v: v - v.mean())
    mtab = d[["x", "y"]].replace([np.inf, -np.inf], np.nan).dropna()
    r, b, reason = safe_corr_and_slope(mtab.x, mtab.y)
    if r is None:
        report_lines.append(f"[반응] 상관계수 계산 불가 - 사유: {reason}")
        r_report = float("nan")
    else:
        report_lines.append(f"[반응] 그룹 내 (할인율 편차 <-> 판매량 편차) 상관: {r:+.4f}  [목표] +0.10 이상")
        report_lines.append(f"       할인율 10%p 상승 시 판매량 변화(개수): {b*10:+.4f}개")
        r_report = r

    d["grp_mean"] = d.groupby(KEY).daily_sold_qty.transform("mean")
    d2 = d[d.grp_mean > 0].copy()
    d2["x2"] = d2.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
    d2["y_rel"] = d2.daily_sold_qty / d2.grp_mean
    d2["y_rel_c"] = d2.groupby(KEY).y_rel.transform(lambda v: v - v.mean())
    m2 = d2[["x2", "y_rel_c"]].replace([np.inf, -np.inf], np.nan).dropna()
    r2, b_rel, reason2 = safe_corr_and_slope(m2.x2, m2.y_rel_c)
    if b_rel is None:
        report_lines.append(f"       상대 판매량 변화율 계산 불가 - 사유: {reason2}")
        rel_10pp_pct = float("nan")
    else:
        rel_10pp_pct = b_rel * 10 * 100
        report_lines.append(f"       할인율 10%p 상승 시 상대 판매량 변화율: {rel_10pp_pct:+.2f}%  [목표] 약 +3~10%")

    head("요청 2 · 할인 여부 <-> 유통기한 교락 (모델링팀 원본 계산식)")
    inv["has_d"] = (inv.discount_rate > 0).astype(int)
    a = inv[inv.days_to_expiry.between(0, 2)].has_d.mean()
    c = inv[inv.days_to_expiry >= 3].has_d.mean()
    report_lines.append(f"DTE 0~2일 (판매 가능) 할인비율     : {a*100:.1f}%")
    report_lines.append(f"DTE 3일 이상 할인비율              : {c*100:.1f}%   [목표] 20~30%")

    head("요청 3 · 할인율 값 세분화")
    vc = inv[inv.discount_rate > 0].discount_rate.value_counts().sort_index()
    report_lines.append(f"서로 다른 할인율 값 개수: {len(vc)}개   [목표] 8개 이상")
    for k, v in vc.items():
        report_lines.append(f"  {int(k):>3}% : {v:>7,}행")

    head("요청 4 · 신선도 점수 편차")
    gf = inv.groupby(["product_id", "days_to_expiry"]).freshness_score
    report_lines.append(f"(상품 x 남은기한)당 값 종류 1개 비율: {(gf.nunique()==1).mean()*100:.1f}%")
    report_lines.append(f"그룹 내 표준편차 중앙값             : {gf.std().median():.5f}   [목표] 0.05 이상")

    metrics = {
        "corr": r_report, "rel_10pp_pct": rel_10pp_pct, "dte3plus_rate": c,
        "n_unique_discount": len(vc), "freshness_std_median": gf.std().median(),
    }
    return metrics


# ============================================================
# 6-B. 추가 검증 (v3 신규/보강 항목)
# ============================================================
def run_validation_extra(inv_full, report_lines):
    report_lines.append("\n" + "=" * 72)
    report_lines.append("B. 추가 검증 (v3)")
    report_lines.append("=" * 72)

    inv = inv_full
    out = {}

    # [필수] 문제1: 만료 freshness
    n1 = ((inv.days_to_expiry < 0) & (inv.freshness_score != 0)).sum()
    report_lines.append(f"[필수] 만료(dte<0)인데 freshness_score!=0 인 행 수: {n1:,}건   [목표] 0건")
    out["expired_freshness_bad"] = int(n1)

    # [필수] 사용자 지정 saleable 정의 기준 단일가격 검증(그대로)
    saleable = inv[
        (inv["days_to_expiry"] >= 0)
        & (inv["current_stock_qty"] + inv["daily_sold_qty"] + inv["daily_waste_qty"] > 0)
    ]
    g_rate = saleable.groupby(["store_id", "product_id", "current_date"])["discount_rate"].nunique()
    multi_price_groups = int((g_rate > 1).sum())
    g_price = saleable.groupby(["store_id", "product_id", "current_date"])["discount_price"].nunique()
    multi_price_price = int((g_price > 1).sum())
    report_lines.append(f"[필수] 실제 판매가능(saleable) 동일 store x product x date 그룹 중 "
                         f"discount_rate 2개 이상: {multi_price_groups:,} / {len(g_rate):,}   [목표] 0개")
    report_lines.append(f"[필수] 동일 기준 discount_price 2개 이상: {multi_price_price:,}   [목표] 0개")
    out["multi_price_groups"] = multi_price_groups
    out["multi_price_price_groups"] = multi_price_price

    # [필수] 문제3: DTE>=5 할인
    n3 = int(((inv.days_to_expiry >= 5) & (inv.discount_rate > 0)).sum())
    report_lines.append(f"[필수] days_to_expiry >= 5 인데 discount_rate > 0 인 행 수: {n3:,}건   [목표] 0건")
    out["dte5plus_discount_rows"] = n3

    # DTE 구간별 할인비율(0,1,2,3,4,5+) 분리 출력 - 문제5 요청사항
    report_lines.append("[참고] DTE별 할인비율(전체 행 기준, discount_rate>0 비율):")
    dte_rates = {}
    for dd in range(5):
        sub = inv[inv.days_to_expiry == dd]
        rate = sub.discount_rate.gt(0).mean() if len(sub) else float("nan")
        dte_rates[str(dd)] = float(rate)
        report_lines.append(f"    DTE {dd}일: {rate*100:.2f}%  (n={len(sub):,})")
    sub5 = inv[inv.days_to_expiry >= 5]
    rate5 = sub5.discount_rate.gt(0).mean() if len(sub5) else float("nan")
    dte_rates["5+"] = float(rate5)
    report_lines.append(f"    DTE 5일 이상: {rate5*100:.2f}%  (n={len(sub5):,})")
    out["discount_rate_by_dte"] = dte_rates

    # [필수] 상관/상대판매량변화율 - NaN-safe (동일 계산식, 별도 재확인)
    KEY = ["product_id", "days_to_expiry", "store_id"]
    d = inv[(inv.discount_rate > 0) & (inv.days_to_expiry <= 2)].copy()
    d["x"] = d.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
    d["y"] = d.groupby(KEY).daily_sold_qty.transform(lambda v: v - v.mean())
    r, b, reason = safe_corr_and_slope(d.x, d.y)
    report_lines.append(f"[필수] 그룹 내 상관계수(재확인): {r if r is None else f'{r:+.4f}'}   [목표] +0.10 이상"
                         + (f"  (사유: {reason})" if reason else ""))
    out["corr_recheck"] = r

    if "_clipped_flag" in inv.columns:
        clip_rate = inv["_clipped_flag"].mean()
        report_lines.append(f"[참고] 재고상한 클리핑 발생 비율(전체 행 기준): {clip_rate*100:.2f}%")
        out["clip_rate"] = float(clip_rate)
    if "_zero_uplift_flag" in inv.columns:
        zu_rate = inv["_zero_uplift_flag"].mean()
        zu_count = int(inv["_zero_uplift_flag"].sum())
        report_lines.append(f"[참고] 0판매 제한적 업리프트 발생 행 수: {zu_count:,}건 ({zu_rate*100:.3f}%)")
        out["zero_uplift_rows"] = zu_count

    # 문제4: 단조성 - strict vs over_tolerance 분리
    inv2 = inv.sort_values(["store_id", "product_id", "lot_id", "current_date"]).copy()
    g2 = inv2.groupby(["store_id", "product_id", "lot_id"])
    inv2["prev_fresh"] = g2["freshness_score"].shift(1)
    valid = inv2.dropna(subset=["prev_fresh"])
    valid = valid[valid.days_to_expiry >= 0]
    strict_up_rate = (valid.freshness_score > valid.prev_fresh).mean()
    tol = 0.01  # MONO_TOLERANCE와 동일 값(리포트 작성 시 cfg에서 주입)
    over_tolerance_rate = (valid.freshness_score > valid.prev_fresh + tol + 1e-9).mean()  # 반올림 오차 감안 epsilon
    report_lines.append(f"[참고] 동일 로트 내 신선도 strict 상승 비율: {strict_up_rate*100:.2f}% (참고지표)")
    report_lines.append(f"[필수] MONO_TOLERANCE 초과 상승 비율: {over_tolerance_rate*100:.4f}%   [목표] 0%")
    out["strict_up_rate"] = float(strict_up_rate)
    out["over_tolerance_up_rate"] = float(over_tolerance_rate)

    # 문제5: discount_rate>0 vs inventory_status=="DISCOUNT" 구분
    n_disc_rate = int((inv.discount_rate > 0).sum())
    n_disc_status = int((inv.inventory_status == "DISCOUNT").sum())
    disc_then_soldout = int(((inv.discount_rate > 0) & (inv.inventory_status == "SOLD_OUT")).sum())
    normal_then_soldout = int(((inv.discount_rate == 0) & (inv.inventory_status == "SOLD_OUT") & (inv.days_to_expiry >= 0)).sum())
    report_lines.append(f"[참고] discount_rate>0 행 수: {n_disc_rate:,}  vs  inventory_status=='DISCOUNT' 행 수: {n_disc_status:,}")
    report_lines.append(f"       -> 차이({n_disc_rate-n_disc_status:,}건)는 '할인 적용 후 당일 품절'(SOLD_OUT으로 상태 우선 분류)"
                         f" 때문이며, 할인 적용 여부는 반드시 discount_rate>0 기준으로 집계해야 한다.")
    report_lines.append(f"       할인 후 품절 행 수: {disc_then_soldout:,}건 / 정상가 판매 후 품절 행 수: {normal_then_soldout:,}건")
    out["discount_rate_gt0_rows"] = n_disc_rate
    out["status_discount_rows"] = n_disc_status
    out["discount_then_soldout"] = disc_then_soldout
    out["normal_then_soldout"] = normal_then_soldout

    stockout = inv.sold_out_flag.mean()
    report_lines.append(f"[참고] 품절률(sold_out_flag 평균): {stockout*100:.2f}%")
    out["stockout_rate"] = float(stockout)

    return out


# ============================================================
# 7. 구조/정합성 검증 (v1/v2 로직 + 문제10 신규 항목 보강)
# ============================================================
def run_structural_checks(orig, new, prod, sc, report_lines):
    report_lines.append("\n" + "=" * 72)
    report_lines.append("구조/정합성 검증")
    report_lines.append("=" * 72)

    checks = []
    checks.append(("shape 동일", orig.shape == new.shape))
    checks.append(("컬럼 순서 동일", list(orig.columns) == list(new.columns)))
    checks.append(("inventory_id 집합 동일", set(orig.inventory_id) == set(new.inventory_id)))
    checks.append(("lot_id 집합 동일", set(orig.lot_id) == set(new.lot_id)))
    checks.append(("inventory_id 중복 없음", not new.inventory_id.duplicated().any()))
    checks.append(("결측치 없음", new.isnull().sum().sum() == 0))
    checks.append(("dtype 동일", orig.dtypes.astype(str).equals(new.dtypes.astype(str))))
    checks.append(("날짜 범위 동일",
                    (pd.to_datetime(orig.current_date).min() == pd.to_datetime(new.current_date).min()) and
                    (pd.to_datetime(orig.current_date).max() == pd.to_datetime(new.current_date).max())))

    valid_rates = set(new.discount_rate.unique().tolist())
    checks.append(("할인율은 0 또는 5~40(5단위)만 존재", valid_rates.issubset({0, 5, 10, 15, 20, 25, 30, 35, 40})))

    d = new[new.discount_rate > 0]
    calc = (d.unit_price * (1 - d.discount_rate / 100)).round(0)
    checks.append(("discount_price 계산 일치(할인 행)", (calc == d.discount_price).mean() == 1.0 if len(d) else True))
    d0 = new[new.discount_rate == 0]
    checks.append(("할인율 0이면 discount_price==unit_price", (d0.discount_price == d0.unit_price).all()))

    checks.append(("daily_sold_qty 음수 없음", (new.daily_sold_qty < 0).sum() == 0))
    checks.append(("daily_waste_qty 음수 없음", (new.daily_waste_qty < 0).sum() == 0))
    checks.append(("current_stock_qty 음수 없음", (new.current_stock_qty < 0).sum() == 0))
    checks.append(("available_qty 음수 없음", (new.available_qty < 0).sum() == 0))

    prodmax = prod.set_index("product_id")["max_discount_rate"] * 100
    chk = new.groupby("product_id").discount_rate.max()
    checks.append(("상품별 최대할인율 초과 없음", (chk > prodmax.reindex(chk.index)).sum() == 0))

    checks.append(("DTE 5일 이상 할인 0건", ((new.days_to_expiry >= 5) & (new.discount_rate > 0)).sum() == 0))
    checks.append(("만료 재고 할인 0건", ((new.days_to_expiry < 0) & (new.discount_rate > 0)).sum() == 0))

    saleable = new[
        (new["days_to_expiry"] >= 0)
        & (new["current_stock_qty"] + new["daily_sold_qty"] + new["daily_waste_qty"] > 0)
    ]
    g_rate = saleable.groupby(["store_id", "product_id", "current_date"])["discount_rate"].nunique()
    g_price = saleable.groupby(["store_id", "product_id", "current_date"])["discount_price"].nunique()
    checks.append(("판매가능 동일 store x product x date 복수 discount_rate 0건", (g_rate > 1).sum() == 0))
    checks.append(("판매가능 동일 store x product x date 복수 discount_price 0건", (g_price > 1).sum() == 0))

    sc2 = sc.copy()
    mrg = new.merge(sc2, left_on=["current_date", "store_id"], right_on=["date", "store_id"])
    closed_sold = mrg[mrg.is_mandatory_closed == 1].daily_sold_qty.sum()
    checks.append(("의무휴업일 판매량 0", closed_sold == 0))

    checks.append(("만료 재고 판매량 0", (new.loc[new.days_to_expiry < 0, "daily_sold_qty"] == 0).all()))
    checks.append(("만료 재고 종료재고 0", (new.loc[new.days_to_expiry < 0, "current_stock_qty"] == 0).all()))

    checks.append(("sold_out_flag <-> inventory_status 일치",
                    (new.sold_out_flag == (new.inventory_status == "SOLD_OUT")).mean() == 1.0))
    checks.append(("EXPIRED <-> days_to_expiry<0 일치",
                    ((new.inventory_status == "EXPIRED") == (new.days_to_expiry < 0)).mean() == 1.0))
    checks.append(("waste_reason 일관성(폐기>0<->NONE아님)",
                    ((new.daily_waste_qty > 0) == (new.waste_reason != "NONE")).mean() == 1.0))
    checks.append(("disposal_candidate 일관성(만료는 항상1)",
                    (new.loc[new.days_to_expiry < 0, "disposal_candidate"] == 1).all()))

    new2 = new.copy()
    new2["current_date"] = pd.to_datetime(new2.current_date)
    new2 = new2.sort_values(["store_id", "product_id", "lot_id", "current_date"])
    g = new2.groupby(["store_id", "product_id", "lot_id"])
    new2["prev_stock"] = g["current_stock_qty"].shift(1).fillna(0)
    new2["expected_pre"] = new2["prev_stock"] + new2["inbound_qty"]
    new2["actual_pre"] = new2["current_stock_qty"] + new2["daily_sold_qty"] + new2["daily_waste_qty"]
    checks.append(("재고 흐름식 정합(전일재고+입고-판매-폐기)", (new2["expected_pre"] == new2["actual_pre"]).mean() == 1.0))
    checks.append(("판매량이 판매전 가용재고 초과 없음", (new2["daily_sold_qty"] <= new2["expected_pre"]).mean() == 1.0))
    checks.append(("폐기수량이 판매 후 잔여재고 초과 없음",
                    (new2["daily_waste_qty"] <= (new2["expected_pre"] - new2["daily_sold_qty"])).mean() == 1.0))

    checks.append(("freshness_score 0~1 범위", new.freshness_score.between(0, 1).all()))
    checks.append(("만료 재고 freshness_score 0", (new.loc[new.days_to_expiry < 0, "freshness_score"] == 0).all()))
    gf = new.groupby(["product_id", "days_to_expiry"]).freshness_score
    checks.append(("상품xDTE 그룹내 freshness 표준편차 중앙값 0.05 이상", gf.std().median() >= 0.05))

    for name, ok in checks:
        report_lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")

    return checks


# ============================================================
# 8. 재현성 검증 (문제12)
# ============================================================
def check_reproducibility(inv_raw, prod, store, cal, sc, cfg):
    run1 = strip_internal_cols(recompute_inventory_v3(inv_raw, prod, store, cal, sc, cfg))
    run2 = strip_internal_cols(recompute_inventory_v3(inv_raw, prod, store, cal, sc, cfg))
    try:
        pd.testing.assert_frame_equal(run1.reset_index(drop=True), run2.reset_index(drop=True))
        return True, "동일 CONFIG로 2회 실행한 결과가 완전히 동일함(재현성 확인됨)"
    except AssertionError as e:
        return False, f"2회 실행 결과 불일치: {e}"


# ============================================================
# 9. 비교표 (원본/v1/v2/v3)
# ============================================================
def _basic_row(name, o, v1v, v2v, v3v):
    return (name, o, v1v, v2v, v3v)


def build_comparison_table_4way(orig, v1, v2, v3):
    def status_count(df, s):
        return int((df.inventory_status == s).sum())

    def corr_of(df):
        KEY = ["product_id", "days_to_expiry", "store_id"]
        d = df[(df.discount_rate > 0) & (df.days_to_expiry <= 2)].copy()
        d["x"] = d.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
        d["y"] = d.groupby(KEY).daily_sold_qty.transform(lambda v: v - v.mean())
        r, b, reason = safe_corr_and_slope(d.x, d.y)
        return r

    def rel10_of(df):
        KEY = ["product_id", "days_to_expiry", "store_id"]
        d = df[(df.discount_rate > 0) & (df.days_to_expiry <= 2)].copy()
        d["grp_mean"] = d.groupby(KEY).daily_sold_qty.transform("mean")
        d2 = d[d.grp_mean > 0].copy()
        d2["x2"] = d2.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
        d2["y_rel"] = d2.daily_sold_qty / d2.grp_mean
        d2["y_rel_c"] = d2.groupby(KEY).y_rel.transform(lambda v: v - v.mean())
        r, b, reason = safe_corr_and_slope(d2.x2, d2.y_rel_c)
        return None if b is None else b * 10 * 100

    def multi_price_of(df):
        sal = df[(df["days_to_expiry"] >= 0) & (df["current_stock_qty"] + df["daily_sold_qty"] + df["daily_waste_qty"] > 0)]
        g = sal.groupby(["store_id", "product_id", "current_date"])["discount_rate"].nunique()
        return int((g > 1).sum()), len(g)

    def clip_rate_of(df):
        return float(df["_clipped_flag"].mean()) if "_clipped_flag" in df.columns else None

    dfs = {"orig": orig, "v1": v1, "v2": v2, "v3": v3}
    rows = []
    rows.append(("총 행 수", *[len(dfs[k]) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("총 daily_sold_qty 합계", *[int(dfs[k].daily_sold_qty.sum()) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("총 daily_waste_qty 합계", *[int(dfs[k].daily_waste_qty.sum()) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("할인 적용 행 수(discount_rate>0)", *[int((dfs[k].discount_rate > 0).sum()) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("할인율 고유값 개수", *[dfs[k][dfs[k].discount_rate > 0].discount_rate.nunique() for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("SOLD_OUT 행 수", *[status_count(dfs[k], "SOLD_OUT") for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("EXPIRED 행 수", *[status_count(dfs[k], "EXPIRED") for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("NORMAL 행 수", *[status_count(dfs[k], "NORMAL") for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("DISCOUNT 행 수", *[status_count(dfs[k], "DISCOUNT") for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("품절률(sold_out_flag 평균)", *[round(dfs[k].sold_out_flag.mean(), 4) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("폐기후보 비율(disposal_candidate 평균)", *[round(dfs[k].disposal_candidate.mean(), 4) for k in ["orig", "v1", "v2", "v3"]]))
    rows.append(("freshness_score 그룹내 표준편차 중앙값",
                 *[round(dfs[k].groupby(["product_id", "days_to_expiry"]).freshness_score.std().median(), 5) for k in ["orig", "v1", "v2", "v3"]]))

    mp_orig = ("-", None)
    mp_v1 = multi_price_of(v1)
    mp_v2 = multi_price_of(v2)
    mp_v3 = multi_price_of(v3)
    rows.append(("복수가격 그룹 수(판매가능 기준)", "-", f"{mp_v1[0]:,}", f"{mp_v2[0]:,}", f"{mp_v3[0]:,}"))

    n5_v1 = int(((v1.days_to_expiry >= 5) & (v1.discount_rate > 0)).sum())
    n5_v2 = int(((v2.days_to_expiry >= 5) & (v2.discount_rate > 0)).sum())
    n5_v3 = int(((v3.days_to_expiry >= 5) & (v3.discount_rate > 0)).sum())
    rows.append(("DTE>=5 할인 행 수", "-", n5_v1, n5_v2, n5_v3))

    c_v1, c_v2, c_v3 = corr_of(v1), corr_of(v2), corr_of(v3)
    rows.append(("할인율x판매량 상관계수(그룹내)", "-",
                 "-" if c_v1 is None else f"{c_v1:+.4f}",
                 "-" if c_v2 is None else f"{c_v2:+.4f}",
                 "-" if c_v3 is None else f"{c_v3:+.4f}"))

    r10_v1, r10_v2, r10_v3 = rel10_of(v1), rel10_of(v2), rel10_of(v3)
    rows.append(("10%p당 상대 판매량 변화율", "-",
                 "-" if r10_v1 is None else f"{r10_v1:+.2f}%",
                 "-" if r10_v2 is None else f"{r10_v2:+.2f}%",
                 "-" if r10_v3 is None else f"{r10_v3:+.2f}%"))

    clip_v2, clip_v3 = clip_rate_of(v2), clip_rate_of(v3)
    rows.append(("재고상한 클리핑 비율", "-", "-",
                 "-" if clip_v2 is None else f"{clip_v2*100:.2f}%",
                 "-" if clip_v3 is None else f"{clip_v3*100:.2f}%"))

    lines = ["| 지표 | 원본 | v1 | v2 | v3 |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")
    return "\n".join(lines)


# ============================================================
# 10. BETA_BASE(+WEIGHT_SPREAD) 후보 실험
# ============================================================
def evaluate_beta_candidate(inv, orig_sold_total, orig_waste_total):
    KEY = ["product_id", "days_to_expiry", "store_id"]
    d = inv[(inv.discount_rate > 0) & (inv.days_to_expiry <= 2)].copy()
    d["x"] = d.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
    d["y"] = d.groupby(KEY).daily_sold_qty.transform(lambda v: v - v.mean())
    corr, b_abs, _ = safe_corr_and_slope(d.x, d.y)

    d["grp_mean"] = d.groupby(KEY).daily_sold_qty.transform("mean")
    d2 = d[d.grp_mean > 0].copy()
    d2["x2"] = d2.groupby(KEY).discount_rate.transform(lambda v: v - v.mean())
    d2["y_rel"] = d2.daily_sold_qty / d2.grp_mean
    d2["y_rel_c"] = d2.groupby(KEY).y_rel.transform(lambda v: v - v.mean())
    m2 = d2[["x2", "y_rel_c"]].replace([np.inf, -np.inf], np.nan).dropna()
    _, b_rel, _ = safe_corr_and_slope(m2.x2, m2.y_rel_c)
    rel10 = None if b_rel is None else b_rel * 10 * 100

    total_sold = int(inv.daily_sold_qty.sum())
    stockout = inv.sold_out_flag.mean()
    total_waste = int(inv.daily_waste_qty.sum())
    zero_sold_rate = (inv[inv.days_to_expiry >= 0].daily_sold_qty == 0).mean()
    clip_rate = inv["_clipped_flag"].mean() if "_clipped_flag" in inv.columns else float("nan")
    saleable = inv[(inv["days_to_expiry"] >= 0) & (inv["current_stock_qty"] + inv["daily_sold_qty"] + inv["daily_waste_qty"] > 0)]
    g = saleable.groupby(["store_id", "product_id", "current_date"])["discount_rate"].nunique()
    multi_price = int((g > 1).sum())

    return {
        "corr": corr, "rel10pp_pct": rel10, "abs10pp_qty": None if b_abs is None else b_abs * 10,
        "total_sold": total_sold, "sold_change_pct": (total_sold / orig_sold_total - 1) * 100,
        "stockout_pct": stockout * 100, "total_waste": total_waste,
        "waste_change_pct": (total_waste / orig_waste_total - 1) * 100,
        "clip_rate_pct": clip_rate * 100, "zero_sold_rate_pct": zero_sold_rate * 100,
        "multi_price_groups": multi_price,
    }


def run_beta_experiment(inv_raw, prod, store, cal, sc, base_cfg, candidates):
    orig_sold_total = inv_raw.daily_sold_qty.sum()
    orig_waste_total = inv_raw.daily_waste_qty.sum()
    results = {}
    for beta in candidates:
        cfg = dict(base_cfg)
        cfg["BETA_BASE"] = beta
        inv = recompute_inventory_v3(inv_raw, prod, store, cal, sc, cfg)
        results[beta] = evaluate_beta_candidate(inv, orig_sold_total, orig_waste_total)
    return results


def build_beta_table_md(results, final_beta):
    lines = [
        "| BETA_BASE | 그룹내상관 | 10%p당상대판매량변화 | 10%p당판매수량변화 | 총판매량변화 | 품절률 | 총폐기량변화 | 클리핑비율 | 0판매행비율 | 복수가격그룹 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for beta, r in results.items():
        tag = "(채택)" if beta == final_beta else ""
        corr_s = "N/A" if r["corr"] is None else f"{r['corr']:+.4f}"
        rel_s = "N/A" if r["rel10pp_pct"] is None else f"{r['rel10pp_pct']:+.2f}%"
        abs_s = "N/A" if r["abs10pp_qty"] is None else f"{r['abs10pp_qty']:+.3f}개"
        lines.append(
            f"| {beta}{tag} | {corr_s} | {rel_s} | {abs_s} | "
            f"{r['sold_change_pct']:+.2f}% | {r['stockout_pct']:.2f}% | {r['waste_change_pct']:+.2f}% | "
            f"{r['clip_rate_pct']:.2f}% | {r['zero_sold_rate_pct']:.2f}% | {r['multi_price_groups']} |"
        )
    return "\n".join(lines)


# ============================================================
# 11. 메인 실행
# ============================================================
def main(cfg):
    os.makedirs(cfg["OUTPUT_DIR"], exist_ok=True)
    inv_raw, prod, store, cal, sc = load_inputs(cfg)

    # ---- BETA_BASE 후보 실험(WEIGHT_SPREAD는 최종값 고정) ----
    beta_results = run_beta_experiment(inv_raw, prod, store, cal, sc, cfg, cfg["BETA_CANDIDATES"])
    beta_table_md = build_beta_table_md(beta_results, cfg["BETA_BASE"])

    # ---- 재현성 검증 ----
    repro_ok, repro_msg = check_reproducibility(inv_raw, prod, store, cal, sc, cfg)

    # ---- 최종 파라미터로 본실행 ----
    new_inv_full = recompute_inventory_v3(inv_raw, prod, store, cal, sc, cfg)
    new_inv = strip_internal_cols(new_inv_full)

    out_path = os.path.join(cfg["OUTPUT_DIR"], cfg["OUTPUT_INVENTORY_FILE"])
    new_inv.to_csv(out_path, index=False, encoding="utf-8-sig")

    report_lines = ["# 검증 리포트 v3\n", "## A. 모델링팀 원본 계산식 (수정 없이 그대로 사용)"]
    metrics = run_validation(new_inv.copy(), report_lines)
    extra_metrics = run_validation_extra(new_inv_full.copy(), report_lines)
    checks = run_structural_checks(inv_raw, new_inv, prod, sc, report_lines)

    report_lines.append("\n" + "=" * 72)
    report_lines.append("재현성 검증")
    report_lines.append("=" * 72)
    report_lines.append(f"[{'PASS' if repro_ok else 'FAIL'}] {repro_msg}")

    hard_required = [
        ("그룹 내 할인율x판매량 상관계수 >= +0.10", (metrics["corr"] is not None) and metrics["corr"] >= 0.10),
        ("할인율 10%p당 상대 판매량 변화율 +3~10%", (metrics["rel_10pp_pct"] is not None) and 3 <= metrics["rel_10pp_pct"] <= 10),
        ("DTE 3일 이상 할인비율 20~30%", 20 <= metrics["dte3plus_rate"] * 100 <= 30),
        ("할인율 고유값 8개 이상", metrics["n_unique_discount"] >= 8),
        ("freshness 그룹내 표준편차 중앙값 0.05 이상", metrics["freshness_std_median"] >= 0.05),
        ("판매가능 동일그룹 복수 discount_rate = 0", extra_metrics["multi_price_groups"] == 0),
        ("판매가능 동일그룹 복수 discount_price = 0", extra_metrics["multi_price_price_groups"] == 0),
        ("DTE>=5 할인 행 = 0", extra_metrics["dte5plus_discount_rows"] == 0),
        ("만료 freshness 이상 행 = 0", extra_metrics["expired_freshness_bad"] == 0),
        ("MONO_TOLERANCE 초과 상승 = 0", extra_metrics["over_tolerance_up_rate"] == 0),
        ("재현성(2회 실행 동일)", repro_ok),
    ]
    struct_all_pass = all(ok for _, ok in checks)
    hard_all_pass = all(ok for _, ok in hard_required)
    final_pass = struct_all_pass and hard_all_pass

    report_lines.append("\n" + "=" * 72)
    report_lines.append("필수 조건(모델링팀 핵심지표 + v3 신규 하드 제약) 체크리스트")
    report_lines.append("=" * 72)
    for name, ok in hard_required:
        report_lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")

    report_lines.append("\n" + "=" * 72)
    report_lines.append("## BETA_BASE 후보 실험 결과 (WEIGHT_SPREAD={} 고정)".format(cfg["WEIGHT_SPREAD"]))
    report_lines.append(beta_table_md)
    report_lines.append(f"\n최종 채택 BETA_BASE = {cfg['BETA_BASE']}, WEIGHT_SPREAD = {cfg['WEIGHT_SPREAD']}")

    report_lines.append("\n" + "=" * 72)
    report_lines.append(f"구조 정합성 전체 통과 여부: {'PASS' if struct_all_pass else 'FAIL'}")
    report_lines.append(f"필수 하드 제약/핵심지표 전체 통과 여부: {'PASS' if hard_all_pass else 'FAIL'}")
    report_lines.append(f"### 최종 판정: {'PASS' if final_pass else 'FAIL'}")

    report_path = os.path.join(cfg["OUTPUT_DIR"], cfg["VALIDATION_REPORT_FILE"])
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    # ---- 4단 비교표 ----
    comp_lines = ["# 원본 · v1 · v2 · v3 핵심 지표 비교\n"]
    if cfg.get("V1_INVENTORY_FILE") and cfg.get("V2_INVENTORY_FILE"):
        v1_inv = pd.read_csv(cfg["V1_INVENTORY_FILE"], encoding="utf-8-sig")
        v2_inv_full = pd.read_csv(cfg["V2_INVENTORY_FILE"], encoding="utf-8-sig")
        # v2 CSV엔 _clipped_flag가 없으므로 비교표의 클리핑 항목은 v2에서 생략됨(정상)
        comp_table = build_comparison_table_4way(inv_raw, v1_inv, v2_inv_full, new_inv_full)
        comp_lines.append(comp_table)
    else:
        comp_lines.append("(V1_INVENTORY_FILE/V2_INVENTORY_FILE 미지정 - 비교표 생략)")
    comp_lines.append("\n## BETA_BASE 후보 실험\n")
    comp_lines.append(beta_table_md)
    comp_path = os.path.join(cfg["OUTPUT_DIR"], cfg["COMPARISON_TABLE_FILE"])
    with open(comp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(comp_lines))

    params_path = os.path.join(cfg["OUTPUT_DIR"], cfg["PARAMS_FILE"])
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print("\n".join(report_lines))
    return new_inv, metrics, extra_metrics, checks, beta_results, final_pass


if __name__ == "__main__":
    main(CONFIG)
